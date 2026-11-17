#define _GNU_SOURCE
#include <napi/native_api.h>
#include <hilog/log.h>
#include <dlfcn.h>
#include <dirent.h>
#include <fcntl.h>
#include <stdlib.h>
#include <errno.h>
#include <signal.h>
#include <stdio.h>
#include <string.h>
#include <sys/ptrace.h>
#include <sys/prctl.h>
#include <sys/mman.h>
#include <pty.h>
#include <poll.h>
#include <time.h>
#include <sys/stat.h>
#include <sys/socket.h>
#include <sys/wait.h>
#include <sys/uio.h>
#include <sys/syscall.h>
#include <unistd.h>
#include <elf.h>

#define LOG(...) OH_LOG_Print(LOG_APP, LOG_INFO, 0xD005, "HarmonyPRoot", __VA_ARGS__)

static int wait_bounded(pid_t pid, int *status) {
    for (int i = 0; i < 100; ++i) {
        pid_t observed = waitpid(pid, status, WNOHANG);
        if (observed == pid) return 0;
        if (observed < 0 && errno != EINTR) return errno;
        usleep(20000);
    }
    return ETIMEDOUT;
}

static void reap(pid_t child) {
    int status;
    kill(child, SIGKILL);
    wait_bounded(child, &status);
}

/* Keep the outer HAP responsive while the child and tracees finish. */
static long long monotonic_ms(void) {
    struct timespec time;
    clock_gettime(CLOCK_MONOTONIC, &time);
    return time.tv_sec * 1000LL + time.tv_nsec / 1000000;
}

static int has_line(const char *text, const char *line) {
    size_t length = strlen(line);
    for (const char *p = text; (p = strstr(p, line)); ++p) {
        if ((p == text || p[-1] == '\n') && (p[length] == '\n' || p[length] == '\r'))
            return 1;
    }
    return 0;
}

static void drive_terminal(int input, int output, int is_pty, int transcript) {
    const char first[] = "if [ -t 0 ] && [ -t 1 ]; then printf '\\nTTY_CONFIRMED\\n'; fi; printf '\\nROUND_ONE\\n'\n";
    const char second[] = "printf '\\nROUND_TWO\\n'; exit 23\n";
    const char pty_second[] = "/bin/busybox stty size; printf '\\nROUND_TWO\\n'; exit 23\n";
    char text[4096] = {0};
    size_t length = 0;
    int sent_second = 0;
    (void)write(input, first, sizeof(first) - 1);
    long long deadline = monotonic_ms() + 6000;
    while (monotonic_ms() < deadline && length < sizeof(text) - 1) {
        struct pollfd ready = { .fd = output, .events = POLLIN };
        int rc = poll(&ready, 1, 100);
        if (rc < 0 && errno != EINTR) break;
        if (rc <= 0) continue;
        ssize_t count = read(output, text + length, sizeof(text) - 1 - length);
        if (count <= 0) break;
        (void)write(transcript, text + length, (size_t)count);
        length += (size_t)count;
        text[length] = 0;
        if (!sent_second && has_line(text, "ROUND_ONE")) {
            sent_second = 1;
            if (is_pty) {
                struct winsize resized = { .ws_row = 37, .ws_col = 91 };
                (void)ioctl(input, TIOCSWINSZ, &resized);
                (void)write(input, pty_second, sizeof(pty_second) - 1);
            } else {
                (void)write(input, second, sizeof(second) - 1);
            }
        }
    }
    dprintf(transcript, "\nTERMINAL_ROUNDS first=%d second=%d tty=%d resize=%d\n",
        has_line(text, "ROUND_ONE"), has_line(text, "ROUND_TWO"), has_line(text, "TTY_CONFIRMED"),
        has_line(text, "37 91"));
}

static int map_rx(const char *path) {
    int fd = open(path, O_RDONLY);
    if (fd < 0) return errno;
    void *map = mmap(NULL, 4096, PROT_READ | PROT_EXEC, MAP_PRIVATE, fd, 0);
    int error = map == MAP_FAILED ? errno : 0;
    if (!error) munmap(map, 4096);
    close(fd);
    return error;
}

struct ShellLaunch {
    const char *cwd;
    const char *command;
    char *const *environment;
    int pid;
    int stdin_fd;
    int stdout_fd;
    int stderr_fd;
    int status_fd;
};

static void close_pair(int pair[2]) {
    if (pair[0] >= 0) close(pair[0]);
    if (pair[1] >= 0) close(pair[1]);
}

static int shell_channel(int pair[2], int streaming) {
    return streaming ? socketpair(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0, pair) : pipe2(pair, O_CLOEXEC);
}

static int close_host_descriptors(int keep) {
    DIR *dir = opendir("/proc/self/fd");
    if (!dir) return errno;
    int own = dirfd(dir);
    struct dirent *entry;
    while ((entry = readdir(dir))) {
        char *end;
        long fd = strtol(entry->d_name, &end, 10);
        if (*end == 0 && fd > STDERR_FILENO && fd != own && fd != keep) close((int)fd);
    }
    closedir(dir);
    return 0;
}

static void run_proot(const char *stage, const char *directory, char *out, size_t size, struct ShellLaunch *shell) {
    Dl_info self;
    if (!dladdr((void *)run_proot, &self) || !self.dli_fname) {
        snprintf(out, size, "cannot find package library path");
        return;
    }
    char native[1024], executable[1100], loader[1100], root[1024], log_path[1024];
    snprintf(native, sizeof(native), "%s", self.dli_fname);
    char *slash = strrchr(native, '/');
    if (!slash) {
        snprintf(out, size, "unexpected library path: %s", native);
        return;
    }
    *slash = 0;
    snprintf(executable, sizeof(executable), "%s/libproot_exec.so", native);
    snprintf(loader, sizeof(loader), "%s/libproot_loader.so", native);
    snprintf(root, sizeof(root), "%s/alpine", directory);
    int secprobe = strstr(stage, "secprobe") != NULL;
    snprintf(log_path, sizeof(log_path), "%s/%s", directory, secprobe ? "proot-seccomp-probe.txt" : "proot-output.txt");
    if (strcmp(stage, "proot-map") == 0) {
        char guest_path[1100], packaged_path[1100];
        snprintf(guest_path, sizeof(guest_path), "%s/bin/busybox", root);
        snprintf(packaged_path, sizeof(packaged_path), "%s/libguest_busybox.so", native);
        int writable = map_rx(guest_path);
        int packaged = map_rx(packaged_path);
        void *map = mmap(NULL, 4096, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
        int anonymous = map == MAP_FAILED ? errno : 0;
        if (!anonymous) {
            anonymous = mprotect(map, 4096, PROT_READ | PROT_EXEC) < 0 ? errno : 0;
            munmap(map, 4096);
        }
        snprintf(out, size, "RX private-file errno=%d packaged-file errno=%d anonymous errno=%d",
            writable, packaged, anonymous);
        return;
    }
    int e = access(executable, X_OK) < 0 ? errno : 0;
    int l = access(loader, X_OK) < 0 ? errno : 0;
    LOG("native=%{public}s proot X_OK errno=%{public}d loader X_OK errno=%{public}d", native, e, l);
    char marker[1100];
    snprintf(marker, sizeof(marker), "%s/marker", root);
    if (!shell) unlink(marker);
    int fd = shell ? open("/dev/null", O_RDONLY | O_CLOEXEC) :
        open(log_path, O_RDWR | O_CREAT | O_TRUNC | O_CLOEXEC, 0600);
    if (fd < 0) {
        snprintf(out, size, "open output errno=%d", errno);
        return;
    }
    char loader_env[1150], temp_env[1100];
    snprintf(loader_env, sizeof(loader_env), "PROOT_LOADER=%s", loader);
    snprintf(temp_env, sizeof(temp_env), "PROOT_TMP_DIR=%s", directory);
    char *env[] = {loader_env, temp_env, "PATH=/bin:/usr/bin", "PROOT_NO_SECCOMP=1", NULL};
    if (strcmp(stage, "proot-default") == 0) env[3] = NULL;
    char *version[] = {executable, "--version", NULL};
    char *guest[16] = {
        executable, "--kill-on-exit", "-v", "0", "-r", root, "-w", "/",
        "/bin/sh", "-c",
        "set -e; printf 'GUEST_OK\\n'; /bin/busybox cat /etc/alpine-release; "
        "/bin/busybox uname -m; /bin/busybox id; "
        "printf 'pipeline-ok\\n' | /bin/busybox grep '^pipeline-ok$'; "
        "/bin/sh -c 'exit 37' || code=$?; test \"$code\" = 37; printf 'EXIT_37_OK\\n'; "
        "printf 'rootfs-write\\n' >/marker; /bin/busybox cat /marker",
        NULL
    };
    int diagnose = strstr(stage, "diag") != NULL;
    int accelerated = secprobe || strstr(stage, "fast") != NULL;
    if (diagnose) guest[3] = "2";
    else if (secprobe) guest[3] = "3";
    else if (accelerated) guest[3] = "1";
    int interactive = strstr(stage, "pty") != NULL;
    int node_test = strstr(stage, "node") != NULL;
    int dsh_test = secprobe || strstr(stage, "dsh") != NULL;
    int shellbench = strstr(stage, "shellbench") != NULL;
    int client = strstr(stage, "client") != NULL;
    int jitless = strstr(stage, "jitless") != NULL;
    if (interactive) {
        guest[9] = "-i";
        guest[10] = NULL;
    } else if (shellbench) {
        guest[7] = shell ? (char *)shell->cwd : "/workspace-native";
        guest[8] = "/bin/bash";
        guest[9] = "-c";
        guest[10] = "set -e -o pipefail; printf 'NATIVE_WEB_PROOT_SHELL_OK\n' | grep -Fx NATIVE_WEB_PROOT_SHELL_OK > result.txt; cat result.txt";
        if (shell) {
            guest[10] = "/bin/bash -c \"$1\" 3>&-; status=$?; printf '%03d' \"$status\" >&3; exit \"$status\"";
            guest[11] = "dsh-shell";
            guest[12] = (char *)shell->command;
            guest[13] = NULL;
        } else {
            guest[11] = NULL;
        }
    } else if (node_test || dsh_test) {
        guest[8] = "/bin/node";
        int argument = 9;
        if (jitless) guest[argument++] = "--jitless";
        if (strstr(stage, "shim")) {
            guest[argument++] = "--require";
            guest[argument++] = "/fetch-shim-boot.cjs";
        }
        guest[argument++] = secprobe ? "/dsh-seccomp-probe.cjs" : client ? "/dsh-client.cjs" : dsh_test ? "/dsh-probe.cjs" : "/node-probe.cjs";
        if (dsh_test && strstr(stage, "headless"))
            guest[argument++] = strstr(stage, "command") ? "headless-command" : strstr(stage, "patch") ? "headless-patch" : "headless";
        guest[argument] = NULL;
    }
    int guest_argc = 0;
    while (guest[guest_argc]) ++guest_argc;
    static const struct { const char *name; const char *guest; } packaged[] = {
        { "libguest_busybox.so", "/bin/sh" },
        { "libguest_busybox.so", "/bin/busybox" },
        { "libguest_musl.so", "/lib/ld-musl-aarch64.so.1" },
        { "libguest_musl.so", "/lib/libc.musl-aarch64.so.1" },
        { "libguest_node.so", "/bin/node" },
        { "libguest_bash.so", "/bin/bash" },
        { "libguest_gcc.so", "/usr/lib/libgcc_s.so.1" },
        { "libguest_readline.so", "/usr/lib/libreadline.so.8" },
        { "libguest_ncurses.so", "/usr/lib/libncursesw.so.6" },
        { "libguest_publish.so", "/harmony-publish.node" },
        { "libguest_stdcpp.so", "/usr/lib/libstdc++.so.6" },
        { "libguest_require_builtin.so", "/dsh/node_modules/node-addon-require-builtin-linux-arm64-musl/prebuilt/linux-arm64-musl-napi-v9.node" },
        { "libguest_dsh_system.so", "/dsh/node_modules/@deepseek-ai/node-addon-system-linux-arm64/bin/musl/system.node" },
        { "libguest_koffi.so", "/dsh/node_modules/@koromix/koffi-linux-arm64/musl_arm64/koffi.node" },
        { "libguest_landlock.so", "/dsh/node_modules/@deepseek-ai/node-addon-system-linux-arm64/bin/landlock-run" },
        { "libguest_rg.so", "/dsh/node_modules/@vscode/ripgrep-linux-arm64/bin/rg" },
        { "libguest_busybox.so", "/bin/cat" },
        { "libguest_busybox.so", "/bin/chmod" },
        { "libguest_busybox.so", "/bin/cp" },
        { "libguest_busybox.so", "/bin/cut" },
        { "libguest_busybox.so", "/bin/diff" },
        { "libguest_busybox.so", "/bin/env" },
        { "libguest_busybox.so", "/bin/find" },
        { "libguest_busybox.so", "/bin/grep" },
        { "libguest_busybox.so", "/bin/head" },
        { "libguest_busybox.so", "/bin/ls" },
        { "libguest_busybox.so", "/bin/mkdir" },
        { "libguest_busybox.so", "/bin/mv" },
        { "libguest_busybox.so", "/bin/rm" },
        { "libguest_busybox.so", "/bin/sed" },
        { "libguest_busybox.so", "/bin/sort" },
        { "libguest_busybox.so", "/bin/tail" },
        { "libguest_busybox.so", "/bin/touch" },
        { "libguest_busybox.so", "/bin/uname" },
        { "libguest_busybox.so", "/bin/wc" },
        { "libguest_busybox.so", "/bin/which" },
        { "libguest_busybox.so", "/bin/awk" },
        { "libguest_busybox.so", "/bin/basename" },
        { "libguest_busybox.so", "/bin/date" },
        { "libguest_busybox.so", "/bin/dirname" },
        { "libguest_busybox.so", "/bin/gzip" },
        { "libguest_busybox.so", "/bin/mktemp" },
        { "libguest_busybox.so", "/bin/sha256sum" },
        { "libguest_busybox.so", "/bin/sleep" },
        { "libguest_busybox.so", "/bin/tar" },
        { "libguest_busybox.so", "/bin/tr" },
        { "libguest_busybox.so", "/bin/xargs" },
        { "libguest_busybox.so", "/bin/base64" },
        { "libguest_busybox.so", "/bin/cmp" },
        { "libguest_busybox.so", "/bin/du" },
        { "libguest_busybox.so", "/bin/id" },
        { "libguest_busybox.so", "/bin/od" },
        { "libguest_busybox.so", "/bin/readlink" },
        { "libguest_busybox.so", "/bin/realpath" },
        { "libguest_busybox.so", "/bin/stat" },
        { "libguest_busybox.so", "/bin/tee" },
        { "libguest_busybox.so", "/bin/timeout" },
        { "libguest_busybox.so", "/bin/unzip" },
        { "libguest_busybox.so", "/bin/whoami" },
        { "libguest_tool_curl.so", "/usr/bin/curl" },
        { "libguest_tool_sqlite3.so", "/usr/bin/sqlite3" },
        { "libguest_rg.so", "/bin/rg" },
        { "libguest_sharp.so", "/dsh/node_modules/@img/sharp-linuxmusl-arm64/lib/sharp-linuxmusl-arm64-0.35.5.node" },
        { "libguest_vips.so", "/usr/lib/libvips-cpp.so.8.18.7" },
        { "libguest_vips.so", "/dsh/node_modules/@img/sharp-libvips-linuxmusl-arm64/lib/libvips-cpp.so.8.18.7" },
#include "guest-tools.inc"
    };
    enum { packaged_count = sizeof(packaged) / sizeof(*packaged) };
    char bind_options[packaged_count][1150];
    char dsh_binding[1150];
    char *bound_guest[packaged_count * 2 + sizeof(guest) / sizeof(*guest) + 8];
    int bound_count = 0;
    if (strstr(stage, "packaged")) {
        for (int n = 0; n < 8; ++n) bound_guest[bound_count++] = guest[n];
        if (dsh_test) {
            snprintf(dsh_binding, sizeof(dsh_binding), "%s/.dsh-0.2.2-rc.4/dsh:/dsh", root);
            bound_guest[bound_count++] = "-b";
            bound_guest[bound_count++] = dsh_binding;
        }
        size_t bindings = dsh_test ? packaged_count : node_test ? 9 : 4;
        for (size_t n = 0; n < bindings; ++n) {
            snprintf(bind_options[n], sizeof(bind_options[n]), "%s/%s:%s", native, packaged[n].name, packaged[n].guest);
            bound_guest[bound_count++] = "-b";
            bound_guest[bound_count++] = bind_options[n];
        }
        if (dsh_test) {
            bound_guest[bound_count++] = "-b";
            bound_guest[bound_count++] = "/dev/null:/dev/null";
            bound_guest[bound_count++] = "-b";
            bound_guest[bound_count++] = "/dev/urandom:/dev/urandom";
            if (access("/dev/zero", R_OK) == 0) {
                bound_guest[bound_count++] = "-b";
                bound_guest[bound_count++] = "/dev/zero:/dev/zero";
            }
        }
        for (int n = 8; n < guest_argc; ++n) bound_guest[bound_count++] = guest[n];
        bound_guest[bound_count] = NULL;
    }
    char **execution_argv = bound_count ? bound_guest : guest;
    int execution_argc = bound_count ? bound_count : guest_argc;
    typedef int (*proot_main_fn)(int, char *const []);
    proot_main_fn entry = NULL;
    if (strstr(stage, "embedded")) {
        void *library = dlopen("libproot_core.so", RTLD_NOW | RTLD_LOCAL);
        if (!library || !(entry = (proot_main_fn)dlsym(library, "main"))) {
            snprintf(out, size, "proot library: %s", dlerror());
            close(fd);
            return;
        }
    }
    void *loader_entry = NULL;
    if (entry) {
        void *module = dlopen("libproot_preloader.so", RTLD_NOW | RTLD_LOCAL);
        if (!module || !(loader_entry = dlsym(module, "ohos_guest_loader"))) {
            snprintf(out, size, "preload loader: %s", dlerror());
            close(fd);
            return;
        }
    }
    char address[32];
    snprintf(address, sizeof(address), "%lx", (unsigned long)loader_entry);
    int only_version = strstr(stage, "version") != NULL;
    int master = -1, slave = -1;
    int in_pipe[2] = {-1, -1}, out_pipe[2] = {-1, -1};
    int use_pty = 0;
    if (interactive) {
        struct winsize initial = { .ws_row = 24, .ws_col = 80 };
        use_pty = openpty(&master, &slave, NULL, NULL, &initial) == 0;
        int pty_error = use_pty ? 0 : errno;
        int ptmx = open("/dev/ptmx", O_RDWR | O_NOCTTY | O_CLOEXEC);
        int ptmx_error = ptmx < 0 ? errno : 0;
        if (ptmx >= 0) close(ptmx);
        dprintf(fd, "PTY_OPEN errno=%d direct_ptmx_errno=%d\n", pty_error, ptmx_error);
        if (!use_pty && (pipe(in_pipe) < 0 || pipe(out_pipe) < 0)) {
            snprintf(out, size, "terminal pipe errno=%d", errno);
            if (in_pipe[0] >= 0) { close(in_pipe[0]); close(in_pipe[1]); }
            close(fd);
            return;
        }
    }
    int streaming = shell && shell->environment != NULL;
    int shell_stdin[2] = {-1, -1}, shell_stdout[2] = {-1, -1}, shell_stderr[2] = {-1, -1};
    int shell_status[2];
    if (shell && ((streaming && shell_channel(shell_stdin, 1) < 0) ||
                  shell_channel(shell_stdout, streaming) < 0 || shell_channel(shell_stderr, streaming) < 0 ||
                  pipe2(shell_status, O_CLOEXEC | O_NONBLOCK) < 0)) {
        snprintf(out, size, "open shell channels errno=%d", errno);
        close_pair(shell_stdin);
        close_pair(shell_stdout);
        close_pair(shell_stderr);
        close(fd);
        return;
    }
    pid_t owner = getpid();
    pid_t child = fork();
    int fork_error = errno;
    if (child == 0) {
        if (client || secprobe || shellbench) {
            if (prctl(PR_SET_PDEATHSIG, SIGQUIT, 0, 0, 0) < 0) {
                dprintf(fd, "PRoot parent-death registration failed: %d\n", errno);
            }
            if (getppid() != owner) _exit(46);
        }
        if (shell) {
            if (prctl(PR_SET_PDEATHSIG, SIGKILL, 0, 0, 0) < 0 || getppid() != owner) _exit(46);
            const int status_channel = STDERR_FILENO + 1;
            if (setpgid(0, 0) < 0 || dup2(streaming ? shell_stdin[1] : fd, STDIN_FILENO) < 0 ||
                dup2(shell_stdout[1], STDOUT_FILENO) < 0 ||
                dup2(shell_stderr[1], STDERR_FILENO) < 0 ||
                dup2(shell_status[1], status_channel) < 0 || fcntl(status_channel, F_SETFD, 0) < 0) _exit(47);
            if (close_host_descriptors(status_channel) != 0) _exit(48);
            clearenv();
            setenv("HARMONY_PROOT_MANAGED_SHELL", "1", 1);
            setenv("HARMONY_GUEST_LIB_DIR", native, 1);
            setenv("HOME", "/workspace-native", 1);
            setenv("LANG", "C.UTF-8", 1);
            setenv("NO_COLOR", "1", 1);
            setenv("PAGER", "cat", 1);
            setenv("NODE_OPTIONS", "--jitless --require=/fetch-shim-boot.cjs", 1);
            setenv("GIT_EXEC_PATH", "/usr/libexec/git-core", 1);
            setenv("GIT_TEMPLATE_DIR", "/usr/share/git-core/templates", 1);
            if (streaming) {
                for (char *const *item = shell->environment; *item; ++item) {
                    if (putenv(*item) != 0) _exit(49);
                }
            }
        } else if (use_pty) {
            close(master);
            if (setsid() < 0 || ioctl(slave, TIOCSCTTY, 0) < 0) {
                dprintf(fd, "PTY_CTTY errno=%d\n", errno);
                _exit(45);
            }
            dup2(slave, STDIN_FILENO);
            dup2(slave, STDOUT_FILENO);
            dup2(slave, STDERR_FILENO);
            if (slave > STDERR_FILENO) close(slave);
        } else if (interactive) {
            setpgid(0, 0);
            close(in_pipe[1]);
            close(out_pipe[0]);
            dup2(in_pipe[0], STDIN_FILENO);
            dup2(out_pipe[1], STDOUT_FILENO);
            dup2(out_pipe[1], STDERR_FILENO);
            close(in_pipe[0]);
            close(out_pipe[1]);
        } else {
            setpgid(0, 0);
            dup2(fd, STDOUT_FILENO);
            dup2(fd, STDERR_FILENO);
        }

        if (entry) {
            setenv("PROOT_LOADER", loader, 1);
            if (loader_entry) setenv("HARMONY_PROOT_LOADER_ENTRY", address, 1);
            setenv("PROOT_TMP_DIR", directory, 1);
            setenv("PATH", "/bin:/usr/bin", 1);
            setenv("TERM", shell ? "dumb" : "xterm", 1);
            setenv("UV_USE_IO_URING", "0", 1);
            setenv("TMPDIR", "/tmp", 1);
            setenv("DSH_HOME", "/tmp/dsh-poc-home", 1);
            if (accelerated || strstr(stage, "default")) unsetenv("PROOT_NO_SECCOMP");
            else setenv("PROOT_NO_SECCOMP", "1", 1);
            _exit(entry(only_version ? (int)(sizeof(version) / sizeof(*version) - 1) : execution_argc, only_version ? version : execution_argv));
        }
        execve(executable, only_version ? version : execution_argv, env);
        int error = errno;
        dprintf(STDERR_FILENO, "execve proot errno=%d (%s)\n", error, strerror(error));
        _exit(44);
    }
    if (shell) {
        close(fd);
        if (streaming) close(shell_stdin[1]);
        close(shell_stdout[1]);
        close(shell_stderr[1]);
        close(shell_status[1]);
        if (child < 0) {
            if (streaming) close(shell_stdin[0]);
            close(shell_stdout[0]);
            close(shell_stderr[0]);
            close(shell_status[0]);
            snprintf(out, size, "fork errno=%d", fork_error);
        } else {
            setpgid(child, child);
            shell->pid = child;
            shell->stdin_fd = shell_stdin[0];
            shell->stdout_fd = shell_stdout[0];
            shell->stderr_fd = shell_stderr[0];
            shell->status_fd = shell_status[0];
        }
        return;
    }
    if (child < 0) {
        snprintf(out, size, "fork errno=%d (%s)", fork_error, strerror(fork_error));
        close(fd);
        return;
    }
    if (interactive) {
        if (use_pty) {
            close(slave);
            drive_terminal(master, master, 1, fd);
            close(master);
        } else {
            close(in_pipe[0]);
            close(out_pipe[1]);
            drive_terminal(in_pipe[1], out_pipe[0], 0, fd);
            close(in_pipe[1]);
            close(out_pipe[0]);
        }
    }
    int status = 0;
    int wait_error = ETIMEDOUT;
    long long deadline = monotonic_ms() + (secprobe ? 15000 : shellbench ? 12000 : dsh_test ? 105000 : 12000);
    char launch_file[1100];
    snprintf(launch_file, sizeof(launch_file), "%s/tmp/dsh-client-launch", root);
    long long fast_deadline = monotonic_ms() + 210000;
    int published = 0;
    while (client || monotonic_ms() < deadline) {
        pid_t got = waitpid(child, &status, WNOHANG);
        if (got == child) { wait_error = 0; break; }
        if (got < 0 && errno != EINTR) { wait_error = errno; break; }
        if (client && accelerated && !published && monotonic_ms() >= fast_deadline) {
            published = access(launch_file, F_OK) == 0;
            if (!published) {
                LOG("accelerated start exceeded time budget");
                break;
            }
        }
        usleep(20000);
    }
    if (wait_error) {
        kill(-child, SIGKILL);
        reap(child);
    }
    if (diagnose) {
        lseek(fd, 0, SEEK_SET);
        FILE *details = fdopen(dup(fd), "r");
        if (details) {
            char line[1600];
            for (int shown = 0; shown < 16 && fgets(line, sizeof(line), details); ) {
                if (!strstr(line, "libgcc") && !strstr(line, "libguest_gcc")) continue;
                line[strcspn(line, "\r\n")] = 0;
                LOG("node mapping %{public}s", line);
                ++shown;
            }
            fclose(details);
        }
    }
    int prefix = snprintf(out, size, "exit=%d signal=%d wait_errno=%d output: ",
        WIFEXITED(status) ? WEXITSTATUS(status) : -1,
        WIFSIGNALED(status) ? WTERMSIG(status) : 0, wait_error);
    if (prefix >= 0 && (size_t)prefix < size) {
        off_t length = lseek(fd, 0, SEEK_END);
        off_t capacity = (off_t)(size - prefix - 1);
        lseek(fd, length > capacity ? length - capacity : 0, SEEK_SET);
        ssize_t n = read(fd, out + prefix, size - prefix - 1);
        out[prefix + (n > 0 ? n : 0)] = 0;
    }
    close(fd);
    FILE *written = fopen(marker, "r");
    if (written) {
        char value[32] = {0};
        if (fgets(value, sizeof(value), written) && strcmp(value, "rootfs-write\n") == 0)
            LOG("Verified guest /marker from HAP storage");
        fclose(written);
    }
}

int harmony_spawn_shell(const char *directory, const char *cwd, const char *command,
                        int *stdout_fd, int *stderr_fd, int *status_fd, char *error, size_t error_size) {
    struct ShellLaunch shell = {.cwd = cwd, .command = command, .pid = -1};
    run_proot("proot-embedded-packaged-dsh-shellbench", directory, error, error_size, &shell);
    if (shell.pid > 0) {
        *stdout_fd = shell.stdout_fd;
        *stderr_fd = shell.stderr_fd;
        *status_fd = shell.status_fd;
    }
    return shell.pid;
}

int harmony_spawn_piped(const char *directory, const char *cwd, const char *command,
                        char *const *environment, int *stdin_fd, int *stdout_fd,
                        int *stderr_fd, int *status_fd, char *error, size_t error_size) {
    struct ShellLaunch shell = {.cwd = cwd, .command = command, .environment = environment, .pid = -1};
    run_proot("proot-embedded-packaged-dsh-shellbench", directory, error, error_size, &shell);
    if (shell.pid > 0) {
        *stdin_fd = shell.stdin_fd;
        *stdout_fd = shell.stdout_fd;
        *stderr_fd = shell.stderr_fd;
        *status_fd = shell.status_fd;
    }
    return shell.pid;
}

static void run_probe(const char *stage, const char *directory, char *out, size_t size) {
    char label[160] = "unreadable";
    FILE *file = fopen("/proc/self/attr/current", "r");
    if (file) {
        if (fgets(label, sizeof(label), file)) label[strcspn(label, "\r\n")] = 0;
        fclose(file);
    }
    LOG("begin stage=%{public}s uid=%{public}u pid=%{public}d domain=%{public}s",
        stage, getuid(), getpid(), label);
    if (strncmp(stage, "proot-", 6) == 0) {
        run_proot(stage, directory, out, size, NULL);
        return;
    }
    int is_trace = strcmp(stage, "trace") == 0;
    int is_root = strcmp(stage, "chroot") == 0;
    int is_shell = strcmp(stage, "shell") == 0;
    char root[1024];
    snprintf(root, sizeof(root), "%s/probe-root", directory);
    if (is_root && mkdir(root, 0700) < 0 && errno != EEXIST) {
        snprintf(out, size, "mkdir errno=%d", errno);
        return;
    }
    int fds[2];
    if (pipe(fds) < 0) {
        snprintf(out, size, "pipe errno=%d", errno);
        return;
    }
    pid_t child = fork();
    int fork_error = errno;
    if (child == 0) {
        close(fds[0]);
        if (is_trace) {
            if (ptrace(PTRACE_TRACEME, 0, 0, 0) < 0) {
                int error = errno;
                write(fds[1], &error, sizeof(error));
                _exit(41);
            }
            kill(getpid(), SIGSTOP);
            syscall(SYS_getpid);
            _exit(0);
        }
        if (is_root) {
            int error = chroot(root) < 0 ? errno : 0;
            write(fds[1], &error, sizeof(error));
            _exit(error ? 42 : 0);
        }
        if (is_shell) {
            execl("/system/bin/sh", "sh", "-c", "exit 37", (char *)NULL);
            int error = errno;
            write(fds[1], &error, sizeof(error));
            _exit(43);
        }
        _exit(37);
    }
    close(fds[1]);
    if (child < 0) {
        close(fds[0]);
        snprintf(out, size, "fork errno=%d (%s)", fork_error, strerror(fork_error));
        return;
    }
    int status = 0;
    int wait_error = wait_bounded(child, &status);
    if (wait_error) {
        reap(child);
        close(fds[0]);
        snprintf(out, size, "waitpid errno=%d (%s)", wait_error, strerror(wait_error));
        return;
    }
    if (is_trace && WIFSTOPPED(status)) {
        unsigned long registers[34] = {0};
        struct iovec regset = { registers, sizeof(registers) };
        int regs_error = ptrace(PTRACE_GETREGSET, child, NT_PRSTATUS, &regset) < 0 ? errno : 0;
        int opts_error = ptrace(PTRACE_SETOPTIONS, child, 0, PTRACE_O_TRACESYSGOOD) < 0 ? errno : 0;
        int step_error = ptrace(PTRACE_SYSCALL, child, 0, 0) < 0 ? errno : 0;
        int step_status = 0;
        int step_wait = step_error ? 0 : wait_bounded(child, &step_status);
        int step_signal = !step_wait && WIFSTOPPED(step_status) ? WSTOPSIG(step_status) : 0;
        snprintf(out, size, "TRACEME stop=%d GETREGSET errno=%d SETOPTIONS errno=%d SYSCALL errno=%d wait=%d stop=%d",
            WSTOPSIG(status), regs_error, opts_error, step_error, step_wait, step_signal);
        if (step_error || step_wait || WIFSTOPPED(step_status)) reap(child);
    } else if (WIFEXITED(status)) {
        int child_error = 0;
        ssize_t bytes = read(fds[0], &child_error, sizeof(child_error));
        snprintf(out, size, "child exit=%d operation_errno=%d (%s)",
            WEXITSTATUS(status), bytes == sizeof(child_error) ? child_error : 0,
            bytes == sizeof(child_error) ? strerror(child_error) : "no errno");
    } else {
        snprintf(out, size, "child signal=%d wait_status=%d", WIFSIGNALED(status) ? WTERMSIG(status) : 0, status);
    }
    close(fds[0]);
}

struct ProbeWork {
    napi_async_work work;
    napi_deferred deferred;
    char stage[64];
    char directory[900];
    char out[3900];
};

static void Execute(napi_env env, void *data) {
    (void)env;
    struct ProbeWork *probe = data;
    run_probe(probe->stage, probe->directory, probe->out, sizeof(probe->out));
}

static void Complete(napi_env env, napi_status status, void *data) {
    struct ProbeWork *probe = data;
    napi_value result;
    const char *message = status == napi_ok ? probe->out : "probe cancelled";
    if (!strstr(probe->stage, "client")) LOG("result stage=%{public}s %{public}s", probe->stage, message);
    napi_create_string_utf8(env, message, NAPI_AUTO_LENGTH, &result);
    napi_resolve_deferred(env, probe->deferred, result);
    napi_delete_async_work(env, probe->work);
    free(probe);
}

static napi_value Run(napi_env env, napi_callback_info info) {
    size_t count = 2;
    napi_value args[2], promise, name;
    struct ProbeWork *probe = calloc(1, sizeof(*probe));
    if (!probe) { napi_throw_error(env, NULL, "probe allocation failed"); return NULL; }
    napi_get_cb_info(env, info, &count, args, NULL, NULL);
    if (count != 2 ||
        napi_get_value_string_utf8(env, args[0], probe->stage, sizeof(probe->stage), NULL) != napi_ok ||
        napi_get_value_string_utf8(env, args[1], probe->directory, sizeof(probe->directory), NULL) != napi_ok) {
        free(probe);
        napi_throw_type_error(env, NULL, "invalid probe arguments");
        return NULL;
    }
    napi_create_promise(env, &probe->deferred, &promise);
    napi_create_string_utf8(env, "PRoot validation", NAPI_AUTO_LENGTH, &name);
    napi_create_async_work(env, NULL, name, Execute, Complete, probe, &probe->work);
    napi_queue_async_work(env, probe->work);
    return promise;
}

extern napi_value StartNative(napi_env env, napi_callback_info info);
extern napi_value NativeStatus(napi_env env, napi_callback_info info);
napi_value UsesHostProcess(napi_env env, napi_callback_info info);
napi_value StopNative(napi_env env, napi_callback_info info);
static napi_value Init(napi_env env, napi_value exports) {
    napi_property_descriptor methods[] = {
        {"run", NULL, Run, NULL, NULL, NULL, napi_default, NULL},
        {"startNative", NULL, StartNative, NULL, NULL, NULL, napi_default, NULL},
        {"nativeStatus", NULL, NativeStatus, NULL, NULL, NULL, napi_default, NULL},
        {"usesHostProcess", NULL, UsesHostProcess, NULL, NULL, NULL, napi_default, NULL},
        {"stopNative", NULL, StopNative, NULL, NULL, NULL, napi_default, NULL},
    };
    napi_define_properties(env, exports, sizeof(methods) / sizeof(methods[0]), methods);
    return exports;
}
static napi_module module = {1, 0, NULL, Init, "poc", NULL, {0}};
__attribute__((constructor)) static void Register(void) { napi_module_register(&module); }

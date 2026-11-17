#define _GNU_SOURCE
#include "ptc-supervisor.h"
#include "ptc-file-filter.h"
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <linux/openat2.h>
#include <linux/seccomp.h>
#include <poll.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/prctl.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <sys/uio.h>
#include <sys/wait.h>
#include <unistd.h>

#ifndef SECCOMP_ADDFD_FLAG_SEND
#define SECCOMP_ADDFD_FLAG_SEND (1UL << 1)
#endif

#define WORKSPACE_RESOLVE (RESOLVE_BENEATH | RESOLVE_NO_SYMLINKS | RESOLVE_NO_XDEV)

static volatile sig_atomic_t stop_requested;
static void request_stop(int signal) { (void)signal; stop_requested = 1; }

static int follow(pid_t parent)
{
    return prctl(PR_SET_PDEATHSIG, SIGKILL, 0, 0, 0) == 0 && getppid() == parent;
}

static void start_node(const char *entry, int control, int setup, int root, pid_t parent, const struct PtcLaunch *launch)
{
    control = fcntl(control, F_DUPFD_CLOEXEC, 8);
    setup = fcntl(setup, F_DUPFD_CLOEXEC, 8);
    if (!follow(parent) || fchdir(root) < 0 ||
        dup2(control, 7) < 0 || dup2(setup, 0) < 0 || dup2(setup, 1) < 0 || dup2(setup, 2) < 0 ||
        syscall(SYS_close_range, 3u, 6u, 0u) < 0 || syscall(SYS_close_range, 8u, ~0u, 0u) < 0 ||
        clearenv() != 0 || setenv("DSH_SUBPROCESS_CONTROL", "pipe", 1) < 0 ||
        ptc_deny_io_uring() != 0) _exit(125);
    void *library = dlopen("libnode.so", RTLD_NOW | RTLD_LOCAL);
    typedef int (*NodeStart)(int, char **);
    NodeStart start = library ? (NodeStart)dlsym(library, "_ZN4node5StartEiPPc") : NULL;
    if (!start) _exit(125);
    char limit[32], memory[64];
    snprintf(limit, sizeof(limit), "%d", launch->message_bytes);
    snprintf(memory, sizeof(memory), "--max-old-space-size=%d", launch->heap_mb);
    char *argv[] = {"node", "--jitless", "--no-warnings", "--experimental-vm-modules", memory,
                    (char *)entry, limit, launch->root, NULL};
    _exit(start(8, argv));
}

static char *workspace_path(pid_t worker, uint64_t address, const struct PtcLaunch *launch, char path[4096])
{
    struct iovec local = {.iov_base = path, .iov_len = 4096};
    struct iovec remote = {.iov_base = (void *)(uintptr_t)address, .iov_len = 4096};
    ssize_t size = syscall(SYS_process_vm_readv, worker, &local, 1, &remote, 1, 0);
    if (size < 0) return NULL;
    if (!size || !path[0] || !memchr(path, 0, (size_t)size)) {
        errno = EFAULT;
        return NULL;
    }
    if (path[0] != '/') return path;
    size_t length = strlen(launch->root);
    if (strncmp(path, launch->root, length) || (path[length] && path[length] != '/')) {
        errno = EACCES;
        return NULL;
    }
    char *relative = path + length;
    while (*relative == '/') ++relative;
    if (!*relative) {
        strcpy(path, ".");
        return path;
    }
    return relative;
}

static int grant_path(int root, pid_t worker, const struct seccomp_data *call, const struct PtcLaunch *launch)
{
    int flags = (int)call->args[2] & ~O_LARGEFILE;
    const int directory = O_DIRECTORY | O_CLOEXEC;
    const int create = O_WRONLY | O_CREAT | O_CLOEXEC;
    const int exclusive = (flags & O_EXCL) != 0;
    const int truncate = (flags & O_TRUNC) != 0 && !exclusive;
    const int writes = flags == (create | O_TRUNC) || flags == (create | O_EXCL | O_TRUNC) ||
        flags == (create | O_EXCL) || flags == (create | O_APPEND) || flags == (create | O_APPEND | O_EXCL);
    if ((int)call->args[0] != AT_FDCWD ||
        (flags != O_CLOEXEC && flags != directory && flags != (directory | O_NONBLOCK) &&
         (!writes || !launch->writable))) {
        errno = EACCES;
        return -1;
    }
    char path[4096];
    const char *relative = workspace_path(worker, call->args[1], launch, path);
    if (!relative) return -1;
    struct open_how how = {
        // Opening without O_TRUNC lets us validate the exact inode first.
        .flags = (flags & ~O_TRUNC) | O_NONBLOCK, .mode = writes ? 0600 : 0,
        .resolve = WORKSPACE_RESOLVE,
    };
    int file = (int)syscall(SYS_openat2, root, relative, &how, sizeof(how));
    if (file >= 0) {
        struct stat stat;
        if (fstat(file, &stat) < 0 ||
            (writes ? !S_ISREG(stat.st_mode) || stat.st_nlink != 1
                    : !S_ISDIR(stat.st_mode) && !S_ISREG(stat.st_mode))) {
            close(file);
            errno = EACCES;
            return -1;
        }
        if (truncate && ftruncate(file, 0) < 0) {
            int error = errno;
            close(file);
            errno = error;
            return -1;
        }
    }
    return file;
}

static int open_parent(int root, char *path, const char **leaf)
{
    char *slash = strrchr(path, '/');
    *leaf = slash ? slash + 1 : path;
    if (!**leaf || !strcmp(*leaf, ".") || !strcmp(*leaf, "..")) {
        errno = EACCES;
        return -1;
    }
    if (slash) *slash = '\0';
    const struct open_how how = {
        .flags = O_PATH | O_DIRECTORY | O_CLOEXEC, .resolve = WORKSPACE_RESOLVE,
    };
    return (int)syscall(SYS_openat2, root, slash ? path : ".", &how, sizeof(how));
}

static int mutate_path(int root, pid_t worker, const struct seccomp_data *call, const struct PtcLaunch *launch)
{
    const int rename = call->nr == SYS_renameat || call->nr == SYS_renameat2;
    if (!launch->writable || (int)call->args[0] != AT_FDCWD ||
        (rename && (int)call->args[2] != AT_FDCWD) ||
        (call->nr == SYS_renameat2 && call->args[4] != 0) ||
        (call->nr == SYS_unlinkat && call->args[2] != 0 && call->args[2] != AT_REMOVEDIR)) return EACCES;
    char source[4096], destination[4096];
    char *path = workspace_path(worker, call->args[1], launch, source);
    if (!path) return errno;
    char *target = rename ? workspace_path(worker, call->args[3], launch, destination) : NULL;
    if (rename && !target) return errno;
    const char *name, *target_name;
    int parent = open_parent(root, path, &name);
    if (parent < 0) return errno;
    int error;
    switch (call->nr) {
    case SYS_mkdirat:
        error = mkdirat(parent, name, (mode_t)call->args[2] & 0777) == 0 ? 0 : errno;
        break;
    case SYS_unlinkat:
        error = unlinkat(parent, name, (int)call->args[2]) == 0 ? 0 : errno;
        break;
    case SYS_renameat:
    case SYS_renameat2: {
        int target_parent = open_parent(root, target, &target_name);
        if (target_parent < 0) error = errno;
        else {
            error = renameat(parent, name, target_parent, target_name) == 0 ? 0 : errno;
            close(target_parent);
        }
        break;
    }
    default:
        error = EACCES;
    }
    close(parent);
    return error;
}

static int mediate(int listener, int root, pid_t worker, const struct PtcLaunch *launch)
{
    struct seccomp_notif request = {0};
    if (ioctl(listener, SECCOMP_IOCTL_NOTIF_RECV, &request) < 0 ||
        ioctl(listener, SECCOMP_IOCTL_NOTIF_ID_VALID, &request.id) < 0) return errno;
    struct seccomp_notif_resp response = {.id = request.id};
    if (!request.pid || syscall(SYS_tgkill, worker, request.pid, 0) < 0) {
        response.error = -EACCES;
        return ioctl(listener, SECCOMP_IOCTL_NOTIF_SEND, &response) < 0 ? errno : 0;
    }
    if (request.data.nr != SYS_openat) {
        response.error = -mutate_path(root, worker, &request.data, launch);
        return ioctl(listener, SECCOMP_IOCTL_NOTIF_SEND, &response) < 0 ? errno : 0;
    }
    int file = grant_path(root, worker, &request.data, launch);
    if (file < 0) {
        response.error = -errno;
        return ioctl(listener, SECCOMP_IOCTL_NOTIF_SEND, &response) < 0 ? errno : 0;
    }
    struct seccomp_notif_addfd grant = {
        .id = request.id, .flags = SECCOMP_ADDFD_FLAG_SEND, .srcfd = file, .newfd_flags = O_CLOEXEC,
    };
    int result = ioctl(listener, SECCOMP_IOCTL_NOTIF_ADDFD, &grant);
    if (result < 0 && errno == EINVAL) {
        grant.flags = 0;
        result = ioctl(listener, SECCOMP_IOCTL_NOTIF_ADDFD, &grant);
        if (result >= 0) {
            response.val = result;
            result = ioctl(listener, SECCOMP_IOCTL_NOTIF_SEND, &response);
        }
    }
    int error = result < 0 ? errno : 0;
    close(file);
    return error;
}

void harmony_ptc_supervise(const char *entry, int channel, pid_t parent, const struct PtcLaunch *launch)
{
    if (!follow(parent)) _exit(125);
    const struct sigaction handler = {.sa_handler = request_stop};
    if (sigaction(SIGTERM, &handler, NULL) < 0) _exit(125);
    struct open_how how = {.flags = O_PATH | O_DIRECTORY | O_CLOEXEC, .resolve = RESOLVE_NO_SYMLINKS};
    int root = (int)syscall(SYS_openat2, AT_FDCWD, launch->root, &how, sizeof(how));
    struct seccomp_notif_sizes sizes;
    int setup[2];
    if (root < 0 || syscall(SYS_seccomp, SECCOMP_GET_NOTIF_SIZES, 0, &sizes) < 0 ||
        sizes.seccomp_notif != sizeof(struct seccomp_notif) ||
        sizes.seccomp_notif_resp != sizeof(struct seccomp_notif_resp) ||
        socketpair(AF_UNIX, SOCK_SEQPACKET | SOCK_CLOEXEC, 0, setup) < 0) _exit(125);
    if (stop_requested) _exit(128 + SIGTERM);
    pid_t supervisor = getpid();
    pid_t worker = fork();
    if (worker == 0) start_node(entry, channel, setup[1], root, supervisor, launch);
    if (worker < 0) _exit(125);
    close(channel);
    close(setup[1]);
    struct pollfd descriptor = {.fd = setup[0], .events = POLLIN};
    int listener = !stop_requested && poll(&descriptor, 1, 8000) > 0
        ? ptc_transfer_listener(setup[0], -1, 1) : -1;
    close(setup[0]);
    int status;
    while (listener >= 0 && !stop_requested) {
        pid_t observed = waitpid(worker, &status, WNOHANG);
        if (observed == worker) _exit(WIFEXITED(status) ? WEXITSTATUS(status) : 128 + WTERMSIG(status));
        if (observed < 0 && errno != EINTR) break;
        descriptor.fd = listener;
        int ready = poll(&descriptor, 1, 100);
        if (ready < 0 && errno != EINTR) break;
        if (ready > 0 && descriptor.revents & POLLIN) {
            int error = mediate(listener, root, worker, launch);
            if (error && error != ENOENT && error != EINTR) break;
        }
    }
    kill(worker, SIGKILL);
    while (waitpid(worker, NULL, 0) < 0 && errno == EINTR) {}
    _exit(stop_requested ? 128 + SIGTERM : 125);
}

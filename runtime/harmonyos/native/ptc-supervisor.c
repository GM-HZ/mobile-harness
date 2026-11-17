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
                    (char *)entry, limit, (char *)launch->cwd, NULL};
    _exit(start(8, argv));
}

struct PtcRoots {
    int fd[MH_PTC_EXTRA_ROOTS + 1];
    const char *path[MH_PTC_EXTRA_ROOTS + 1];
    int count;
};

static int root_index(const struct PtcRoots *roots, const char *path)
{
    int selected = -1;
    size_t longest = 0;
    for (int i = 0; i < roots->count; ++i) {
        size_t length = strlen(roots->path[i]);
        if (length >= longest && !strncmp(path, roots->path[i], length) &&
            (length == 1 || !path[length] || path[length] == '/')) {
            selected = i;
            longest = length;
        }
    }
    return selected;
}

static int normalize_path(const char *source, char path[4096])
{
    size_t used = 1;
    path[0] = '/';
    path[1] = 0;
    const char *part = source;
    while (*part) {
        while (*part == '/') ++part;
        const char *end = part;
        while (*end && *end != '/') ++end;
        size_t length = (size_t)(end - part);
        if (!length) break;
        if (length == 2 && !memcmp(part, "..", 2)) {
            while (used > 1 && path[used - 1] != '/') --used;
            if (used > 1) --used;
        } else if (length != 1 || part[0] != '.') {
            size_t separator = used > 1 ? 1 : 0;
            if (used + separator + length >= 4096) return ENAMETOOLONG;
            if (used > 1) path[used++] = '/';
            memcpy(path + used, part, length);
            used += length;
        }
        path[used] = 0;
        part = end;
    }
    if (used > 1 && source[strlen(source) - 1] == '/') {
        if (used + 1 >= 4096) return ENAMETOOLONG;
        path[used++] = '/';
    }
    path[used] = 0;
    return 0;
}

static int validate_parent(char *path)
{
    char *leaf = strrchr(path, '/');
    if (!leaf) return EACCES;
    *leaf = 0;
    const struct open_how how = {
        .flags = O_PATH | O_DIRECTORY | O_CLOEXEC, .resolve = RESOLVE_NO_SYMLINKS,
    };
    // The original parent must resolve, including components removed by ".." or ".".
    int directory = (int)syscall(SYS_openat2, AT_FDCWD, *path ? path : "/", &how, sizeof(how));
    if (directory < 0) return errno;
    close(directory);
    return 0;
}

static char *workspace_path(const struct PtcRoots *roots, pid_t worker, uint64_t address,
                            const struct PtcLaunch *launch, char path[4096], int *root)
{
    struct iovec local = {.iov_base = path, .iov_len = 4096};
    struct iovec remote = {.iov_base = (void *)(uintptr_t)address, .iov_len = 4096};
    ssize_t size = syscall(SYS_process_vm_readv, worker, &local, 1, &remote, 1, 0);
    if (size < 0) return NULL;
    if (!size || !path[0] || !memchr(path, 0, (size_t)size)) {
        errno = EFAULT;
        return NULL;
    }
    if (path[0] != '/') {
        size_t prefix = strlen(launch->cwd), length = strlen(path);
        if (prefix + length + 2 > 4096) {
            errno = ENAMETOOLONG;
            return NULL;
        }
        memmove(path + prefix + 1, path, length + 1);
        memcpy(path, launch->cwd, prefix);
        path[prefix] = '/';
    }
    char original[4096];
    strcpy(original, path);
    int error = normalize_path(original, path);
    if (error) {
        errno = error;
        return NULL;
    }
    int selected = root_index(roots, path);
    if (selected < 0) {
        errno = EACCES;
        return NULL;
    }
    error = validate_parent(original);
    if (error) {
        errno = error;
        return NULL;
    }
    *root = roots->fd[selected];
    char *relative = path + strlen(roots->path[selected]);
    while (*relative == '/') ++relative;
    return *relative ? relative : ".";
}

static int grant_path(const struct PtcRoots *roots, pid_t worker, const struct seccomp_data *call, const struct PtcLaunch *launch)
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
    int root;
    const char *relative = workspace_path(roots, worker, call->args[1], launch, path, &root);
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

static int mutate_path(const struct PtcRoots *roots, pid_t worker, const struct seccomp_data *call, const struct PtcLaunch *launch)
{
    const int rename = call->nr == SYS_renameat || call->nr == SYS_renameat2;
    if (!launch->writable || (int)call->args[0] != AT_FDCWD ||
        (rename && (int)call->args[2] != AT_FDCWD) ||
        (call->nr == SYS_renameat2 && call->args[4] != 0) ||
        (call->nr == SYS_unlinkat && call->args[2] != 0 && call->args[2] != AT_REMOVEDIR)) return EACCES;
    char source[4096], destination[4096];
    int root, target_root;
    char *path = workspace_path(roots, worker, call->args[1], launch, source, &root);
    if (!path) return errno;
    char *target = rename ? workspace_path(roots, worker, call->args[3], launch, destination, &target_root) : NULL;
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
        int target_parent = open_parent(target_root, target, &target_name);
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

static int stat_path(int listener, const struct PtcRoots *roots, pid_t worker, const struct seccomp_notif *request,
                     const struct PtcLaunch *launch)
{
    const struct seccomp_data *call = &request->data;
    if ((int)call->args[0] != AT_FDCWD ||
        (call->args[3] != 0 && call->args[3] != AT_SYMLINK_NOFOLLOW)) return EACCES;
    char path[4096];
    int root;
    const char *relative = workspace_path(roots, worker, call->args[1], launch, path, &root);
    if (!relative) return errno;
    const int nofollow = call->args[3] == AT_SYMLINK_NOFOLLOW;
    const struct open_how how = {
        .flags = O_PATH | O_CLOEXEC | (nofollow ? O_NOFOLLOW : 0),
        .resolve = WORKSPACE_RESOLVE,
    };
    int file = (int)syscall(SYS_openat2, root, relative, &how, sizeof(how));
    if (file < 0) return errno;
    // Use the kernel ABI of the worker's syscall, and inspect only the pinned inode.
    struct stat metadata = {0};
    int error = syscall(SYS_newfstatat, file, "", &metadata, AT_EMPTY_PATH) < 0 ? errno : 0;
    close(file);
    if (error) return error;
    if (!S_ISREG(metadata.st_mode) && !S_ISDIR(metadata.st_mode) &&
        !(nofollow && S_ISLNK(metadata.st_mode))) return EACCES;
    if (ioctl(listener, SECCOMP_IOCTL_NOTIF_ID_VALID, &request->id) < 0) return errno;
    struct iovec local = {.iov_base = &metadata, .iov_len = sizeof(metadata)};
    struct iovec remote = {.iov_base = (void *)(uintptr_t)call->args[2], .iov_len = sizeof(metadata)};
    ssize_t written = syscall(SYS_process_vm_writev, worker, &local, 1, &remote, 1, 0);
    return written < 0 ? errno : (size_t)written == sizeof(metadata) ? 0 : EFAULT;
}

static int directory_path(const struct PtcRoots *roots, pid_t worker, const struct seccomp_data *call,
                          const struct PtcLaunch *launch, char absolute[1024])
{
    char path[4096];
    int root;
    const char *relative = workspace_path(roots, worker, call->args[0], launch, path, &root);
    if (!relative) return -1;
    // Directory transitions have a single canonical spelling shared by Node and the broker.
    if (path[0] != '/' || strlen(path) >= 1024 || strstr(path, "/../") || strstr(path, "/./") ||
        strstr(path, "//") || (strlen(path) >= 3 && !strcmp(path + strlen(path) - 3, "/..")) ||
        (strlen(path) >= 2 && !strcmp(path + strlen(path) - 2, "/."))) {
        errno = EACCES;
        return -1;
    }
    const struct open_how how = {
        .flags = O_RDONLY | O_DIRECTORY | O_CLOEXEC, .resolve = WORKSPACE_RESOLVE,
    };
    int directory = (int)syscall(SYS_openat2, root, relative, &how, sizeof(how));
    if (directory >= 0) strcpy(absolute, path);
    return directory;
}

static int mediate(int listener, const struct PtcRoots *roots, pid_t worker, struct PtcLaunch *launch)
{
    struct seccomp_notif request = {0};
    if (ioctl(listener, SECCOMP_IOCTL_NOTIF_RECV, &request) < 0 ||
        ioctl(listener, SECCOMP_IOCTL_NOTIF_ID_VALID, &request.id) < 0) return errno;
    struct seccomp_notif_resp response = {.id = request.id};
    if (!request.pid || syscall(SYS_tgkill, worker, request.pid, 0) < 0) {
        response.error = -EACCES;
        return ioctl(listener, SECCOMP_IOCTL_NOTIF_SEND, &response) < 0 ? errno : 0;
    }
    const int change_directory = request.data.nr == SYS_chdir;
    if (request.data.nr != SYS_openat && !change_directory) {
        response.error = request.data.nr == SYS_newfstatat ? -stat_path(listener, roots, worker, &request, launch)
                                                         : -mutate_path(roots, worker, &request.data, launch);
        return ioctl(listener, SECCOMP_IOCTL_NOTIF_SEND, &response) < 0 ? errno : 0;
    }
    char next_directory[1024];
    int file = change_directory ? directory_path(roots, worker, &request.data, launch, next_directory)
                                : grant_path(roots, worker, &request.data, launch);
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
    if (!error && change_directory) strcpy(launch->cwd, next_directory);
    close(file);
    return error;
}

void harmony_ptc_supervise(const char *entry, int channel, pid_t parent, const struct PtcLaunch *launch)
{
    if (!follow(parent)) _exit(125);
    struct PtcLaunch current = *launch;
    const struct sigaction handler = {.sa_handler = request_stop};
    if (sigaction(SIGTERM, &handler, NULL) < 0) _exit(125);
    struct open_how how = {.flags = O_PATH | O_DIRECTORY | O_CLOEXEC, .resolve = RESOLVE_NO_SYMLINKS};
    if (launch->extra_count < 0 || launch->extra_count > MH_PTC_EXTRA_ROOTS ||
        (!launch->writable && launch->extra_count)) _exit(125);
    struct PtcRoots roots = {.count = launch->extra_count + 1};
    roots.path[0] = launch->root;
    for (int i = 0; i < launch->extra_count; ++i) roots.path[i + 1] = launch->extra_roots[i];
    for (int i = 0; i < roots.count; ++i) {
        roots.fd[i] = (int)syscall(SYS_openat2, AT_FDCWD, roots.path[i], &how, sizeof(how));
        if (roots.fd[i] < 0) _exit(125);
    }
    if (root_index(&roots, launch->cwd) < 0) _exit(125);
    struct seccomp_notif_sizes sizes;
    int setup[2];
    if (syscall(SYS_seccomp, SECCOMP_GET_NOTIF_SIZES, 0, &sizes) < 0 ||
        sizes.seccomp_notif != sizeof(struct seccomp_notif) ||
        sizes.seccomp_notif_resp != sizeof(struct seccomp_notif_resp) ||
        socketpair(AF_UNIX, SOCK_SEQPACKET | SOCK_CLOEXEC, 0, setup) < 0) _exit(125);
    if (stop_requested) _exit(128 + SIGTERM);
    pid_t supervisor = getpid();
    pid_t worker = fork();
    if (worker == 0) start_node(entry, channel, setup[1], roots.fd[0], supervisor, launch);
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
            int error = mediate(listener, &roots, worker, &current);
            if (error && error != ENOENT && error != EINTR) break;
        }
    }
    kill(worker, SIGKILL);
    while (waitpid(worker, NULL, 0) < 0 && errno == EINTR) {}
    _exit(stop_requested ? 128 + SIGTERM : 125);
}

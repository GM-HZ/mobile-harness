#define _GNU_SOURCE
#include "ptc-file-filter.h"
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <linux/openat2.h>
#include <linux/seccomp.h>
#include <napi/native_api.h>
#include <poll.h>
#include <pthread.h>
#include <signal.h>
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

enum { PATH_LIMIT = 256, MAX_NOTIFICATIONS = 16 };
static const char marker[] = "ptc-fixture";

struct BrokerReport {
    int protocol_error;
    int path_copy_error;
    int injected;
    int refused;
    int reaped;
    const char *stage;
    int atomic_addfd_errno;
    int legacy_injected;
    int thread_notifications;
    int requested_flags[ATTEMPTS];
    struct WorkerReport worker;
};

static int wait_readable(int fd)
{
    struct pollfd item = {.fd = fd, .events = POLLIN};
    int result;
    do { result = poll(&item, 1, 2000); } while (result < 0 && errno == EINTR);
    return result > 0 && (item.revents & POLLIN) ? 0 : result == 0 ? ETIMEDOUT : EIO;
}

struct ThreadProbe {
    const char *outside;
    int ready[2];
    int result[2];
};

static int try_openat2(const char *path)
{
    const struct open_how how = {.flags = O_RDONLY};
    int fd = (int)syscall(SYS_openat2, AT_FDCWD, path, &how, sizeof(how));
    if (fd < 0) return errno;
    close(fd);
    return 0;
}

static void *existing_thread(void *data)
{
    const struct ThreadProbe *probe = data;
    char start;
    if (read(probe->ready[0], &start, 1) == 1) {
        int error = try_openat2(probe->outside);
        if (write(probe->result[1], &error, sizeof(error)) == sizeof(error)) {
            // The supervisor reaps the process. Keep the thread on the permitted read
            // path without running libc's thread teardown inside the test filter.
            (void)read(probe->ready[0], &start, 1);
        }
    }
    return NULL;
}

static void worker(int socket_fd, const char *outside, pid_t parent, int with_thread)
{
    if (prctl(PR_SET_PDEATHSIG, SIGKILL, 0, 0, 0) < 0 || getppid() != parent ||
        dup2(socket_fd, CONTROL) < 0 || syscall(SYS_close_range, 1u, ~0u, 0u) < 0 ||
        prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) < 0) _exit(90);
    struct ThreadProbe thread_test = {.outside = outside};
    if (with_thread) {
        pthread_t thread;
        if (pipe2(thread_test.ready, O_CLOEXEC) < 0 || pipe2(thread_test.result, O_CLOEXEC) < 0 ||
            pthread_create(&thread, NULL, existing_thread, &thread_test) != 0) _exit(94);
    }
    if (ptc_install_file_filter(with_thread, 0)) _exit(92);

    struct WorkerReport report = {.existing_thread_openat2_errno = -1};
    if (with_thread) {
        if (write(thread_test.ready[1], "T", 1) != 1 ||
            read(thread_test.result[0], &report.existing_thread_openat2_errno, sizeof(int)) != sizeof(int)) _exit(95);
    }
    const char *paths[ATTEMPTS] = {"read.txt", "created.txt", "../outside.txt", outside};
    for (int i = 0; i < ATTEMPTS; ++i) {
        int flags = (i == 1 || i == 3) ? O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC : O_RDONLY | O_CLOEXEC;
        int fd = (int)syscall(SYS_openat, AT_FDCWD, paths[i], flags, 0600);
        if (fd < 0) {
            report.error[i] = errno;
            continue;
        }
        if (i == 0) {
            char data[sizeof(marker)] = {0};
            report.read_correct = read(fd, data, sizeof(data)) == sizeof(data) && !memcmp(data, marker, sizeof(data));
        } else if (i == 1) report.write_correct = write(fd, marker, sizeof(marker)) == sizeof(marker);
        close(fd);
    }
    report.direct_openat2_errno = try_openat2(outside);
    _exit(write(CONTROL, &report, sizeof(report)) == sizeof(report) ? 0 : 93);
}

static int authorize(int root, pid_t child, const struct seccomp_notif *request, int writable, int *read_error)
{
    // The libc wrapper automatically adds O_LARGEFILE. It carries no access mode.
    int flags = (int)request->data.args[2] & ~O_LARGEFILE;
    const int directory_flags = O_RDONLY | O_CLOEXEC | O_DIRECTORY;
    const int directory = flags == directory_flags || flags == (directory_flags | O_NONBLOCK);
    if (!request->pid || syscall(SYS_tgkill, child, request->pid, 0) < 0 || request->data.nr != SYS_openat ||
        (int)request->data.args[0] != AT_FDCWD ||
        (flags != (O_RDONLY | O_CLOEXEC) && !directory &&
         (!writable || flags != (O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC)))) {
        errno = EACCES;
        return -1;
    }
    char path[PATH_LIMIT];
    struct iovec local = {.iov_base = path, .iov_len = sizeof(path)};
    struct iovec remote = {.iov_base = (void *)(uintptr_t)request->data.args[1], .iov_len = sizeof(path)};
    ssize_t copied = syscall(SYS_process_vm_readv, child, &local, 1, &remote, 1, 0);
    if (copied <= 0) {
        *read_error = errno;
        return -1;
    }
    if (!memchr(path, 0, (size_t)copied) || !path[0] || path[0] == '/') {
        errno = EACCES;
        return -1;
    }
    const struct open_how how = {
        .flags = flags, .mode = flags & O_CREAT ? 0600 : 0,
        .resolve = RESOLVE_BENEATH | RESOLVE_NO_SYMLINKS | RESOLVE_NO_MAGICLINKS | RESOLVE_NO_XDEV,
    };
    return (int)syscall(SYS_openat2, root, path, &how, sizeof(how));
}

static int serve_open(int listener, int root, pid_t child, int writable, struct BrokerReport *report)
{
    report->stage = "notification";
    int error = wait_readable(listener);
    if (error) return error;
    struct seccomp_notif request = {0};
    if (ioctl(listener, SECCOMP_IOCTL_NOTIF_RECV, &request) < 0) return errno;
    report->stage = "validate";
    if (ioctl(listener, SECCOMP_IOCTL_NOTIF_ID_VALID, &request.id) < 0) return errno;
    if (request.pid != (unsigned)child) ++report->thread_notifications;
    int index = report->injected + report->refused;
    if (index < ATTEMPTS) report->requested_flags[index] = (int)request.data.args[2];
    int incoming = authorize(root, child, &request, writable, &report->path_copy_error);
    if (incoming < 0) {
        struct seccomp_notif_resp denial = {.id = request.id, .error = -errno};
        report->stage = "deny";
        if (ioctl(listener, SECCOMP_IOCTL_NOTIF_SEND, &denial) < 0) return errno;
        ++report->refused;
        return 0;
    }
    struct seccomp_notif_addfd grant = {
        .id = request.id, .flags = SECCOMP_ADDFD_FLAG_SEND,
        .srcfd = incoming, .newfd_flags = O_CLOEXEC,
    };
    report->stage = "grant";
    int result = ioctl(listener, SECCOMP_IOCTL_NOTIF_ADDFD, &grant);
    error = result < 0 ? errno : 0;
    if (error == EINVAL) {
        // Older kernels support adding the already-authorized FD followed by a reply.
        report->atomic_addfd_errno = error;
        grant.flags = 0;
        report->stage = "addfd";
        result = ioctl(listener, SECCOMP_IOCTL_NOTIF_ADDFD, &grant);
        error = result < 0 ? errno : 0;
        if (!error) {
            ++report->legacy_injected;
            struct seccomp_notif_resp reply = {.id = request.id, .val = result};
            report->stage = "reply";
            if (ioctl(listener, SECCOMP_IOCTL_NOTIF_SEND, &reply) < 0) error = errno;
        }
    }
    close(incoming);
    if (!error) ++report->injected;
    return error;
}

static void node_worker(int channel, const char *entry, pid_t parent)
{
    if (prctl(PR_SET_PDEATHSIG, SIGKILL, 0, 0, 0) < 0 || getppid() != parent ||
        dup2(channel, STDIN_FILENO) < 0 || dup2(channel, STDOUT_FILENO) < 0 ||
        dup2(channel, STDERR_FILENO) < 0 || syscall(SYS_close_range, 3u, ~0u, 0u) < 0 ||
        clearenv() != 0 || ptc_deny_io_uring() != 0) _exit(100);
    void *node = dlopen("libnode.so", RTLD_NOW | RTLD_LOCAL);
    typedef int (*NodeStart)(int, char **);
    NodeStart start = node ? (NodeStart)dlsym(node, "_ZN4node5StartEiPPc") : NULL;
    if (!start) _exit(101);
    char *argv[] = {"node", "--jitless", "--no-warnings", (char *)entry, NULL};
    _exit(start(4, argv));
}

static int poll_case(int listener, int channel, int root, pid_t child, int writable, struct BrokerReport *report)
{
    struct pollfd descriptors[] = {{.fd = listener, .events = POLLIN}, {.fd = channel, .events = POLLIN}};
    for (int count = 0; count <= MAX_NOTIFICATIONS; ++count) {
        int ready;
        do { ready = poll(descriptors, 2, 2000); } while (ready < 0 && errno == EINTR);
        if (ready <= 0) return ready == 0 ? ETIMEDOUT : errno;
        if (descriptors[1].revents & POLLIN) {
            return read(channel, &report->worker, sizeof(report->worker)) ==
                sizeof(report->worker) ? 0 : EPROTO;
        }
        if (!(descriptors[0].revents & POLLIN)) return EIO;
        if (count == MAX_NOTIFICATIONS) return EOVERFLOW;
        int error = serve_open(listener, root, child, writable, report);
        if (error) return error;
    }
    return EIO;
}

static struct BrokerReport run_case(int root, const char *outside, int writable, int with_thread, const char *entry)
{
    struct BrokerReport report = {
        .stage = "get-sizes",
        .worker = {.error = {-1, -1, -1, -1}, .direct_openat2_errno = -1, .existing_thread_openat2_errno = -1},
    };
    struct seccomp_notif_sizes sizes;
    if (syscall(SYS_seccomp, SECCOMP_GET_NOTIF_SIZES, 0, &sizes) < 0) {
        report.protocol_error = errno;
        return report;
    }
    if (sizes.seccomp_notif != sizeof(struct seccomp_notif) ||
        sizes.seccomp_notif_resp != sizeof(struct seccomp_notif_resp)) {
        report.protocol_error = EPROTO;
        return report;
    }
    int sockets[2];
    report.stage = "startup";
    if (socketpair(AF_UNIX, SOCK_SEQPACKET | SOCK_CLOEXEC, 0, sockets) < 0) {
        report.protocol_error = errno;
        return report;
    }
    pid_t parent = getpid();
    pid_t child = fork();
    if (child == 0) {
        if (entry) node_worker(sockets[1], entry, parent);
        else worker(sockets[1], outside, parent, with_thread);
    }
    report.protocol_error = child < 0 ? errno : 0;
    close(sockets[1]);
    if (child > 0) {
        int listener = wait_readable(sockets[0]) ? -1 : ptc_transfer_listener(sockets[0], -1, 1);
        if (listener < 0) report.protocol_error = EPROTO;
        else {
            report.protocol_error = poll_case(listener, sockets[0], root, child, writable, &report);
            if (!report.protocol_error) report.stage = "complete";
            close(listener);
        }
        if (report.protocol_error) kill(child, SIGKILL);
        int status;
        pid_t reaped;
        do { reaped = waitpid(child, &status, 0); } while (reaped < 0 && errno == EINTR);
        report.reaped = reaped == child && WIFEXITED(status) && WEXITSTATUS(status) == 0;
    }
    close(sockets[0]);
    return report;
}

static int seed(int root, const char *name)
{
    int fd = openat(root, name, O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC, 0600);
    if (fd < 0) return -1;
    int result = write(fd, marker, sizeof(marker)) == sizeof(marker) ? 0 : -1;
    close(fd);
    return result;
}

static int format_case(char *buffer, size_t size, const struct BrokerReport *report)
{
    return snprintf(buffer, size,
                    "{\"protocolErrno\":%d,\"pathCopyErrno\":%d,\"injected\":%d,\"refused\":%d,"
                    "\"openErrnos\":[%d,%d,%d,%d],\"readVerified\":%d,\"writeVerified\":%d,"
                    "\"directOpenat2Errno\":%d,\"cleanExit\":%d,\"stage\":\"%s\","
                    "\"atomicAddfdErrno\":%d,\"legacyInjected\":%d,\"threadOpenat2Errno\":%d,"
                    "\"threadNotifications\":%d,\"requestedFlags\":[%d,%d,%d,%d],"
                    "\"directoryVerified\":%d,\"typedRead\":%d}",
                    report->protocol_error, report->path_copy_error, report->injected, report->refused,
                    report->worker.error[0], report->worker.error[1], report->worker.error[2], report->worker.error[3],
                    report->worker.read_correct, report->worker.write_correct, report->worker.direct_openat2_errno,
                    report->reaped, report->stage, report->atomic_addfd_errno, report->legacy_injected,
                    report->worker.existing_thread_openat2_errno, report->thread_notifications,
                    report->requested_flags[0], report->requested_flags[1],
                    report->requested_flags[2], report->requested_flags[3],
                    report->worker.directory_verified, report->worker.typed_read);
}

static void run_probe(const char *app_files, const char *entry, char *response, size_t size)
{
    char temp[1024], outside[1100];
    snprintf(temp, sizeof(temp), "%s/ptc-files.XXXXXX", app_files);
    if (!mkdtemp(temp)) {
        snprintf(response, size, "mkdtemp errno=%d", errno);
        return;
    }
    snprintf(outside, sizeof(outside), "%s/outside.txt", temp);
    int parent = open(temp, O_PATH | O_DIRECTORY | O_CLOEXEC);
    int root = parent >= 0 && mkdirat(parent, "workspace", 0700) == 0
        ? openat(parent, "workspace", O_PATH | O_DIRECTORY | O_CLOEXEC) : -1;
    if (root < 0 || seed(root, "read.txt") < 0 || seed(parent, "outside.txt") < 0) {
        snprintf(response, size, "fixture setup errno=%d", errno);
    } else {
        const struct BrokerReport ro = run_case(root, outside, 0, 0, entry);
        const int read_only_created = faccessat(root, "created.txt", F_OK, 0) == 0;
        const struct BrokerReport rw = run_case(root, outside, 1, 1, entry);
        const int file = openat(root, "created.txt", O_RDONLY | O_CLOEXEC);
        char data[sizeof(marker)] = {0};
        const int stored = file >= 0 && read(file, data, sizeof(data)) == sizeof(data)
            && !memcmp(data, marker, sizeof(data));
        if (file >= 0) close(file);
        char a[420], b[420];
        format_case(a, sizeof(a), &ro);
        format_case(b, sizeof(b), &rw);
        snprintf(response, size, "{\"readOnly\":%s,\"workspaceWrite\":%s,\"storedVerified\":%d,"
                 "\"readOnlyCreatedFile\":%d}", a, b, stored, read_only_created);
    }
    if (root >= 0) {
        unlinkat(root, "created.txt", 0);
        unlinkat(root, "read.txt", 0);
        close(root);
    }
    if (parent >= 0) {
        unlinkat(parent, "outside.txt", 0);
        unlinkat(parent, "workspace", AT_REMOVEDIR);
        close(parent);
    }
    rmdir(temp);
}

napi_value RunPtcFiles(napi_env env, napi_callback_info info)
{
    size_t count = 2, length = 0, entry_length = 0;
    napi_value args[2], result;
    char path[900], entry[1024], response[950];
    if (napi_get_cb_info(env, info, &count, args, NULL, NULL) != napi_ok || count != 2 ||
        napi_get_value_string_utf8(env, args[0], path, sizeof(path), &length) != napi_ok ||
        !length || length >= sizeof(path) - 1 || length != strlen(path) ||
        napi_get_value_string_utf8(env, args[1], entry, sizeof(entry), &entry_length) != napi_ok ||
        entry_length >= sizeof(entry) - 1 || entry_length != strlen(entry)) {
        napi_throw_type_error(env, NULL, "Expected app files directory and optional worker entry");
        return NULL;
    }
    run_probe(path, entry_length ? entry : NULL, response, sizeof(response));
    napi_create_string_utf8(env, response, NAPI_AUTO_LENGTH, &result);
    return result;
}

#define _GNU_SOURCE
#include "child-descriptors.h"
#include "workflow-broker.h"
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <linux/filter.h>
#include <linux/seccomp.h>
#include <stddef.h>
#include <poll.h>
#include <pthread.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/prctl.h>
#include <sys/socket.h>
#include <sys/syscall.h>
#include <sys/wait.h>
#include <unistd.h>

enum { START = 1, STOP, STATUS, START_PTC, START_OFFICE, MAX_WORKERS = 8 };
struct Request { int action; uint32_t id; struct PtcLaunch launch; };
struct Reply { int error; uint32_t id; pid_t pid; int finished; int status; };
struct Worker { uint32_t id; pid_t pid; int finished; int status; int ptc; };

static pthread_mutex_t client_lock = PTHREAD_MUTEX_INITIALIZER;
static int client = -1;
static pid_t broker = -1;

static int follow_parent(pid_t expected)
{
    return prctl(PR_SET_PDEATHSIG, SIGKILL, 0, 0, 0) == 0 && getppid() == expected;
}

// libuv may initialize an io_uring for epoll batching even when SQPOLL is disabled.
// Force its ordinary epoll path before Node initializes a loop or creates threads.
static int disable_io_uring(void)
{
    struct sock_filter rules[] = {
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, nr)),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, SYS_io_uring_setup, 0, 1),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | ENOSYS),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ALLOW),
    };
    const struct sock_fprog filter = {
        .len = sizeof(rules) / sizeof(rules[0]),
        .filter = rules,
    };
    return prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) ||
        syscall(SYS_seccomp, SECCOMP_SET_MODE_FILTER, 0, &filter);
}

static void run_worker(const char *entry, int channel, pid_t parent, int office)
{
    if (!follow_parent(parent) ||
        dup2(channel, STDIN_FILENO) < 0 ||
        dup2(channel, STDOUT_FILENO) < 0 ||
        dup2(channel, STDERR_FILENO) < 0 ||
        close_child_descriptors(STDERR_FILENO + 1, -1) != 0 ||
        clearenv() != 0 || disable_io_uring() != 0) _exit(125);
    if (office) {
        char directory[1100], home[1100];
        const char *slash = strrchr(entry, '/');
        if (!slash || setpgid(0, 0) < 0) _exit(125);
        snprintf(directory, sizeof(directory), "%.*s/tmp", (int)(slash - entry), entry);
        snprintf(home, sizeof(home), "%.*s/native-benchmark-home", (int)(slash - entry), entry);
        if (setenv("TMPDIR", directory, 1) || setenv("HOME", home, 1) || setenv("UV_USE_IO_URING", "0", 1)) _exit(125);
    }
    void *node = dlopen("libnode.so", RTLD_NOW | RTLD_LOCAL);
    typedef int (*NodeStart)(int, char **);
    NodeStart start = node ? (NodeStart)dlsym(node, "_ZN4node5StartEiPPc") : NULL;
    if (!start) _exit(126);
    char *argv[] = {"node", "--jitless", "--no-warnings", "--max-old-space-size=64", (char *)entry, NULL};
    char *office_argv[] = {"node", "--no-warnings", "--max-old-space-size=512", (char *)entry, NULL};
    _exit(start(office ? 4 : 5, office ? office_argv : argv));
}

static int send_reply(int channel, struct Reply reply, int fd)
{
    union { struct cmsghdr align; char buffer[CMSG_SPACE(sizeof(fd))]; } control;
    struct iovec data = {.iov_base = &reply, .iov_len = sizeof(reply)};
    struct msghdr message = {.msg_iov = &data, .msg_iovlen = 1};
    if (fd >= 0) {
        memset(&control, 0, sizeof(control));
        message.msg_control = control.buffer;
        message.msg_controllen = sizeof(control.buffer);
        struct cmsghdr *header = CMSG_FIRSTHDR(&message);
        header->cmsg_level = SOL_SOCKET;
        header->cmsg_type = SCM_RIGHTS;
        header->cmsg_len = CMSG_LEN(sizeof(fd));
        memcpy(CMSG_DATA(header), &fd, sizeof(fd));
    }
    return sendmsg(channel, &message, MSG_NOSIGNAL) == sizeof(reply);
}

static struct Worker *worker_slot(struct Worker *workers, uint32_t id)
{
    for (int i = 0; i < MAX_WORKERS; ++i) if (workers[i].id == id) return &workers[i];
    return NULL;
}

static void reap(struct Worker *worker)
{
    if (!worker->id || worker->finished) return;
    int status;
    if (waitpid(worker->pid, &status, WNOHANG) == worker->pid) {
        worker->finished = 1;
        worker->status = status;
    }
}

static void serve(int channel, const char *entry, pid_t parent)
{
    const struct sigaction child_signal = {.sa_handler = SIG_DFL};
    if (!follow_parent(parent) || dup2(channel, STDIN_FILENO) < 0 ||
        close_child_descriptors(STDIN_FILENO + 1, -1) != 0 ||
        sigaction(SIGCHLD, &child_signal, NULL) < 0) _exit(125);
    channel = STDIN_FILENO;
    const pid_t broker_pid = getpid();
    struct Worker workers[MAX_WORKERS] = {{0}};
    uint32_t next_id = 1;
    struct Request request;
    char ptc_entry[1024];
    snprintf(ptc_entry, sizeof(ptc_entry), "%s", entry);
    char *basename = strrchr(ptc_entry, '/');
    const char ptc_name[] = "/dsh-harmony-ptc-worker.mjs";
    int has_ptc = basename && (size_t)(basename - ptc_entry) + sizeof(ptc_name) <= sizeof(ptc_entry);
    if (has_ptc) memcpy(basename, ptc_name, sizeof(ptc_name));
    char office_entry[1024];
    snprintf(office_entry, sizeof(office_entry), "%s", entry);
    basename = strrchr(office_entry, '/');
    const char office_name[] = "/dsh-harmony-office-worker.mjs";
    int has_office = basename && (size_t)(basename - office_entry) + sizeof(office_name) <= sizeof(office_entry);
    if (has_office) memcpy(basename, office_name, sizeof(office_name));
    for (;;) {
        ssize_t count = recv(channel, &request, sizeof(request), 0);
        if (count < 0 && errno == EINTR) continue;
        if (count != sizeof(request)) break;
        for (int i = 0; i < MAX_WORKERS; ++i) reap(&workers[i]);
        struct Reply reply = {0};
        int worker_fd = -1;
        const int ptc = request.action == START_PTC;
        const int office = request.action == START_OFFICE;
        int invalid_roots = request.launch.extra_count < 0 || request.launch.extra_count > MH_PTC_EXTRA_ROOTS;
        for (int i = 0; !invalid_roots && i < request.launch.extra_count; ++i) {
            invalid_roots = request.launch.extra_roots[i][0] != '/' ||
                !memchr(request.launch.extra_roots[i], 0, sizeof(request.launch.extra_roots[i]));
        }
        if (request.action == START || ptc || office) {
            struct Worker *worker = worker_slot(workers, 0);
            int pair[2];
            if (ptc && (invalid_roots || !has_ptc || request.launch.root[0] != '/' ||
                        !memchr(request.launch.root, 0, sizeof(request.launch.root)) ||
                        request.launch.cwd[0] != '/' ||
                        !memchr(request.launch.cwd, 0, sizeof(request.launch.cwd)))) reply.error = EINVAL;
            else if (office && !has_office) reply.error = EINVAL;
            else if (!worker) reply.error = EBUSY;
            else if (next_id == 0) reply.error = EOVERFLOW;
            else if (socketpair(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0, pair) < 0) reply.error = errno;
            else {
                pid_t pid = fork();
                if (pid == 0) {
                    close(pair[0]);
                    if (ptc) harmony_ptc_supervise(ptc_entry, pair[1], broker_pid, &request.launch);
                    else run_worker(office ? office_entry : entry, pair[1], broker_pid, office);
                }
                if (pid < 0) {
                    reply.error = errno;
                    close(pair[0]);
                } else {
                    *worker = (struct Worker){.id = next_id++, .pid = pid, .ptc = ptc};
                    reply.id = worker->id;
                    reply.pid = pid;
                    worker_fd = pair[0];
                }
                close(pair[1]);
            }
        } else {
            struct Worker *worker = request.id ? worker_slot(workers, request.id) : NULL;
            if (!worker) reply.error = ESRCH;
            else if (request.action == STATUS) {
                reply.finished = worker->finished;
                reply.status = worker->status;
                if (worker->finished) worker->id = 0;
            } else if (request.action == STOP) {
                if (!worker->finished && kill(worker->pid, worker->ptc ? SIGTERM : SIGKILL) < 0 && errno != ESRCH)
                    reply.error = errno;
            } else reply.error = EINVAL;
        }
        const int sent = send_reply(channel, reply, worker_fd);
        if (worker_fd >= 0) close(worker_fd);
        if (!sent) break;
    }
    for (int i = 0; i < MAX_WORKERS; ++i) {
        if (workers[i].id && !workers[i].finished) kill(workers[i].pid, SIGKILL);
    }
    _exit(0);
}

int harmony_workflow_broker_start(const char *entry)
{
    pthread_mutex_lock(&client_lock);
    int error = 0;
    if (client >= 0 || broker > 0) error = EALREADY;
    else {
        int pair[2];
        if (socketpair(AF_UNIX, SOCK_SEQPACKET | SOCK_CLOEXEC, 0, pair) < 0) error = errno;
        else {
            const pid_t parent = getpid();
            const pid_t child = fork();
            if (child == 0) serve(pair[1], entry, parent);
            if (child < 0) {
                error = errno;
                close(pair[0]);
            } else {
                broker = child;
                client = pair[0];
            }
            close(pair[1]);
        }
    }
    pthread_mutex_unlock(&client_lock);
    return error;
}

static int exchange(struct Request request, struct Reply *reply, int *fd)
{
    int error = EIO;
    int received_fd = -1;
    pthread_mutex_lock(&client_lock);
    if (client < 0) error = ENOTCONN;
    else if (send(client, &request, sizeof(request), MSG_NOSIGNAL | MSG_DONTWAIT) != sizeof(request)) error = errno;
    else {
        struct pollfd ready = {.fd = client, .events = POLLIN};
        const int count = poll(&ready, 1, 500);
        if (count <= 0) error = count ? errno : ETIMEDOUT;
        else {
            union { struct cmsghdr align; char buffer[CMSG_SPACE(sizeof(int))]; } control;
            struct iovec data = {.iov_base = reply, .iov_len = sizeof(*reply)};
            struct msghdr message = {
                .msg_iov = &data, .msg_iovlen = 1, .msg_control = control.buffer,
                .msg_controllen = sizeof(control.buffer),
            };
            const ssize_t bytes = recvmsg(client, &message, MSG_DONTWAIT | MSG_CMSG_CLOEXEC);
            if (bytes >= 0) {
                struct cmsghdr *header = CMSG_FIRSTHDR(&message);
                if (header && header->cmsg_level == SOL_SOCKET && header->cmsg_type == SCM_RIGHTS &&
                    header->cmsg_len == CMSG_LEN(sizeof(received_fd))) {
                    memcpy(&received_fd, CMSG_DATA(header), sizeof(received_fd));
                }
                if (bytes == sizeof(*reply) && !(message.msg_flags & (MSG_TRUNC | MSG_CTRUNC)) &&
                    ((received_fd >= 0) == (fd && reply->error == 0))) {
                    error = reply->error;
                    if (received_fd >= 0) *fd = received_fd;
                    received_fd = -1;
                    pthread_mutex_unlock(&client_lock);
                    return error;
                }
            }
        }
    }
    if (received_fd >= 0) close(received_fd);
    // A lost response leaves the stream between requests. Close instead of reusing it.
    if (client >= 0) {
        close(client);
        client = -1;
    }
    pthread_mutex_unlock(&client_lock);
    return error;
}

int harmony_workflow_spawn(struct WorkflowChild *child)
{
    struct Reply reply;
    int error = exchange((struct Request){.action = START}, &reply, &child->fd);
    if (!error) {
        child->id = reply.id;
        child->pid = reply.pid;
    }
    return error;
}

int harmony_ptc_spawn(const struct PtcLaunch *launch, struct WorkflowChild *child)
{
    struct Reply reply;
    int error = exchange((struct Request){.action = START_PTC, .launch = *launch}, &reply, &child->fd);
    if (!error) {
        child->id = reply.id;
        child->pid = reply.pid;
    }
    return error;
}

int harmony_office_spawn(struct WorkflowChild *child)
{
    struct Reply reply;
    int error = exchange((struct Request){.action = START_OFFICE}, &reply, &child->fd);
    if (!error) {
        child->id = reply.id;
        child->pid = reply.pid;
    }
    return error;
}

int harmony_workflow_stop(uint32_t id)
{
    struct Reply reply;
    return exchange((struct Request){.action = STOP, .id = id}, &reply, NULL);
}

int harmony_workflow_status(uint32_t id, int *finished, int *wait_status)
{
    struct Reply reply;
    int error = exchange((struct Request){.action = STATUS, .id = id}, &reply, NULL);
    if (!error) {
        *finished = reply.finished;
        *wait_status = reply.status;
    }
    return error;
}

void harmony_workflow_broker_close(void)
{
    pthread_mutex_lock(&client_lock);
    if (client >= 0) {
        close(client);
        client = -1;
    }
    if (broker > 0) {
        pid_t observed;
        do { observed = waitpid(broker, NULL, WNOHANG); } while (observed < 0 && errno == EINTR);
        if (observed == 0) {
            if (kill(broker, SIGKILL) < 0 && errno != ESRCH) {
                pthread_mutex_unlock(&client_lock);
                return;
            }
            while (waitpid(broker, NULL, 0) < 0 && errno == EINTR) {}
        }
        broker = -1;
    }
    pthread_mutex_unlock(&client_lock);
}

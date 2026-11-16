#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <napi/native_api.h>
#include <poll.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/prctl.h>
#include <sys/socket.h>
#include <sys/syscall.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

typedef int (*NodeStart)(int, char **);

static void launch_child(const char *entry, int input, int output, pid_t parent)
{
    if (prctl(PR_SET_PDEATHSIG, SIGKILL, 0, 0, 0) < 0 || getppid() != parent) _exit(91);
    if (dup2(input, STDIN_FILENO) < 0 || dup2(output, STDOUT_FILENO) < 0 ||
        dup2(output, STDERR_FILENO) < 0) _exit(92);
    if (syscall(SYS_close_range, 3u, ~0u, 0u) < 0) _exit(93);
    if (clearenv() != 0) _exit(94);
    void *node = dlopen("libnode.so", RTLD_NOW | RTLD_LOCAL);
    NodeStart start = node ? (NodeStart)dlsym(node, "_ZN4node5StartEiPPc") : NULL;
    if (!start) {
        dprintf(STDOUT_FILENO, "cannot load embedded Node: %s", dlerror());
        _exit(95);
    }
    char *argv[] = {"node", "--jitless", "--no-warnings", "--max-old-space-size=64", (char *)entry, NULL};
    _exit(start(5, argv));
}

static int64_t now_ms(void)
{
    struct timespec time;
    clock_gettime(CLOCK_MONOTONIC, &time);
    return (int64_t)time.tv_sec * 1000 + time.tv_nsec / 1000000;
}

static ssize_t receive(int fd, void *buffer, size_t size, int64_t deadline)
{
    int64_t remaining = deadline - now_ms();
    if (remaining <= 0) {
        errno = ETIMEDOUT;
        return -1;
    }
    struct pollfd ready = {.fd = fd, .events = POLLIN};
    const int observed = poll(&ready, 1, (int)remaining);
    if (observed == 0) errno = ETIMEDOUT;
    if (observed <= 0) return -1;
    return read(fd, buffer, size);
}

static bool run_node(const char *entry, const char *fixture, bool expect_timeout, char *report, size_t size)
{
    int request[2];
    if (socketpair(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0, request) < 0) {
        snprintf(report, size, "request socket errno=%d", errno);
        return false;
    }
    int output[2];
    if (pipe2(output, O_CLOEXEC) < 0) {
        snprintf(report, size, "probe output pipe errno=%d", errno);
        close(request[0]);
        close(request[1]);
        return false;
    }
    pid_t parent = getpid();
    pid_t child = request[0] > 2 && request[1] > 2 && output[0] > 2 && output[1] > 2 ? fork() : -1;
    if (child == 0) launch_child(entry, request[1], output[1], parent);
    close(request[1]);
    close(output[1]);
    int64_t deadline = now_ms() + 6000;
    int64_t dispatched_at = 0;
    size_t length = 0;
    int transport_ok = 0;
    if (child > 0) {
        char marker;
        ssize_t count = receive(output[0], &marker, 1, deadline);
        if (count == 1 && marker == '+') {
            dispatched_at = now_ms();
            deadline = dispatched_at + 1500;
            size_t length = strlen(fixture);
            transport_ok = send(request[0], fixture, length, MSG_NOSIGNAL) == (ssize_t)length;
        } else if (count == 1) {
            report[length++] = marker;
        }
    }
    close(request[0]);
    ssize_t count = -1;
    while (child > 0 && length < size - 1) {
        count = receive(output[0], report + length, size - 1 - length, deadline);
        if (count < 0 && errno == EINTR) continue;
        if (count <= 0) break;
        length += (size_t)count;
    }
    const bool timed_out = count < 0 && errno == ETIMEDOUT;
    close(output[0]);
    int status = 0;
    pid_t observed = child > 0 ? waitpid(child, &status, WNOHANG) : -1;
    while (observed == 0 && now_ms() < deadline && count == 0) {
        usleep(1000);
        observed = waitpid(child, &status, WNOHANG);
    }
    bool killed = false;
    if (observed == 0) {
        killed = kill(child, SIGKILL) == 0;
        do { observed = waitpid(child, &status, 0); } while (observed < 0 && errno == EINTR);
    }
    report[length] = '\0';
    if (expect_timeout && transport_ok && timed_out && killed && observed == child && WIFSIGNALED(status) &&
        WTERMSIG(status) == SIGKILL && strcmp(report, "!") == 0) {
        snprintf(report, size, "{\"timedOut\":true,\"signal\":%d,\"wallMs\":%lld}",
                 WTERMSIG(status), (long long)(now_ms() - dispatched_at));
        return true;
    }
    if (!expect_timeout && transport_ok && count == 0 && child > 0 && observed == child &&
        WIFEXITED(status) && WEXITSTATUS(status) == 0 && strncmp(report, "!{", 2) == 0) return true;
    snprintf(report + length, size - length, " [worker probe failed: input=%d read=%zd status=%d]",
             transport_ok, count, status);
    return false;
}

napi_value RunWorkflowNode(napi_env env, napi_callback_info info)
{
    size_t argc = 1, length = 0;
    char entry[1024], report[1024], timeout[256], result_text[1310];
    napi_value args[1], result;
    if (napi_get_cb_info(env, info, &argc, args, NULL, NULL) != napi_ok || argc != 1 ||
        napi_get_value_string_utf8(env, args[0], entry, sizeof(entry), &length) != napi_ok ||
        length == 0 || length >= sizeof(entry) - 1 || length != strlen(entry)) {
        napi_throw_type_error(env, NULL, "Expected the packaged probe entry path");
        return NULL;
    }
    bool completed = run_node(entry, "phase('Probe'); return await parallel([() => agent('one'), () => agent('two')]);",
                              false, report, sizeof(report));
    if (completed) {
        run_node(entry, "while (true) {}", true, timeout, sizeof(timeout));
        snprintf(result_text, sizeof(result_text), "%s\ntimeoutProbe=%s", report + 1, timeout);
    } else {
        snprintf(result_text, sizeof(result_text), "%s", report);
    }
    napi_create_string_utf8(env, result_text, NAPI_AUTO_LENGTH, &result);
    return result;
}

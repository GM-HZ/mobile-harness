#define _GNU_SOURCE
#include "workflow-broker.h"
#include <errno.h>
#include <napi/native_api.h>
#include <poll.h>
#include <signal.h>
#include <stdio.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

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

static int wait_worker(uint32_t id, int *status)
{
    const int64_t deadline = now_ms() + 500;
    for (;;) {
        int finished;
        int error = harmony_workflow_status(id, &finished, status);
        if (error || finished) return error;
        if (now_ms() >= deadline) return ETIMEDOUT;
        usleep(1000);
    }
}

static bool run_node(struct WorkflowChild child, const char *fixture, bool expect_timeout, char *report, size_t size)
{
    int64_t deadline = now_ms() + 6000;
    int64_t dispatched_at = 0;
    size_t length = 0;
    int transport_ok = 0;
    char marker;
    ssize_t count = receive(child.fd, &marker, 1, deadline);
    if (count == 1 && marker == '+') {
        dispatched_at = now_ms();
        deadline = dispatched_at + 1500;
        size_t fixture_size = strlen(fixture);
        transport_ok = send(child.fd, fixture, fixture_size, MSG_NOSIGNAL) == (ssize_t)fixture_size;
    } else if (count == 1) {
        report[length++] = marker;
    }
    shutdown(child.fd, SHUT_WR);
    while (length < size - 1) {
        count = receive(child.fd, report + length, size - 1 - length, deadline);
        if (count < 0 && errno == EINTR) continue;
        if (count <= 0) break;
        length += (size_t)count;
    }
    const bool timed_out = count < 0 && errno == ETIMEDOUT;
    bool killed = count != 0 && harmony_workflow_stop(child.id) == 0;
    close(child.fd);
    int status = 0;
    int error = wait_worker(child.id, &status);
    report[length] = '\0';
    if (expect_timeout && transport_ok && timed_out && killed && !error && WIFSIGNALED(status) &&
        WTERMSIG(status) == SIGKILL && strcmp(report, "!") == 0) {
        snprintf(report, size, "{\"workerId\":%u,\"timedOut\":true,\"signal\":%d,\"wallMs\":%lld}",
                 child.id, WTERMSIG(status), (long long)(now_ms() - dispatched_at));
        return true;
    }
    if (!expect_timeout && transport_ok && count == 0 && !error &&
        WIFEXITED(status) && WEXITSTATUS(status) == 0 && strncmp(report, "!{", 2) == 0) return true;
    snprintf(report + length, size - length, " [worker probe failed: input=%d read=%zd status=%d broker=%d]",
             transport_ok, count, status, error);
    return false;
}

napi_value RunWorkflowNode(napi_env env, napi_callback_info info)
{
    size_t argc = 1, length = 0;
    char entry[1024], report[1024], timeout[256], result_text[1430];
    napi_value args[1], result;
    if (napi_get_cb_info(env, info, &argc, args, NULL, NULL) != napi_ok || argc != 1 ||
        napi_get_value_string_utf8(env, args[0], entry, sizeof(entry), &length) != napi_ok ||
        length == 0 || length >= sizeof(entry) - 1 || length != strlen(entry)) {
        napi_throw_type_error(env, NULL, "Expected the packaged probe entry path");
        return NULL;
    }
    int error = harmony_workflow_broker_start(entry);
    struct WorkflowChild regular = {.fd = -1}, spinning = {.fd = -1};
    if (!error) error = harmony_workflow_spawn(&regular);
    if (!error) error = harmony_workflow_spawn(&spinning);
    if (error) {
        snprintf(result_text, sizeof(result_text), "broker setup errno=%d", error);
    } else if (run_node(regular, "phase('Probe'); return await parallel([() => agent('one'), () => agent('two')]);",
                       false, report, sizeof(report))) {
        regular.fd = -1;
        run_node(spinning, "while (true) {}", true, timeout, sizeof(timeout));
        spinning.fd = -1;
        int finished, status;
        bool retired = harmony_workflow_status(regular.id, &finished, &status) == ESRCH &&
            harmony_workflow_status(spinning.id, &finished, &status) == ESRCH;
        snprintf(result_text, sizeof(result_text), "%s\nbrokerTimeout=%s\nbrokerWorkers=%d,%d retired=%s",
                 report + 1, timeout, regular.pid, spinning.pid, retired ? "true" : "false");
    } else {
        regular.fd = -1;
        snprintf(result_text, sizeof(result_text), "%s", report);
    }
    if (regular.fd >= 0) close(regular.fd);
    if (spinning.fd >= 0) close(spinning.fd);
    harmony_workflow_broker_close();
    napi_create_string_utf8(env, result_text, NAPI_AUTO_LENGTH, &result);
    return result;
}

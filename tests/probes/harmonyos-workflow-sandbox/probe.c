#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <linux/audit.h>
#include <linux/filter.h>
#include <linux/openat2.h>
#include <linux/seccomp.h>
#include <napi/native_api.h>
#include <stddef.h>
#include <stdio.h>
#include <sys/prctl.h>
#include <sys/socket.h>
#include <sys/syscall.h>
#include <sys/wait.h>
#include <unistd.h>

struct Outcome {
    int baseline_open;
    int baseline_socket;
    int landlock_abi;
    int landlock_errno;
    int no_new_privileges_errno;
    int filter_errno;
    int notification_action_errno;
    int notification_listener_errno;
    int openat2_errno;
    int open_errno;
    int socket_errno;
    int exec_errno;
};

#define ALLOW_SYSCALL(number) \
    BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, number, 0, 1), BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ALLOW)

static void probe_child(int output)
{
    struct Outcome outcome = {
        .filter_errno = -1, .open_errno = -1, .socket_errno = -1, .exec_errno = -1,
    };
    int file = open("/dev/null", O_RDONLY);
    outcome.baseline_open = file < 0 ? errno : 0;
    if (file >= 0) close(file);
    int socket_fd = socket(AF_INET, SOCK_STREAM, 0);
    outcome.baseline_socket = socket_fd < 0 ? errno : 0;
    if (socket_fd >= 0) close(socket_fd);
    outcome.landlock_abi = (int)syscall(SYS_landlock_create_ruleset, NULL, 0, 1);
    outcome.landlock_errno = outcome.landlock_abi < 0 ? errno : 0;
    const struct open_how how = {.flags = O_RDONLY | O_CLOEXEC};
    file = (int)syscall(SYS_openat2, AT_FDCWD, "/dev/null", &how, sizeof(how));
    outcome.openat2_errno = file < 0 ? errno : 0;
    if (file >= 0) close(file);
    uint32_t action = SECCOMP_RET_USER_NOTIF;
    outcome.notification_action_errno = syscall(SYS_seccomp, SECCOMP_GET_ACTION_AVAIL, 0, &action) < 0 ? errno : 0;

    struct sock_filter instructions[] = {
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, arch)),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, AUDIT_ARCH_AARCH64, 1, 0),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_KILL_PROCESS),
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, nr)),
        ALLOW_SYSCALL(SYS_write),
        ALLOW_SYSCALL(SYS_exit),
        ALLOW_SYSCALL(SYS_exit_group),
        ALLOW_SYSCALL(SYS_rt_sigreturn),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | EPERM),
    };
    const struct sock_fprog filter = {
        .len = sizeof(instructions) / sizeof(instructions[0]),
        .filter = instructions,
    };
    outcome.no_new_privileges_errno = prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) < 0 ? errno : 0;
    outcome.notification_listener_errno = -1;
    if (!outcome.no_new_privileges_errno) {
        struct sock_filter test[] = {BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ALLOW)};
        const struct sock_fprog listener_filter = {.len = 1, .filter = test};
        int listener = (int)syscall(SYS_seccomp, SECCOMP_SET_MODE_FILTER,
                                    SECCOMP_FILTER_FLAG_NEW_LISTENER, &listener_filter);
        outcome.notification_listener_errno = listener < 0 ? errno : 0;
        if (listener >= 0) close(listener);
        long installed = syscall(SYS_seccomp, SECCOMP_SET_MODE_FILTER, SECCOMP_FILTER_FLAG_TSYNC, &filter);
        outcome.filter_errno = installed < 0 ? errno : installed == 0 ? 0 : EBUSY;
        if (!outcome.filter_errno) {
            outcome.open_errno = syscall(SYS_openat, AT_FDCWD, "/dev/null", O_RDONLY, 0) < 0 ? errno : 0;
            outcome.socket_errno = syscall(SYS_socket, AF_INET, SOCK_STREAM, 0) < 0 ? errno : 0;
            outcome.exec_errno = syscall(SYS_execve, "/nonexistent-workflow-probe", NULL, NULL) < 0 ? errno : 0;
        }
    }
    const ssize_t written = write(output, &outcome, sizeof(outcome));
    _exit(written == sizeof(outcome) ? 0 : 1);
}

static napi_value run(napi_env env, napi_callback_info info)
{
    (void)info;
    char response[512];
    int pipe_fd[2];
    if (pipe(pipe_fd) < 0) {
        snprintf(response, sizeof(response), "pipe errno=%d", errno);
    } else {
        pid_t pid = fork();
        if (pid == 0) {
            close(pipe_fd[0]);
            probe_child(pipe_fd[1]);
        }
        const int fork_errno = pid < 0 ? errno : 0;
        close(pipe_fd[1]);
        struct Outcome outcome;
        ssize_t count = pid < 0 ? -1 : read(pipe_fd[0], &outcome, sizeof(outcome));
        close(pipe_fd[0]);
        int status = 0;
        if (pid > 0) while (waitpid(pid, &status, 0) < 0 && errno == EINTR) {}
        if (count == sizeof(outcome) && WIFEXITED(status) && WEXITSTATUS(status) == 0) {
            snprintf(response, sizeof(response),
                "{\"baselineOpenErrno\":%d,\"baselineSocketErrno\":%d,\"landlockAbi\":%d,\"landlockErrno\":%d,"
                "\"noNewPrivilegesErrno\":%d,\"seccompTsyncErrno\":%d,\"filteredOpenErrno\":%d,"
                "\"filteredSocketErrno\":%d,\"filteredExecErrno\":%d,\"inheritedPipeWrite\":true,"
                "\"notificationActionErrno\":%d,\"notificationListenerErrno\":%d,\"openat2Errno\":%d}",
                outcome.baseline_open, outcome.baseline_socket, outcome.landlock_abi, outcome.landlock_errno,
                outcome.no_new_privileges_errno, outcome.filter_errno, outcome.open_errno,
                outcome.socket_errno, outcome.exec_errno, outcome.notification_action_errno,
                outcome.notification_listener_errno, outcome.openat2_errno);
        } else {
            snprintf(response, sizeof(response), "child report missing fork_errno=%d bytes=%zd wait_status=%d",
                fork_errno, count, status);
        }
    }
    napi_value result;
    napi_create_string_utf8(env, response, NAPI_AUTO_LENGTH, &result);
    return result;
}

napi_value RunWorkflowNode(napi_env env, napi_callback_info info);
napi_value RunPtcFiles(napi_env env, napi_callback_info info);

static napi_value init(napi_env env, napi_value exports)
{
    const napi_property_descriptor properties[] = {
        {"run", NULL, run, NULL, NULL, NULL, napi_default, NULL},
        {"runNode", NULL, RunWorkflowNode, NULL, NULL, NULL, napi_default, NULL},
        {"runFiles", NULL, RunPtcFiles, NULL, NULL, NULL, napi_default, NULL},
    };
    napi_define_properties(env, exports, sizeof(properties) / sizeof(properties[0]), properties);
    return exports;
}

static napi_module module = {1, 0, NULL, init, "workflowprobe", NULL, {0}};
__attribute__((constructor)) static void register_module(void)
{
    napi_module_register(&module);
}

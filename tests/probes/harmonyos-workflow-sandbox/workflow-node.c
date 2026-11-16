#define _GNU_SOURCE
#include <errno.h>
#include <linux/audit.h>
#include <linux/filter.h>
#include <linux/seccomp.h>
#include <node_api.h>
#include <poll.h>
#include <stddef.h>
#include <sys/mman.h>
#include <sys/prctl.h>
#include <sys/socket.h>
#include <sys/syscall.h>
#include <unistd.h>

#define LOAD_ARG(arg) BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, args[arg]))
#define ALLOW BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ALLOW)
#define DENY BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | EPERM)
#define ALLOW_CALL(number) BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, number, 0, 1), ALLOW
#define ALLOW_ARG(number, arg, value) BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, number, 0, 4), \
    LOAD_ARG(arg), BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, value, 0, 1), ALLOW, DENY

static int restrict_worker(void)
{
    struct sock_filter rules[] = {
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, arch)),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, AUDIT_ARCH_AARCH64, 1, 0),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_KILL_PROCESS),
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, nr)),
        ALLOW_ARG(SYS_read, 0, STDIN_FILENO),
        ALLOW_ARG(SYS_write, 0, STDOUT_FILENO),
        ALLOW_ARG(SYS_ppoll, 1, 1),
        ALLOW_CALL(SYS_futex),
        ALLOW_CALL(SYS_clock_gettime),
        ALLOW_CALL(SYS_getpid),
        ALLOW_CALL(SYS_gettid),
        ALLOW_CALL(SYS_sched_yield),
        ALLOW_CALL(SYS_brk),
        ALLOW_CALL(SYS_munmap),
        ALLOW_CALL(SYS_madvise),
        ALLOW_CALL(SYS_exit),
        ALLOW_CALL(SYS_exit_group),
        ALLOW_CALL(SYS_rt_sigreturn),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, SYS_mprotect, 0, 4),
        LOAD_ARG(2), BPF_JUMP(BPF_JMP | BPF_JSET | BPF_K, PROT_EXEC, 1, 0), ALLOW, DENY,
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, SYS_mmap, 0, 6),
        LOAD_ARG(2), BPF_JUMP(BPF_JMP | BPF_JSET | BPF_K, PROT_EXEC, 2, 0),
        LOAD_ARG(3), BPF_JUMP(BPF_JMP | BPF_JSET | BPF_K, MAP_ANONYMOUS, 1, 0), DENY,
        ALLOW,
        DENY,
    };
    const struct sock_fprog filter = {
        .len = sizeof(rules) / sizeof(rules[0]),
        .filter = rules,
    };
    if (prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) < 0) return errno;
    const long result = syscall(SYS_seccomp, SECCOMP_SET_MODE_FILTER, SECCOMP_FILTER_FLAG_TSYNC, &filter);
    return result < 0 ? errno : result == 0 ? 0 : EBUSY;
}

static napi_value number(napi_env env, int code)
{
    napi_value value;
    napi_create_int32(env, code, &value);
    return value;
}

static napi_value confine(napi_env env, napi_callback_info info)
{
    (void)info;
    return number(env, restrict_worker());
}

static napi_value socket_errno(napi_env env, napi_callback_info info)
{
    (void)info;
    const int fd = socket(AF_INET, SOCK_STREAM, 0);
    if (fd < 0) return number(env, errno);
    close(fd);
    return number(env, 0);
}

static napi_value finish(napi_env env, napi_callback_info info)
{
    (void)env;
    (void)info;
    _exit(0);
}

static napi_value wait_input(napi_env env, napi_callback_info info)
{
    (void)info;
    struct pollfd input = {.fd = STDIN_FILENO, .events = POLLIN};
    const int ready = poll(&input, 1, 2000);
    return number(env, ready > 0 ? 0 : ready == 0 ? ETIMEDOUT : errno);
}

NAPI_MODULE_INIT()
{
    const napi_property_descriptor properties[] = {
        {"confine", NULL, confine, NULL, NULL, NULL, napi_default, NULL},
        {"socketErrno", NULL, socket_errno, NULL, NULL, NULL, napi_default, NULL},
        {"finish", NULL, finish, NULL, NULL, NULL, napi_default, NULL},
        {"waitInput", NULL, wait_input, NULL, NULL, NULL, napi_default, NULL},
    };
    napi_define_properties(env, exports, sizeof(properties) / sizeof(properties[0]), properties);
    return exports;
}

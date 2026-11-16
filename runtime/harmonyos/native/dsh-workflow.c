#define _GNU_SOURCE
#include "workflow-broker.h"
#include <dlfcn.h>
#include <errno.h>
#include <linux/audit.h>
#include <linux/filter.h>
#include <linux/seccomp.h>
#include <node_api.h>
#include <poll.h>
#include <stddef.h>
#include <stdio.h>
#include <sys/mman.h>
#include <sys/prctl.h>
#include <sys/syscall.h>
#include <sys/wait.h>
#include <unistd.h>

#define LOAD_ARG(arg) BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, args[arg]))
#define ALLOW BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ALLOW)
#define DENY BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | EPERM)
#define ALLOW_CALL(number) BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, number, 0, 1), ALLOW
#define CHANNEL_CALL(number) BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, number, 0, 4), \
    LOAD_ARG(0), BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, STDIN_FILENO, 0, 1), ALLOW, DENY

static int restrict_worker(void)
{
    struct sock_filter rules[] = {
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, arch)),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, AUDIT_ARCH_AARCH64, 1, 0),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_KILL_PROCESS),
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, nr)),
        CHANNEL_CALL(SYS_read),
        CHANNEL_CALL(SYS_write),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, SYS_ppoll, 0, 4),
        LOAD_ARG(1), BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, 1, 0, 1), ALLOW, DENY,
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

static napi_value error_value(napi_env env, const char *action, int error)
{
    char message[110];
    snprintf(message, sizeof(message), "Workflow %s failed (errno %d)", action, error);
    napi_throw_error(env, NULL, message);
    return NULL;
}

static void set_number(napi_env env, napi_value object, const char *name, uint32_t number)
{
    napi_value value;
    napi_create_uint32(env, number, &value);
    napi_set_named_property(env, object, name, value);
}

static void *broker_symbol(const char *symbol)
{
    void *poc = dlopen("libpoc.so", RTLD_NOW | RTLD_NOLOAD);
    if (!poc) return NULL;
    void *address = dlsym(poc, symbol);
    dlclose(poc);
    return address;
}

static napi_value launch(napi_env env, napi_callback_info info)
{
    (void)info;
    int (*spawn)(struct WorkflowChild *) = broker_symbol("harmony_workflow_spawn");
    struct WorkflowChild child;
    int error = spawn ? spawn(&child) : ENOSYS;
    if (error) return error_value(env, "launch", error);
    napi_value result;
    napi_create_object(env, &result);
    set_number(env, result, "id", child.id);
    set_number(env, result, "fd", child.fd);
    return result;
}

static napi_value request(napi_env env, napi_callback_info info, int stop)
{
    size_t argc = 1;
    napi_value args[1], result;
    uint32_t id;
    if (napi_get_cb_info(env, info, &argc, args, NULL, NULL) != napi_ok || argc != 1 ||
        napi_get_value_uint32(env, args[0], &id) != napi_ok || !id) return error_value(env, "worker ID", EINVAL);
    if (stop) {
        int (*terminate)(uint32_t) = broker_symbol("harmony_workflow_stop");
        int error = terminate ? terminate(id) : ENOSYS;
        if (error) return error_value(env, "terminate", error);
        napi_get_undefined(env, &result);
    } else {
        int (*status)(uint32_t, int *, int *) = broker_symbol("harmony_workflow_status");
        int finished, state;
        int error = status ? status(id, &finished, &state) : ENOSYS;
        if (error) return error_value(env, "status", error);
        if (!finished) napi_get_null(env, &result);
        else {
            napi_create_object(env, &result);
            set_number(env, result, "exitCode", WIFEXITED(state) ? WEXITSTATUS(state) : 255);
            set_number(env, result, "signal", WIFSIGNALED(state) ? WTERMSIG(state) : 0);
        }
    }
    return result;
}

static napi_value terminate(napi_env env, napi_callback_info info) { return request(env, info, 1); }
static napi_value status(napi_env env, napi_callback_info info) { return request(env, info, 0); }

static napi_value confine(napi_env env, napi_callback_info info)
{
    (void)info;
    int error = restrict_worker();
    if (error) return error_value(env, "seccomp", error);
    napi_value result;
    napi_get_undefined(env, &result);
    return result;
}

static napi_value finish(napi_env env, napi_callback_info info)
{
    size_t argc = 1;
    napi_value args[1];
    uint32_t code;
    if (napi_get_cb_info(env, info, &argc, args, NULL, NULL) != napi_ok || argc != 1 ||
        napi_get_value_uint32(env, args[0], &code) != napi_ok || code > 1) return error_value(env, "exit", EINVAL);
    _exit(code);
}

static napi_value wait_channel(napi_env env, napi_callback_info info)
{
    size_t argc = 1;
    napi_value args[1], result;
    bool writing;
    if (napi_get_cb_info(env, info, &argc, args, NULL, NULL) != napi_ok || argc != 1 ||
        napi_get_value_bool(env, args[0], &writing) != napi_ok) return error_value(env, "poll request", EINVAL);
    struct pollfd control = {.fd = STDIN_FILENO, .events = writing ? POLLOUT : POLLIN};
    int ready;
    do { ready = poll(&control, 1, -1); } while (ready < 0 && errno == EINTR);
    if (ready < 0) return error_value(env, "poll", errno);
    napi_get_undefined(env, &result);
    return result;
}

NAPI_MODULE_INIT()
{
    const napi_property_descriptor properties[] = {
        {"launch", NULL, launch, NULL, NULL, NULL, napi_default, NULL},
        {"terminate", NULL, terminate, NULL, NULL, NULL, napi_default, NULL},
        {"status", NULL, status, NULL, NULL, NULL, napi_default, NULL},
        {"confine", NULL, confine, NULL, NULL, NULL, napi_default, NULL},
        {"finish", NULL, finish, NULL, NULL, NULL, napi_default, NULL},
        {"waitChannel", NULL, wait_channel, NULL, NULL, NULL, napi_default, NULL},
    };
    napi_define_properties(env, exports, sizeof(properties) / sizeof(properties[0]), properties);
    return exports;
}

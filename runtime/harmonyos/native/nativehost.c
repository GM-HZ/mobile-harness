#include <napi/native_api.h>
#include <dlfcn.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdbool.h>
#include <stdio.h>
#include "workflow-broker.h"
#ifdef MOBILE_HARNESS_EXPERIMENTAL_FORK
#include <errno.h>
#include <signal.h>
#include <sys/prctl.h>
#include <sys/wait.h>
#include <unistd.h>
#include <hilog/log.h>
#endif

static atomic_int status = 0;
static char entry[1024];
static char directory[900];
static bool safe_mode = false;
typedef int (*NodeStart)(int, char **);

static int RunHost(void) {
    char workflow_entry[1024];
    snprintf(workflow_entry, sizeof(workflow_entry), "%s/dsh-harmony-workflow-worker.cjs", directory);
    if (!safe_mode) {
        int broker_error = harmony_workflow_broker_start(workflow_entry);
        if (broker_error) {
            fprintf(stderr, "Workflow broker unavailable (%d)\n", broker_error);
        }
    }
    void *node = dlopen("libnode.so", RTLD_NOW | RTLD_LOCAL);
    NodeStart start = node ? (NodeStart)dlsym(node, "_ZN4node5StartEiPPc") : NULL;
    if (!start) {
        harmony_workflow_broker_close();
        return -2;
    }
    // Signed self/lab builds enable V8 JIT (the anonymous executable mappings
    // used by the signed ELF loader are available to the App). Store builds keep
    // the conservative --jitless launch until store-side policy is verified.
#ifdef MH_SELF_BUILD
    char *argv[] = {"node", "--expose-internals", entry, safe_mode ? "safe" : "normal", NULL};
    int code = start(4, argv);
#else
    char *argv[] = {"node", "--jitless", "--expose-internals", entry, safe_mode ? "safe" : "normal", NULL};
    int code = start(5, argv);
#endif
    harmony_workflow_broker_close();
    return code == 0 ? -3 : -4;
}

#ifdef MOBILE_HARNESS_EXPERIMENTAL_FORK
static pthread_mutex_t child_lock = PTHREAD_MUTEX_INITIALIZER;
static pid_t host_pid = -1;
#endif

static void *RunNative(void *unused) {
    (void)unused;
#ifdef MOBILE_HARNESS_EXPERIMENTAL_FORK
    const pid_t parent = getpid();
    pid_t child = fork();
    if (child == 0) {
        if (prctl(PR_SET_PDEATHSIG, SIGKILL, 0, 0, 0) < 0 || getppid() != parent) _exit(91);
        _exit(RunHost() == -3 ? 0 : 1);
    }
    if (child < 0) {
        atomic_store(&status, -2);
        return NULL;
    }
    pthread_mutex_lock(&child_lock);
    host_pid = child;
    atomic_store(&status, 2);
    pthread_mutex_unlock(&child_lock);
    OH_LOG_Print(LOG_APP, LOG_INFO, 0xD005, "DSHClient", "experimental Host UI=%{public}d Host=%{public}d",
                 parent, child);
    for (;;) {
        pthread_mutex_lock(&child_lock);
        int exit_state = 0;
        pid_t observed = waitpid(child, &exit_state, WNOHANG);
        if (observed == child || (observed < 0 && errno != EINTR)) {
            host_pid = -1;
            pthread_mutex_unlock(&child_lock);
            OH_LOG_Print(LOG_APP, LOG_INFO, 0xD005, "DSHClient", "experimental Host exited wait=%{public}d",
                         exit_state);
            atomic_store(&status, -3);
            break;
        }
        pthread_mutex_unlock(&child_lock);
        usleep(50000);
    }
#else
    atomic_store(&status, 2);
    atomic_store(&status, RunHost());
#endif
    return NULL;
}

napi_value StartNative(napi_env env, napi_callback_info info) {
    size_t count = 2;
    size_t length = 0;
    napi_value argv[2];
    napi_value result;
    int expected = 0;
#ifdef MOBILE_HARNESS_EXPERIMENTAL_FORK
    expected = atomic_load(&status);
#endif
    if (expected <= 0 && atomic_compare_exchange_strong(&status, &expected, 1)) {
        napi_get_cb_info(env, info, &count, argv, NULL, NULL);
        if (count != 2 || napi_get_value_bool(env, argv[1], &safe_mode) != napi_ok || napi_get_value_string_utf8(env, argv[0], directory, sizeof(directory), &length) != napi_ok ||
            length == 0 || length >= sizeof(directory) - 1) {
            atomic_store(&status, -1);
        } else {
            snprintf(entry, sizeof(entry), "%s/dsh-native-web.cjs", directory);
            pthread_t thread;
            pthread_attr_t attr;
            pthread_attr_init(&attr);
            pthread_attr_setstacksize(&attr, 32 * 1024 * 1024);
            int code = pthread_create(&thread, &attr, RunNative, NULL);
            pthread_attr_destroy(&attr);
            if (code == 0) pthread_detach(thread);
            else atomic_store(&status, -1);
        }
    }
    napi_create_int32(env, atomic_load(&status), &result);
    return result;
}

napi_value NativeStatus(napi_env env, napi_callback_info info) {
    (void)info;
    napi_value result;
    napi_create_int32(env, atomic_load(&status), &result);
    return result;
}

napi_value UsesHostProcess(napi_env env, napi_callback_info info) {
    (void)info;
    napi_value result;
#ifdef MOBILE_HARNESS_EXPERIMENTAL_FORK
    napi_get_boolean(env, true, &result);
#else
    napi_get_boolean(env, false, &result);
#endif
    return result;
}

napi_value StopNative(napi_env env, napi_callback_info info) {
    (void)info;
    bool stopped = false;
#ifdef MOBILE_HARNESS_EXPERIMENTAL_FORK
    pthread_mutex_lock(&child_lock);
    stopped = host_pid > 0 && kill(host_pid, SIGKILL) == 0;
    pthread_mutex_unlock(&child_lock);
#endif
    napi_value result;
    napi_get_boolean(env, stopped, &result);
    return result;
}

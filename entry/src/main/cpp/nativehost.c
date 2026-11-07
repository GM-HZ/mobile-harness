#include <napi/native_api.h>
#include <dlfcn.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>

static atomic_int status = 0;
static char entry[1024];
static char directory[900];
typedef int (*NodeStart)(int, char **);

static void *RunNative(void *unused) {
    (void)unused;
    void *node = dlopen("libnode.so", RTLD_NOW | RTLD_LOCAL);
    NodeStart start = node ? (NodeStart)dlsym(node, "_ZN4node5StartEiPPc") : NULL;
    if (!start) { atomic_store(&status, -2); return NULL; }
    char *argv[] = {"node", "--jitless", "--expose-internals", entry, NULL};
    setenv("HARMONY_NATIVE_WEB_ROOT", directory, 1);
    atomic_store(&status, 2);
    int code = start(4, argv);
    atomic_store(&status, code == 0 ? -3 : -4);
    return NULL;
}

napi_value StartNative(napi_env env, napi_callback_info info) {
    size_t count = 1;
    size_t length = 0;
    napi_value argv[1];
    napi_value result;
    int expected = 0;
    if (atomic_compare_exchange_strong(&status, &expected, 1)) {
        napi_get_cb_info(env, info, &count, argv, NULL, NULL);
        if (count != 1 || napi_get_value_string_utf8(env, argv[0], directory, sizeof(directory), &length) != napi_ok ||
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

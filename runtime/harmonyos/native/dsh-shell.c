#include <node_api.h>
#include <dlfcn.h>
#include <errno.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>

typedef int (*SpawnShell)(const char *, const char *, const char *, int *, int *, int *, char *, size_t);

static int string_arg(napi_env env, napi_value value, char *out, size_t capacity) {
    size_t expected, written;
    if (napi_get_value_string_utf8(env, value, NULL, 0, &expected) != napi_ok || expected == 0 || expected >= capacity)
        return 0;
    return napi_get_value_string_utf8(env, value, out, capacity, &written) == napi_ok &&
        expected == written && strlen(out) == written;
}

static void set_number(napi_env env, napi_value object, const char *name, int value) {
    napi_value result;
    napi_create_int32(env, value, &result);
    napi_set_named_property(env, object, name, result);
}

static napi_value launch(napi_env env, napi_callback_info info) {
    size_t argc = 3;
    napi_value argv[3];
    char directory[900], cwd[1024], command[32768];
    if (napi_get_cb_info(env, info, &argc, argv, NULL, NULL) != napi_ok || argc != 3 ||
        !string_arg(env, argv[0], directory, sizeof(directory)) || !string_arg(env, argv[1], cwd, sizeof(cwd)) ||
        !string_arg(env, argv[2], command, sizeof(command))) {
        napi_throw_type_error(env, NULL, "Expected bounded filesDir, cwd and Bash command");
        return NULL;
    }
    void *poc = dlopen("libpoc.so", RTLD_NOW | RTLD_NOLOAD);
    SpawnShell start = poc ? (SpawnShell)dlsym(poc, "harmony_spawn_shell") : NULL;
    if (!start) {
        if (poc) dlclose(poc);
        napi_throw_error(env, NULL, "PRoot launcher is unavailable");
        return NULL;
    }
    int out, err, status;
    char diagnostic[256] = "PRoot could not start";
    int pid = start(directory, cwd, command, &out, &err, &status, diagnostic, sizeof(diagnostic));
    dlclose(poc);
    if (pid < 0) {
        napi_throw_error(env, NULL, diagnostic);
        return NULL;
    }
    napi_value result;
    napi_create_object(env, &result);
    set_number(env, result, "pid", pid);
    set_number(env, result, "stdoutFd", out);
    set_number(env, result, "stderrFd", err);
    set_number(env, result, "statusFd", status);
    return result;
}

static napi_value poll_exit(napi_env env, napi_callback_info info) {
    size_t argc = 1;
    napi_value argv[1], result;
    int32_t pid;
    if (napi_get_cb_info(env, info, &argc, argv, NULL, NULL) != napi_ok || argc != 1 ||
        napi_get_value_int32(env, argv[0], &pid) != napi_ok || pid <= 0) {
        napi_throw_type_error(env, NULL, "Expected process ID");
        return NULL;
    }
    int status;
    pid_t observed = waitpid(pid, &status, WNOHANG);
    if (observed == 0 || (observed < 0 && errno == EINTR)) {
        napi_get_null(env, &result);
        return result;
    }
    if (observed < 0) {
        napi_throw_error(env, NULL, "Could not reap the PRoot process");
        return NULL;
    }
    napi_create_object(env, &result);
    set_number(env, result, "exitCode", WIFEXITED(status) ? WEXITSTATUS(status) : -1);
    set_number(env, result, "signal", WIFSIGNALED(status) ? WTERMSIG(status) : 0);
    return result;
}

NAPI_MODULE_INIT() {
    napi_property_descriptor properties[] = {
        {"launch", NULL, launch, NULL, NULL, NULL, napi_default, NULL},
        {"pollExit", NULL, poll_exit, NULL, NULL, NULL, napi_default, NULL},
    };
    napi_define_properties(env, exports, 2, properties);
    return exports;
}

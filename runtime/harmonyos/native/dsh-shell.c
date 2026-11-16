#include <node_api.h>
#include <dlfcn.h>
#include <errno.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>

typedef int (*SpawnPiped)(const char *, const char *, const char *, char *const *, int *, int *, int *, int *, char *, size_t);
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

static napi_value start_shell(napi_env env, napi_callback_info info, int streaming) {
    size_t argc = streaming ? 4 : 3;
    napi_value argv[4];
    char directory[900], cwd[1024], command[32768];
    if (napi_get_cb_info(env, info, &argc, argv, NULL, NULL) != napi_ok || argc != (streaming ? 4 : 3) ||
        !string_arg(env, argv[0], directory, sizeof(directory)) || !string_arg(env, argv[1], cwd, sizeof(cwd)) ||
        !string_arg(env, argv[2], command, sizeof(command))) {
        napi_throw_type_error(env, NULL, "Expected bounded filesDir, cwd and Bash command");
        return NULL;
    }
    char environment_data[32768], *environment[129];
    if (streaming) {
        uint32_t count;
        size_t used = 0;
        if (napi_get_array_length(env, argv[3], &count) != napi_ok || count >= 129) {
            napi_throw_type_error(env, NULL, "Expected at most 128 environment entries");
            return NULL;
        }
        for (uint32_t i = 0; i < count; ++i) {
            napi_value item;
            if (napi_get_element(env, argv[3], i, &item) != napi_ok ||
                !string_arg(env, item, environment_data + used, sizeof(environment_data) - used)) {
                napi_throw_type_error(env, NULL, "Invalid or oversized MCP environment");
                return NULL;
            }
            environment[i] = environment_data + used;
            used += strlen(environment[i]) + 1;
        }
        environment[count] = NULL;
    }
    void *poc = dlopen("libpoc.so", RTLD_NOW | RTLD_NOLOAD);
    int input = -1, out, err, status, pid = -1;
    char diagnostic[256] = "PRoot launcher is unavailable";
    if (poc && streaming) {
        SpawnPiped start = (SpawnPiped)dlsym(poc, "harmony_spawn_piped");
        if (start) pid = start(directory, cwd, command, environment, &input, &out, &err, &status, diagnostic, sizeof(diagnostic));
    } else if (poc) {
        SpawnShell start = (SpawnShell)dlsym(poc, "harmony_spawn_shell");
        if (start) pid = start(directory, cwd, command, &out, &err, &status, diagnostic, sizeof(diagnostic));
    }
    if (poc) dlclose(poc);
    if (pid < 0) {
        napi_throw_error(env, NULL, diagnostic);
        return NULL;
    }
    napi_value result;
    napi_create_object(env, &result);
    set_number(env, result, "pid", pid);
    if (streaming) set_number(env, result, "stdinFd", input);
    set_number(env, result, "stdoutFd", out);
    set_number(env, result, "stderrFd", err);
    set_number(env, result, "statusFd", status);
    return result;
}

static napi_value launch(napi_env env, napi_callback_info info) {
    return start_shell(env, info, 0);
}

static napi_value launch_piped(napi_env env, napi_callback_info info) {
    return start_shell(env, info, 1);
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
        {"launchPiped", NULL, launch_piped, NULL, NULL, NULL, napi_default, NULL},
        {"pollExit", NULL, poll_exit, NULL, NULL, NULL, napi_default, NULL},
    };
    napi_define_properties(env, exports, sizeof(properties) / sizeof(*properties), properties);
    return exports;
}

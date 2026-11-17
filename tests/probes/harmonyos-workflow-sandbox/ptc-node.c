#define _GNU_SOURCE
#include "ptc-file-filter.h"
#include <errno.h>
#include <fcntl.h>
#include <linux/openat2.h>
#include <node_api.h>
#include <sys/syscall.h>

static napi_value number(napi_env env, int value)
{
    napi_value output;
    napi_create_int32(env, value, &output);
    return output;
}

static napi_value confine(napi_env env, napi_callback_info info)
{
    (void)info;
    return number(env, ptc_install_file_filter(1, 1));
}

static napi_value direct_open(napi_env env, napi_callback_info info)
{
    (void)info;
    struct open_how how = {.flags = O_RDONLY};
    int fd = (int)syscall(SYS_openat2, AT_FDCWD, "../outside.txt", &how, sizeof(how));
    int error = fd < 0 ? errno : 0;
    if (fd >= 0) close(fd);
    return number(env, error);
}

static napi_value finish(napi_env env, napi_callback_info info)
{
    size_t count = 1, length;
    void *data;
    napi_value args[1];
    if (napi_get_cb_info(env, info, &count, args, NULL, NULL) != napi_ok || count != 1 ||
        napi_get_buffer_info(env, args[0], &data, &length) != napi_ok ||
        length != sizeof(struct WorkerReport)) _exit(96);
    _exit(write(CONTROL, data, length) == (ssize_t)length ? 0 : 97);
}

NAPI_MODULE_INIT()
{
    const napi_property_descriptor properties[] = {
        {"confine", NULL, confine, NULL, NULL, NULL, napi_default, NULL},
        {"directOpenat2", NULL, direct_open, NULL, NULL, NULL, napi_default, NULL},
        {"finish", NULL, finish, NULL, NULL, NULL, napi_default, NULL},
    };
    napi_define_properties(env, exports, sizeof(properties) / sizeof(properties[0]), properties);
    return exports;
}

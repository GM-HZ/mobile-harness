#include <node_api.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdlib.h>

extern uint8_t *dsh_search(const uint8_t *, size_t, const atomic_uchar *, size_t *);
extern void dsh_search_free(uint8_t *, size_t);

struct SearchWork {
    napi_async_work work;
    napi_deferred promise;
    napi_ref request_ref, cancel_ref;
    const uint8_t *request;
    size_t request_size;
    atomic_uchar *cancel;
    uint8_t *response;
    size_t response_size;
};

static void execute(napi_env env, void *data) {
    (void)env;
    struct SearchWork *job = data;
    job->response = dsh_search(job->request, job->request_size, job->cancel, &job->response_size);
}

static void release(napi_env env, struct SearchWork *job) {
    if (job->response) dsh_search_free(job->response, job->response_size);
    if (job->request_ref) napi_delete_reference(env, job->request_ref);
    if (job->cancel_ref) napi_delete_reference(env, job->cancel_ref);
    if (job->work) napi_delete_async_work(env, job->work);
    free(job);
}

static void complete(napi_env env, napi_status status, void *data) {
    struct SearchWork *job = data;
    napi_value result;
    if (status == napi_ok && job->response && napi_create_string_utf8(
            env, (const char *)job->response, job->response_size, &result) == napi_ok) {
        napi_resolve_deferred(env, job->promise, result);
    } else {
        napi_value message;
        napi_create_string_utf8(env, "Native search did not complete", NAPI_AUTO_LENGTH, &message);
        napi_create_error(env, NULL, message, &result);
        napi_reject_deferred(env, job->promise, result);
    }
    release(env, job);
}

static napi_value run(napi_env env, napi_callback_info info) {
    size_t argc = 2, cancel_size;
    napi_value args[2], promise, label;
    struct SearchWork *job = calloc(1, sizeof(*job));
    if (!job) {
        napi_throw_error(env, NULL, "Could not allocate search operation");
        return NULL;
    }
    if (napi_get_cb_info(env, info, &argc, args, NULL, NULL) != napi_ok || argc != 2 ||
        napi_get_buffer_info(env, args[0], (void **)&job->request, &job->request_size) != napi_ok ||
        napi_get_buffer_info(env, args[1], (void **)&job->cancel, &cancel_size) != napi_ok || cancel_size != 1) {
        free(job);
        napi_throw_type_error(env, NULL, "Invalid native search arguments");
        return NULL;
    }
    if (napi_create_reference(env, args[0], 1, &job->request_ref) != napi_ok ||
        napi_create_reference(env, args[1], 1, &job->cancel_ref) != napi_ok ||
        napi_create_promise(env, &job->promise, &promise) != napi_ok ||
        napi_create_string_utf8(env, "Workspace search", NAPI_AUTO_LENGTH, &label) != napi_ok ||
        napi_create_async_work(env, NULL, label, execute, complete, job, &job->work) != napi_ok ||
        napi_queue_async_work(env, job->work) != napi_ok) {
        release(env, job);
        napi_throw_error(env, NULL, "Could not schedule native search");
        return NULL;
    }
    return promise;
}

static napi_value cancel(napi_env env, napi_callback_info info) {
    size_t argc = 1, size;
    napi_value arg, result;
    atomic_uchar *flag;
    if (napi_get_cb_info(env, info, &argc, &arg, NULL, NULL) != napi_ok || argc != 1 ||
        napi_get_buffer_info(env, arg, (void **)&flag, &size) != napi_ok || size != 1) {
        napi_throw_type_error(env, NULL, "Invalid native search cancellation flag");
        return NULL;
    }
    atomic_store_explicit(flag, 1, memory_order_release);
    napi_get_undefined(env, &result);
    return result;
}

NAPI_MODULE_INIT() {
    const napi_property_descriptor properties[] = {
        {"run", NULL, run, NULL, NULL, NULL, napi_default, NULL},
        {"cancel", NULL, cancel, NULL, NULL, NULL, napi_default, NULL},
    };
    napi_define_properties(env, exports, sizeof(properties) / sizeof(properties[0]), properties);
    return exports;
}

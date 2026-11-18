#include <node_api.h>
#include <stdbool.h>

#ifdef MH_HARMONY_NODE
#include <dlfcn.h>
#endif

static napi_value initialize(napi_env env, napi_value exports)
{
    napi_value value;

#ifdef MH_HARMONY_NODE
    // HarmonyOS also has ArkTS N-API. Resolve the embedded Node implementation.
    void *const node = dlopen("libnode.so", RTLD_NOW | RTLD_NOLOAD);
    if (!node) return NULL;
    __typeof__(&napi_create_int32) create = dlsym(node, "napi_create_int32");
    __typeof__(&napi_set_named_property) set = dlsym(node, "napi_set_named_property");
    if (!create || !set) {
        dlclose(node);
        return NULL;
    }
#else
    __typeof__(&napi_create_int32) create = napi_create_int32;
    __typeof__(&napi_set_named_property) set = napi_set_named_property;
#endif
    const bool success = create(env, 42, &value) == napi_ok &&
                         set(env, exports, "value", value) == napi_ok;
#ifdef MH_HARMONY_NODE
    dlclose(node);
#endif
    return success ? exports : NULL;
}

NAPI_MODULE(runtime_addon, initialize)

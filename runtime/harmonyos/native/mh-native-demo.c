/* Tiny NAPI addon used to verify dlopen of a signed native extension overlay. */
#include <node_api.h>

static napi_value answer(napi_env env, napi_callback_info info)
{
	napi_value result;
	if (napi_create_int32(env, 42, &result) != napi_ok)
		return NULL;
	return result;
}

NAPI_MODULE_INIT()
{
	napi_value function;
	napi_create_function(env, "answer", NAPI_AUTO_LENGTH, answer, NULL, &function);
	napi_set_named_property(env, exports, "answer", function);
	return exports;
}

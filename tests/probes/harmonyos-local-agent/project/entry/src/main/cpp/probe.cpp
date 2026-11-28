#include <atomic>
#include <cerrno>
#include <climits>
#include <string>
#include <thread>
#include <utility>

#include <hilog/log.h>
#include <napi/native_api.h>
#include <unistd.h>

int llama_server(int argc, char **argv);
static std::atomic<int> state{0};

static napi_value integer(napi_env env, int value) {
    napi_value result;
    napi_create_int32(env, value, &result);
    return result;
}

static void run(std::string files_dir) {
    std::string model = files_dir + "/llama-lab.gguf";
    std::string log = files_dir + "/llama-lab.log";
    std::string arguments[] = {
        "llama-server", "--model", std::move(model),
        "--host", "127.0.0.1", "--port", "39765", "--alias", "mh-on-device",
        "--ctx-size", "4096", "--threads", "4", "--parallel", "1",
        "--reasoning", "off", "--temp", "0", "--predict", "512",
        "--jinja", "--no-webui", "--log-file", std::move(log)
    };
    char *argv[sizeof(arguments) / sizeof(*arguments) + 1] = {};
    for (size_t i = 0; i < sizeof(arguments) / sizeof(*arguments); ++i) {
        argv[i] = arguments[i].data();
    }
    const int result = llama_server(sizeof(arguments) / sizeof(*arguments), argv);
    state.store(result == 0 ? 2 : -result);
    OH_LOG_Print(LOG_APP, LOG_INFO, 0xD005, "MhLlamaProbe",
                 "Server exit: %{public}d", result);
}

static napi_value start(napi_env env, napi_callback_info info) {
    char files_dir[PATH_MAX];
    size_t count = 1, length = 0;
    napi_value args[1];
    if (napi_get_cb_info(env, info, &count, args, nullptr, nullptr) != napi_ok ||
        count != 1 ||
        napi_get_value_string_utf8(env, args[0], files_dir, sizeof(files_dir), &length) != napi_ok ||
        !length || length >= sizeof(files_dir) - 32) {
        return integer(env, -EINVAL);
    }
    std::string directory(files_dir, length);
    if (access((directory + "/llama-lab.gguf").c_str(), R_OK) != 0) {
        return integer(env, -errno);
    }
    int idle = 0;
    if (!state.compare_exchange_strong(idle, 1)) {
        return integer(env, idle);
    }
    try {
        std::thread(run, std::move(directory)).detach();
    } catch (...) {
        state.store(-EAGAIN);
        return integer(env, -EAGAIN);
    }
    return integer(env, 1);
}

static napi_value status(napi_env env, napi_callback_info info) {
    return integer(env, state.load());
}

static napi_value init(napi_env env, napi_value exports) {
    napi_property_descriptor methods[] = {
        {"start", nullptr, start, nullptr, nullptr, nullptr, napi_default, nullptr},
        {"status", nullptr, status, nullptr, nullptr, nullptr, napi_default, nullptr}
    };
    napi_define_properties(env, exports, sizeof(methods) / sizeof(*methods), methods);
    return exports;
}

static napi_module module = {1, 0, nullptr, init, "mhllamaprobe", nullptr, {0}};
__attribute__((constructor)) static void register_module(void) { napi_module_register(&module); }

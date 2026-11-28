#include "common.h"

#include <atomic>
#include <cerrno>
#include <cstring>
#include <mutex>
#include <string>
#include <sys/stat.h>
#include <thread>
#include <utility>

int llama_server_mobile(common_params &params, const std::atomic<bool> &stop, std::atomic<bool> &ready);

namespace {
std::mutex lifecycle;
std::atomic<bool> stop_requested{false};
std::atomic<bool> engine_ready{false};
std::atomic<int> state{0};

void serve(std::string path, std::string model_id, std::string api_key) {
    int result = -EIO;
    try {
        common_params params;
        params.model.path = std::move(path);
        params.model_alias.insert(std::move(model_id));
        params.api_keys.push_back(std::move(api_key));
        params.hostnames = {"127.0.0.1"};
        params.port = 39765;
        params.cors_origins.clear();
        params.cors_credentials = false;
        params.n_ctx = 16384;
        params.n_predict = 1024;
        params.n_parallel = 1;
        params.n_gpu_layers = 0;
        params.cpuparams.n_threads = 4;
        params.cpuparams_batch.n_threads = 4;
        params.enable_reasoning = 0;
        params.default_template_kwargs["enable_thinking"] = "false";
        params.sampling.temp = 0;
        params.sampling.user_sampling_config |= COMMON_PARAMS_SAMPLING_CONFIG_TEMP;
        params.cache_ram_mib = 0;
        params.cache_ram_explicit = true;
        params.ui = false;
        params.endpoint_slots = false;
        result = llama_server_mobile(params, stop_requested, engine_ready) == 0 ? 0 : -EIO;
    } catch (...) {
        // Never pass model data or the bearer token to the app log.
    }
    const std::lock_guard<std::mutex> lock(lifecycle);
    engine_ready = false;
    state = stop_requested ? 0 : result;
}
} // namespace

extern "C" int dshLocalInferenceStart(const char *path, const char *model_id, const char *api_key) {
    if (path[0] != '/' ||
        (std::strcmp(model_id, "lfm3-1.7b-q4") != 0 && std::strcmp(model_id, "qwen3.5-2b-q4") != 0)) {
        return -EINVAL;
    }
    const size_t key_size = std::strlen(api_key);
    if (key_size < 32 || key_size != std::strspn(api_key, "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")) {
        return -EINVAL;
    }
    struct stat model;
    if (stat(path, &model) != 0) return -errno;
    if (!S_ISREG(model.st_mode)) return -EINVAL;

    const std::lock_guard<std::mutex> lock(lifecycle);
    if (state > 0) return -EBUSY;
    stop_requested = false;
    state = 1;
    try {
        std::thread(serve, std::string(path), std::string(model_id), std::string(api_key)).detach();
    } catch (...) {
        state = -EAGAIN;
    }
    return state;
}

extern "C" int dshLocalInferenceStop() {
    const std::lock_guard<std::mutex> lock(lifecycle);
    stop_requested = true;
    state = state > 0 ? 2 : 0;
    return state;
}

extern "C" int dshLocalInferenceState() {
    const int current = state;
    return current == 1 && !engine_ready ? 3 : current;
}

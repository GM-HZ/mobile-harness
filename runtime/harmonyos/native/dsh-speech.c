#include <dlfcn.h>
#include <math.h>
#include <node_api.h>
#include <pthread.h>
#include <sherpa-onnx/c-api/c-api.h>
#include <stdlib.h>
#include <string.h>

/* The app loads both ArkTS and Node. Bind the N-API functions to the Node DSO. */
#define NODE_APIS(X) \
    X(napi_get_cb_info) X(napi_get_value_string_utf8) X(napi_get_value_double) \
    X(napi_throw_error) X(napi_create_external) X(napi_get_value_external) \
    X(napi_get_typedarray_info) X(napi_create_array) X(napi_create_string_utf8) \
    X(napi_set_element) X(napi_define_properties)
#define DECLARE(name) static __typeof__(&name) node_##name;
NODE_APIS(DECLARE)
static pthread_once_t bindings_once = PTHREAD_ONCE_INIT;
static int bound;

static void bind_node(void)
{
    void *node = dlopen("libnode.so", RTLD_NOW | RTLD_NOLOAD);
    if (!node) return;
    bound = 1;
#define BIND(name) \
    node_##name = (__typeof__(node_##name))dlsym(node, #name); \
    if (!node_##name) bound = 0;
    NODE_APIS(BIND)
    dlclose(node);
}

#define RATE 16000
#define WINDOW 512
#define MAX_SAMPLES (RATE * 120)

struct Speech {
    SherpaOnnxOfflineRecognizerConfig config;
    const SherpaOnnxOfflineRecognizer *recognizer;
    const SherpaOnnxVoiceActivityDetector *vad;
    char model[1024];
    char tokens[1024];
    char vad_model[1024];
};

static napi_value error(napi_env env, const char *message)
{
    node_napi_throw_error(env, NULL, message);
    return NULL;
}

static int read_string(napi_env env, napi_value value, char *data, size_t capacity)
{
    size_t length;
    return node_napi_get_value_string_utf8(env, value, NULL, 0, &length) == napi_ok &&
           length > 0 && length < capacity &&
           node_napi_get_value_string_utf8(env, value, data, capacity, &length) == napi_ok &&
           strlen(data) == length;
}

static void dispose(napi_env env, void *data, void *hint)
{
    (void)env;
    (void)hint;
    struct Speech *speech = data;
    if (speech->vad) SherpaOnnxDestroyVoiceActivityDetector(speech->vad);
    if (speech->recognizer) SherpaOnnxDestroyOfflineRecognizer(speech->recognizer);
    free(speech);
}

static napi_value open_speech(napi_env env, napi_callback_info info)
{
    napi_value args[8], handle;
    size_t argc = 8;
    double config[5];
    if (node_napi_get_cb_info(env, info, &argc, args, NULL, NULL) != napi_ok || argc != 8)
        return error(env, "Invalid SenseVoice settings");
    for (size_t i = 0; i < 5; ++i) {
        if (node_napi_get_value_double(env, args[i + 3], &config[i]) != napi_ok || !isfinite(config[i]))
            return error(env, "Invalid SenseVoice numeric setting");
    }
    if (config[0] < 1 || config[0] > 32 || config[1] < 0 || config[1] > 1 ||
        config[2] <= 0 || config[2] > 120 || config[3] < 0 || config[3] > 120 ||
        config[4] <= 0 || config[4] > 120)
        return error(env, "SenseVoice settings are out of range");
    struct Speech *speech = calloc(1, sizeof(*speech));
    if (!speech) return error(env, "Cannot allocate SenseVoice runtime");
    if (!read_string(env, args[0], speech->model, sizeof(speech->model)) ||
        !read_string(env, args[1], speech->tokens, sizeof(speech->tokens)) ||
        !read_string(env, args[2], speech->vad_model, sizeof(speech->vad_model))) {
        dispose(env, speech, NULL);
        return error(env, "Invalid SenseVoice model path");
    }
    speech->config = (SherpaOnnxOfflineRecognizerConfig){
        .feat_config = { .sample_rate = RATE, .feature_dim = 80 },
        .model_config = {
            .sense_voice = { .model = speech->model, .language = "auto", .use_itn = 1 },
            .tokens = speech->tokens, .num_threads = (int)config[0], .provider = "cpu",
        },
        .decoding_method = "greedy_search",
    };
    const SherpaOnnxVadModelConfig vad_config = {
        .silero_vad = {
            .model = speech->vad_model, .window_size = WINDOW, .threshold = config[1],
            .min_silence_duration = config[2], .min_speech_duration = config[3],
            .max_speech_duration = config[4],
        },
        .sample_rate = RATE, .num_threads = (int)config[0], .provider = "cpu",
    };
    speech->recognizer = SherpaOnnxCreateOfflineRecognizer(&speech->config);
    speech->vad = SherpaOnnxCreateVoiceActivityDetector(&vad_config, config[4] + config[2] + 1);
    if (!speech->recognizer || !speech->vad ||
        node_napi_create_external(env, speech, dispose, NULL, &handle) != napi_ok) {
        dispose(env, speech, NULL);
        return error(env, "Cannot initialize SenseVoice models");
    }
    return handle;
}

static int decode_segment(napi_env env, struct Speech *speech, napi_value parts,
                          uint32_t index, const float *samples, int32_t count)
{
    const SherpaOnnxOfflineStream *stream = SherpaOnnxCreateOfflineStream(speech->recognizer);
    if (!stream) return 0;
    SherpaOnnxAcceptWaveformOffline(stream, RATE, samples, count);
    SherpaOnnxDecodeOfflineStream(speech->recognizer, stream);
    const SherpaOnnxOfflineRecognizerResult *result = SherpaOnnxGetOfflineStreamResult(stream);
    napi_value text;
    const int ok = result && result->text &&
        node_napi_create_string_utf8(env, result->text, NAPI_AUTO_LENGTH, &text) == napi_ok &&
        node_napi_set_element(env, parts, index, text) == napi_ok;
    if (result) SherpaOnnxDestroyOfflineRecognizerResult(result);
    SherpaOnnxDestroyOfflineStream(stream);
    return ok;
}

static napi_value transcribe(napi_env env, napi_callback_info info)
{
    napi_value args[4], parts;
    size_t argc = 4, count;
    char language[16];
    double onset;
    napi_typedarray_type type;
    void *handle, *pcm;
    if (node_napi_get_cb_info(env, info, &argc, args, NULL, NULL) != napi_ok || argc != 4 ||
        node_napi_get_value_external(env, args[0], &handle) != napi_ok || !handle ||
        node_napi_get_typedarray_info(env, args[1], &type, &count, &pcm, NULL, NULL) != napi_ok ||
        type != napi_float32_array || !pcm || !count || count > MAX_SAMPLES ||
        !read_string(env, args[2], language, sizeof(language)) ||
        node_napi_get_value_double(env, args[3], &onset) != napi_ok ||
        !isfinite(onset) || onset < 0 || onset > MAX_SAMPLES ||
        node_napi_create_array(env, &parts) != napi_ok)
        return error(env, "Invalid SenseVoice audio or language");

    struct Speech *speech = handle;
    const float *samples = pcm;
    SherpaOnnxOfflineRecognizerConfig config = speech->config;
    config.model_config.sense_voice.language = language;
    SherpaOnnxOfflineRecognizerSetConfig(speech->recognizer, &config);
    SherpaOnnxVoiceActivityDetectorReset(speech->vad);

    uint32_t index = 0;
    for (size_t offset = 0;;) {
        if (offset == count) SherpaOnnxVoiceActivityDetectorFlush(speech->vad);
        else SherpaOnnxVoiceActivityDetectorAcceptWaveform(speech->vad, samples + offset,
                count - offset < WINDOW ? (int32_t)(count - offset) : WINDOW);
        while (!SherpaOnnxVoiceActivityDetectorEmpty(speech->vad)) {
            const SherpaOnnxSpeechSegment *segment = SherpaOnnxVoiceActivityDetectorFront(speech->vad);
            if (!segment) return error(env, "Cannot read SenseVoice speech segment");
            const float *audio = segment->samples;
            int32_t length = segment->n;
            /* Preserve the start that Silero can omit before the first trigger. */
            if (index == 0 && onset >= 1 && segment->start > 0 && (size_t)segment->start <= count &&
                length > 0 && (size_t)length <= count - (size_t)segment->start) {
                const int32_t prefix = segment->start < (int32_t)onset ? segment->start : (int32_t)onset;
                audio = samples + segment->start - prefix;
                length += prefix;
            }
            const int ok = length > 0 && decode_segment(env, speech, parts, index++, audio, length);
            SherpaOnnxDestroySpeechSegment(segment);
            SherpaOnnxVoiceActivityDetectorPop(speech->vad);
            if (!ok) return error(env, "SenseVoice could not decode the speech segment");
        }
        if (offset == count) break;
        offset += count - offset < WINDOW ? count - offset : WINDOW;
    }
    return parts;
}

NAPI_MODULE_INIT()
{
    pthread_once(&bindings_once, bind_node);
    if (!bound) return NULL;
    const napi_property_descriptor functions[] = {
        { .utf8name = "open", .method = open_speech, .attributes = napi_default },
        { .utf8name = "transcribe", .method = transcribe, .attributes = napi_default },
    };
    if (node_napi_define_properties(env, exports, sizeof(functions) / sizeof(functions[0]), functions) != napi_ok)
        return NULL;
    return exports;
}

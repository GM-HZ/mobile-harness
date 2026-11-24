#include <node_api.h>
#include <multimedia/image_framework/image/image_packer_native.h>
#include <native_color_space_manager/native_color_space_manager.h>
#include <math.h>
#include <dlfcn.h>
#include <pthread.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

// Image Kit also loads the Ark runtime. Resolve Node-API from the embedded
// Node library so its environment and values are handled by the same runtime.
#define NODE_API_FUNCTIONS(X) \
    X(napi_create_async_work) \
    X(napi_create_error) \
    X(napi_create_object) \
    X(napi_create_promise) \
    X(napi_create_reference) \
    X(napi_create_string_utf8) \
    X(napi_create_uint32) \
    X(napi_define_properties) \
    X(napi_delete_async_work) \
    X(napi_delete_reference) \
    X(napi_get_buffer_info) \
    X(napi_get_cb_info) \
    X(napi_get_value_bool) \
    X(napi_get_value_int32) \
    X(napi_get_value_uint32) \
    X(napi_queue_async_work) \
    X(napi_reject_deferred) \
    X(napi_resolve_deferred) \
    X(napi_set_named_property) \
    X(napi_throw_error) \
    X(napi_throw_type_error)

#define DECLARE(name) static __typeof__(name) *node_##name;
NODE_API_FUNCTIONS(DECLARE)
#undef DECLARE

static pthread_once_t node_api_once = PTHREAD_ONCE_INIT;
static bool node_api_ready = false;
static void load_node_api(void) {
    void *node = dlopen("libnode.so", RTLD_NOW | RTLD_NOLOAD);
    if (!node) return;
#define LOAD(name) node_##name = (__typeof__(name) *)dlsym(node, #name); if (!node_##name) return;
    NODE_API_FUNCTIONS(LOAD)
#undef LOAD
    node_api_ready = true;
}

enum Operation { METADATA, DECODE, JPEG, WEBP };
struct ImageWork {
    napi_async_work work;
    napi_deferred promise;
    napi_ref input;
    uint8_t *bytes;
    size_t length;
    enum Operation operation;
    uint32_t target_width, target_height, width, height, frames, quality;
    uint16_t orientation;
    bool auto_orient;
    int32_t output_fd;
    const char *format;
    const char *error;
};

static const char *get_format(Image_MimeType mime) {
    const char *formats[] = {"png", "jpeg", "webp", "gif"};
    for (size_t i = 0; i < sizeof(formats) / sizeof(formats[0]); i++) {
        size_t length = strlen(formats[i]);
        if (mime.data && mime.size == 6 + length && !memcmp(mime.data, "image/", 6) &&
            !memcmp(mime.data + 6, formats[i], length)) return formats[i];
    }
    return NULL;
}

static bool read_source(struct ImageWork *job, OH_ImageSourceNative *source) {
    OH_ImageSource_Info *info = NULL;
    if (OH_ImageSourceInfo_Create(&info) != IMAGE_SUCCESS) return false;
    Image_MimeType mime = {0};
    bool ok = OH_ImageSourceNative_GetImageInfo(source, 0, info) == IMAGE_SUCCESS &&
        OH_ImageSourceInfo_GetWidth(info, &job->width) == IMAGE_SUCCESS &&
        OH_ImageSourceInfo_GetHeight(info, &job->height) == IMAGE_SUCCESS &&
        OH_ImageSourceInfo_GetMimeType(info, &mime) == IMAGE_SUCCESS;
    if (ok) job->format = get_format(mime);
    OH_ImageSourceInfo_Release(info);
    if (!ok || !job->format || !job->width || !job->height ||
        OH_ImageSourceNative_GetFrameCount(source, &job->frames) != IMAGE_SUCCESS || !job->frames) return false;
    Image_String orientation = {(char *)OHOS_IMAGE_PROPERTY_ORIENTATION, strlen(OHOS_IMAGE_PROPERTY_ORIENTATION)};
    uint16_t value;
    if (OH_ImageSourceNative_GetImagePropertyShort(source, &orientation, &value) == IMAGE_SUCCESS &&
        value >= 1 && value <= 8) job->orientation = value;
    return true;
}

static bool transform(struct ImageWork *job, OH_PixelmapNative *pixelmap) {
    if (job->auto_orient && job->orientation >= 2) {
        static const float rotation[] = {0, 0, 0, 180, 0, 90, 90, 270, 270};
        uint16_t orientation = job->orientation;
        if (rotation[orientation] && OH_PixelmapNative_Rotate(pixelmap, rotation[orientation]) != IMAGE_SUCCESS)
            return false;
        bool horizontal = orientation == 2 || orientation == 5 || orientation == 7;
        bool vertical = orientation == 4;
        if ((horizontal || vertical) && OH_PixelmapNative_Flip(pixelmap, horizontal, vertical) != IMAGE_SUCCESS)
            return false;
        if (orientation >= 5) {
            uint32_t width = job->width;
            job->width = job->height;
            job->height = width;
        }
    }
    double scale = 1;
    if (job->target_width) scale = fmin(scale, (double)job->target_width / job->width);
    if (job->target_height) scale = fmin(scale, (double)job->target_height / job->height);
    if (scale < 1 && OH_PixelmapNative_Scale(pixelmap, (float)scale, (float)scale) != IMAGE_SUCCESS)
        return false;
    OH_Pixelmap_ImageInfo *info = NULL;
    if (OH_PixelmapImageInfo_Create(&info) != IMAGE_SUCCESS) return false;
    bool ok = OH_PixelmapNative_GetImageInfo(pixelmap, info) == IMAGE_SUCCESS &&
        OH_PixelmapImageInfo_GetWidth(info, &job->width) == IMAGE_SUCCESS &&
        OH_PixelmapImageInfo_GetHeight(info, &job->height) == IMAGE_SUCCESS;
    OH_PixelmapImageInfo_Release(info);
    return ok;
}

static bool encode(const struct ImageWork *job, OH_PixelmapNative *pixelmap) {
    OH_ImagePackerNative *packer = NULL;
    OH_PackingOptions *options = NULL;
    char *type = job->operation == JPEG ? "image/jpeg" : "image/webp";
    Image_MimeType mime = {type, strlen(type)};
    bool ok = OH_ImagePackerNative_Create(&packer) == IMAGE_SUCCESS &&
        OH_PackingOptions_Create(&options) == IMAGE_SUCCESS &&
        OH_PackingOptions_SetMimeType(options, &mime) == IMAGE_SUCCESS &&
        OH_PackingOptions_SetQuality(options, job->quality) == IMAGE_SUCCESS &&
        OH_PackingOptions_SetNeedsPackProperties(options, false) == IMAGE_SUCCESS &&
        OH_ImagePackerNative_PackToFileFromPixelmap(packer, options, pixelmap, job->output_fd) == IMAGE_SUCCESS;
    if (options) OH_PackingOptions_Release(options);
    if (packer) OH_ImagePackerNative_Release(packer);
    return ok;
}

static void execute(napi_env env, void *data) {
    (void)env;
    struct ImageWork *job = data;
    OH_ImageSourceNative *source = NULL;
    OH_DecodingOptions *options = NULL;
    OH_PixelmapNative *pixels = NULL;
    job->error = "Invalid image header";
    if (OH_ImageSourceNative_CreateFromDataWithUserBuffer(job->bytes, job->length, &source) != IMAGE_SUCCESS ||
        !read_source(job, source)) goto cleanup;
    job->error = NULL;
    if (job->operation == METADATA) goto cleanup;

    job->error = "Image decoding failed";
    if ((uint64_t)job->width * job->height > 64000000 ||
        OH_DecodingOptions_Create(&options) != IMAGE_SUCCESS ||
        OH_DecodingOptions_SetPixelFormat(options, PIXEL_FORMAT_RGBA_8888) != IMAGE_SUCCESS ||
        OH_DecodingOptions_SetDesiredDynamicRange(options, IMAGE_DYNAMIC_RANGE_SDR) != IMAGE_SUCCESS ||
        OH_DecodingOptions_SetDesiredColorSpace(options, SRGB) != IMAGE_SUCCESS ||
        OH_ImageSourceNative_CreatePixelmap(source, options, &pixels) != IMAGE_SUCCESS) goto cleanup;
    job->error = NULL;
    if (job->operation == DECODE) goto cleanup;

    if (!transform(job, pixels) || !encode(job, pixels)) job->error = "Image encoding failed";
cleanup:
    if (pixels) OH_PixelmapNative_Release(pixels);
    if (options) OH_DecodingOptions_Release(options);
    if (source) OH_ImageSourceNative_Release(source);
}

static void set_number(napi_env env, napi_value result, const char *name, uint32_t number) {
    napi_value value;
    node_napi_create_uint32(env, number, &value);
    node_napi_set_named_property(env, result, name, value);
}

static void complete(napi_env env, napi_status status, void *data) {
    struct ImageWork *job = data;
    napi_value result, message;
    if (status != napi_ok || job->error) {
        node_napi_create_string_utf8(env, job->error ? job->error : "Image operation cancelled", NAPI_AUTO_LENGTH, &message);
        node_napi_create_error(env, NULL, message, &result);
        node_napi_reject_deferred(env, job->promise, result);
    } else {
        node_napi_create_object(env, &result);
        set_number(env, result, "width", job->width);
        set_number(env, result, "height", job->height);
        set_number(env, result, "pages", job->frames);
        if (job->orientation) set_number(env, result, "orientation", job->orientation);
        node_napi_create_string_utf8(env, job->format, NAPI_AUTO_LENGTH, &message);
        node_napi_set_named_property(env, result, "format", message);
        node_napi_resolve_deferred(env, job->promise, result);
    }
    node_napi_delete_reference(env, job->input);
    node_napi_delete_async_work(env, job->work);
    free(job);
}

static napi_value run_image(napi_env env, napi_callback_info info) {
    size_t argc = 7;
    napi_value args[7], promise, label;
    uint32_t operation;
    struct ImageWork *job = calloc(1, sizeof(*job));
    if (!job) {
        node_napi_throw_error(env, NULL, "Could not allocate image operation");
        return NULL;
    }
    if (node_napi_get_cb_info(env, info, &argc, args, NULL, NULL) != napi_ok || argc != 7 ||
        node_napi_get_buffer_info(env, args[0], (void **)&job->bytes, &job->length) != napi_ok || !job->length ||
        node_napi_get_value_uint32(env, args[1], &operation) != napi_ok || operation > WEBP ||
        node_napi_get_value_uint32(env, args[2], &job->target_width) != napi_ok ||
        node_napi_get_value_uint32(env, args[3], &job->target_height) != napi_ok ||
        node_napi_get_value_bool(env, args[4], &job->auto_orient) != napi_ok ||
        node_napi_get_value_uint32(env, args[5], &job->quality) != napi_ok || job->quality > 100 ||
        node_napi_get_value_int32(env, args[6], &job->output_fd) != napi_ok ||
        (operation >= JPEG && job->output_fd < 0)) {
        free(job);
        node_napi_throw_type_error(env, NULL, "Invalid native image arguments");
        return NULL;
    }
    job->operation = operation;
    if (node_napi_create_reference(env, args[0], 1, &job->input) != napi_ok ||
        node_napi_create_promise(env, &job->promise, &promise) != napi_ok ||
        node_napi_create_string_utf8(env, "HarmonyOS image operation", NAPI_AUTO_LENGTH, &label) != napi_ok ||
        node_napi_create_async_work(env, NULL, label, execute, complete, job, &job->work) != napi_ok ||
        node_napi_queue_async_work(env, job->work) != napi_ok) {
        if (job->work) node_napi_delete_async_work(env, job->work);
        if (job->input) node_napi_delete_reference(env, job->input);
        free(job);
        node_napi_throw_error(env, NULL, "Could not schedule native image operation");
        return NULL;
    }
    return promise;
}

NAPI_MODULE_INIT() {
    pthread_once(&node_api_once, load_node_api);
    if (!node_api_ready) return exports;
    napi_property_descriptor property = {"runImage", NULL, run_image, NULL, NULL, NULL, napi_default, NULL};
    node_napi_define_properties(env, exports, 1, &property);
    return exports;
}

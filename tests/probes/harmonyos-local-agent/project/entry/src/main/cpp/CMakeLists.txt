cmake_minimum_required(VERSION 3.5.0)
project(mh_llama_probe CXX)
set(CMAKE_CXX_STANDARD 17)
set(LLAMA_BUILD "$ENV{MH_LLAMA_BUILD}")
if(NOT EXISTS "${LLAMA_BUILD}/tools/server/libllama-server-impl.a")
    message(FATAL_ERROR "Set MH_LLAMA_BUILD to the static ARM64 HarmonyOS llama.cpp build directory")
endif()
add_library(mhllamaprobe SHARED probe.cpp)
target_link_libraries(mhllamaprobe PRIVATE
    "${LLAMA_BUILD}/tools/server/libllama-server-impl.a"
    "${LLAMA_BUILD}/tools/server/libserver-context.a"
    "${LLAMA_BUILD}/common/libllama-common.a"
    "${LLAMA_BUILD}/common/libllama-common-base.a"
    "${LLAMA_BUILD}/tools/mtmd/libmtmd.a"
    "${LLAMA_BUILD}/src/libllama.a"
    "${LLAMA_BUILD}/ggml/src/libggml.a"
    "${LLAMA_BUILD}/ggml/src/libggml-cpu.a"
    "${LLAMA_BUILD}/ggml/src/libggml-base.a"
    "${LLAMA_BUILD}/vendor/hash/libvendor-hash.a"
    "${LLAMA_BUILD}/ui/apps/chat/libllama-ui.a"
    "${LLAMA_BUILD}/vendor/cpp-httplib/libcpp-httplib.a"
    libace_napi.z.so libhilog_ndk.z.so dl m)

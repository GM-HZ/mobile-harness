target_compile_definitions(poc PRIVATE MOBILE_HARNESS_LOCAL_INFERENCE=1)
target_sources(poc PRIVATE dsh-local-inference.cpp)
set_property(TARGET poc PROPERTY CXX_STANDARD 17)
target_include_directories(poc PRIVATE
    "${MH_LLAMA_SOURCE}/common"
    "${MH_LLAMA_SOURCE}/include"
    "${MH_LLAMA_SOURCE}/ggml/include"
    "${MH_LLAMA_SOURCE}/vendor")
target_link_libraries(poc PUBLIC
    "${MH_LLAMA_BUILD}/tools/server/libllama-server-impl.a"
    "${MH_LLAMA_BUILD}/tools/server/libserver-context.a"
    "${MH_LLAMA_BUILD}/common/libllama-common.a"
    "${MH_LLAMA_BUILD}/common/libllama-common-base.a"
    "${MH_LLAMA_BUILD}/tools/mtmd/libmtmd.a"
    "${MH_LLAMA_BUILD}/src/libllama.a"
    "${MH_LLAMA_BUILD}/ggml/src/libggml.a"
    "${MH_LLAMA_BUILD}/ggml/src/libggml-cpu.a"
    "${MH_LLAMA_BUILD}/ggml/src/libggml-base.a"
    "${MH_LLAMA_BUILD}/vendor/hash/libvendor-hash.a"
    "${MH_LLAMA_BUILD}/ui/apps/chat/libllama-ui.a"
    "${MH_LLAMA_BUILD}/vendor/cpp-httplib/libcpp-httplib.a"
    pthread m)
set_property(TARGET poc APPEND_STRING PROPERTY LINK_FLAGS " -Wl,--exclude-libs,ALL")

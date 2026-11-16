cmake_minimum_required(VERSION 3.5.0)
project(sayact_node_poc)
add_library(poc SHARED poc.c nativehost.c workflow-broker.c)
target_link_libraries(poc PUBLIC libace_napi.z.so libhilog_ndk.z.so)

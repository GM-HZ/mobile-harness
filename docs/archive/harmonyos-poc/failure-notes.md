# 已观察的失败

> 历史实验记录。命令与结论适用于当时的环境和版本。原始日志与二进制保存在本机。现行结论见[研究索引](../../research/harmonyos-runtime.md)。

| 实验 | 现象 | 证据与处置 |
| --- | --- | --- |
| 首次 ArkTS 构建 | `CopyOptions.Local` 不存在 | 修正枚举使用后编译通过；不涉及 Node |
| 未附 Node 的负向测试 | `dlopen` 找不到库 | 模拟器原生日志；证明错误路径可观察 |
| 真机无签名 HAP | code 9568320，无签名 | HDC 虽退出 0，但输出安装失败；配置真实调试签名后安装成功 |
| Node 24.2 首次真机启动 | SIGSYS，调用号 425 | 手机 hilog；可选 io_uring_setup 被 seccomp 拒绝 |
| Node 24.2 实验性回退 | Node ready、文件/worker/HTTP 通过 | 进程级 SIGSYS 处理仅用于探路；目标运行时改在 libuv 源码禁用 OHOS 上的可选 io_uring，随后需去掉信号处理重测 |
| Node 24.2 内置 fetch | WASM 不存在，未处理拒绝后 exit 导致 SIGABRT | 保留崩溃日志；加诊断处理后得到实际异常，兼容性仍失败 |
| Node 24.14 本机交叉编译 1 | Mac host 工具误编 Linux libuv 源码 | `build-node24-native.log`；增加受环境变量控制的 host 平台构建适配 |
| Node 24.14 本机交叉编译 2 | Ada 需要 ranges 算法，SDK 默认未暴露 | `build-node24-host-adapter.log`；最小复现确认 `_LIBCPP_ENABLE_EXPERIMENTAL` 后可编译，不改 Ada 算法 |
| Node 24.14 本机交叉编译 3 | ICU host 工具 dynamic_cast 与 -fno-rtti 冲突 | `build-node24-ranges.log`；仅 Mac host C++ 包装器追加 -frtti，目标鸿蒙编译器不变 |

全部日志位于 `.build/harmony-node/`。新版运行时尚未完成，不能将旧版探路结果计作目标 P0/P1 通过。DSH 未运行。

## 后续构建记录

- V8 的 C++20 `make_unique_for_overwrite` 缺失：增加受标准特性宏控制的等价数组分配分支，见独立 patch。没有改动 DSH。
- OHOS clang 15 在 zlib ARM CRC32 intrinsic 上内部崩溃：与固定 DSHM 参考脚本记录一致；仅关闭可选 ARMv8 CRC 优化，保留通用 CRC，设备用 gzip 往返检验。
- Mac host 工具链接：过滤 GNU archive group 标志，并重建为 Apple ld 可读的普通 host 静态库；host Abseil 时区代码补链接 CoreFoundation。这些只影响 Mac 构建工具，目标仍为 OHOS 编译器生成的 ELF。
- ICU 阶段的一次构建主动中断（退出 130），仅为将并行度从 2 调整为 4；没有把中断当作构建成功。
- 新版 N-API 桥接成功编译，但该次仍使用旧 staged libnode，未安装，不能作为新版运行时设备验收。桥接已经去掉 SIGSYS 全局处理，并将 stdout/stderr 写入应用沙箱诊断文件；等待新版 libuv 构建后实测。

### 2026-11-07 SDK C++ ranges 缺项

- `.build/harmony-node/build-node24-clang20-resource.log` 最终失败：`std::ranges::elements_view` / `keys_view` 未提供。不是仍在编译或已构建成功。
- 新独立补丁 `node24-ohos-builtin-ids-vector.patch` 仅在 `__OHOS__` 下返回已复制的 builtin ID vector，保留 map 遍历顺序并在读取锁存活时复制；对应 V8 转换复用原有 vector 分支。其他平台仍用原 ranges 实现。还需要设备验证 builtin 枚举/模块加载。
- 新构建日志 `.build/harmony-node/build-node24-builtin-vector.log`；构建进行中，未完成 P0。

- builtin vector 补丁后构建退出 2；7 个 Node API 对象已生成，进一步遇到 `views::values` 与 `views::split` 缺项。新增 `node24-ohos-options-ranges-fallback.patch`：option implication 改等价迭代器循环，OHOS inspector/tracing 的逗号分割使用 string_view vector，保留空输入与结尾分隔符语义。新日志 `.build/harmony-node/build-node24-options-ranges.log`，完整构建未通过。

### OHOS C++ ABI 头文件纠正

- `build-node24-options-ranges.log` 构建最终退出 2：共享库曾生成，但 embedtest 链接发现大量 `std::__1` 未解析符号。SDK `libc++_shared.so` 实际导出 `std::__n1`；因此该库不能用于设备加载，不能称作构建完成。
- 根因是 C++ 包装器误选通用 `llvm/include/c++/v1`。SDK clang 自身 `-E -v` 使用 `llvm/include/libcxx-ohos/include/c++/v1`，其 `__config_site` 为 `__n1`。现已纠正，保留之前 target 对象目录 `.build/harmony-node/obj-target-generic-cxx-headers-*` 并重编所有 target 对象，避免 ABI 混合。
- 新构建日志 `.build/harmony-node/build-node24-ohos-libcxx.log`。另以独立 patch 纠正 macOS 交叉构建时 shared library 后缀：目标 OHOS 使用 `.so`，不继承宿主 `.dylib` 名称。实际 ELF 头和依赖仍需在生成后验证。

### OHOS 专用头文件重编结果

- `build-node24-ohos-libcxx.log` 本轮 `make` 最终退出 0，包含 embedtest 链接；不是在 macOS 运行目标程序。
- `llvm-readelf` 确认 AArch64 ELF DYN、SONAME `libnode.so`、依赖 `libc++_shared.so` 与 `libc.so`。strip/self-sign/stage 退出 0，目标签名库 SHA-256 `05f5edecd7a94f3aae6a7c1a921c9d333353c0a8c0aa04103b9e395509e5c33e`。
- 这只是构建/制品检查通过，尚未设备 P0；自编译 HAP 正在单独打包，优先模拟器测试，不切走真机的 DSHM 展示。

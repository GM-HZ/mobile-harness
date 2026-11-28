# AGENTS.md — 原生运行时（`runtime/harmonyos/native`）

C/CMake 层：PRoot 桥、shell、workflow、PTC、exec shim、N-API 扩展。ABI/签名/平台敏感，改起来最贵。

## 规则

1. **绑定表是编译期数据**：新增 guest 路径绑定要进 `poc.c` 的 `packaged[]`（按 stage 限制），
   或由 `guest-tools.inc`/`guest-libs.inc` 生成；不要在 shell 脚本里临时 mount。
2. **自建开关**：`MH_SELF_BUILD` 的代码必须是编译期宏；store 构建不得包含 shim/loader/overlay；
   改后跑 `store_build_check.py` 与 `variant_check.py`。
3. **不要 debug 产物入库**：临时日志、探针、调试符号在提交前删除；错误信息要可诊断但不泄露凭据。
4. **内存与 fd**：新增 fd/映射必须成对释放；exec shim/loader 改动要在真机（签名构建）验证，
   模拟器 unsigned 通过不构成证据。
5. **ABI**：N-API 扩展必须用打包 Node 的 headers/ABI；`.node` 缺 `libnode.so` 依赖要显式处理。
6. **AppGallery**：CMake 禁用 Workflow 和 PTC 编译入口，Image Kit 和原生搜索桥按 Host 的 Node-API ABI 装配。
7. **证据**：真机 G3 `device_lab` 或对应 `--probe`，记录到 `docs/evidence/device-lab/`。
8. **Host 启动与子进程**：嵌入式 Node 在正常、安全、冷启动和热启动均使用 `--jitless`。Workflow、PTC 和 shell 子进程在分配 IPC 描述符后用 `child-descriptors.h` 清理继承描述符。Mate 60 的应用沙箱会拦截 `close_range`。
9. **端侧推理实验**：仅启用 `HARMONY_SELF_BUILD=1 HARMONY_LOCAL_INFERENCE=1` 时将锁定的 llama.cpp 作为静态库链接到 `libpoc.so`。启动和停止均在原生线程完成，只绑定 `127.0.0.1:39765`，每次启动以应用生成的 bearer token 认证。仅在绑定成功且模型加载完成后报告就绪。状态码为 0 已停止、1 就绪、2 正在停止、3 正在加载，负值表示失败。

## 检查清单

- [ ] `HARMONY_SELF_BUILD=1 ./build.sh --package` 通过；
- [ ] 真机 G3 相关 probe 通过（不是只跑模拟器）；
- [ ] store/self shape 断言未被破坏。

# 鸿蒙 PTC 的 TypeScript 解析

RC.3 的通用 PTC 在启动执行进程前调用 Node `stripTypeScriptTypes`。普通的 TypeScript 擦除使用 Node 内置的 Amaro。鸿蒙 Host 的 Node 24.14.1 使用 `--jitless`，调用时返回 `ERR_WEBASSEMBLY_NOT_SUPPORTED`。[Node TypeScript 文档](https://nodejs.org/docs/latest-v24.x/api/typescript.html)

独立探针从 Node 子模块锁定的 Amaro 1.1.7 提取 WASM，用 Binaryen 132.0.0 在构建机转为 JavaScript，保留原有输入输出包装。WASM 浮点饱和转整数指令先由 `wasm-opt` 降级，再运行 `wasm2js`。直接翻译该模块时，Binaryen 在两个 64 位指令处生成了无法通过自身验证的中间表示。生成代码的 64 位导入参数通过两个 32 位值还原成 Amaro 预期的 BigInt。 [Binaryen wasm2js](https://github.com/WebAssembly/binaryen#wasm2js)

探针用同版本带 WASM 的 Amaro 生成基准，再在鸿蒙原生 Node worker 启用 seccomp 后对照 JavaScript 输出和错误。长脚本实测暴露了缓冲区扩容后仍读取旧视图的问题，包装改为按缓冲区身份刷新。最终在 API 26 Phone 模拟器上，80 个用例全部匹配，其中 69 个成功擦除、11 个按原版规则拒绝。加载解析器和基准数据用时 302 ms，执行对照用时 219 ms。带类型标注和 `await` 的固定脚本在受限进程中返回 `42`。 [探针记录](../evidence/emulator-ptc-amaro-2026-11-17.json)

本轮使用独立 HAP。通用 PTC 仍需接入正式 Host 的运行入口与生命周期，并验证工作区读写授权。模拟器的 Landlock 调用返回 `ENOSYS`，已有 Workflow 的无文件访问策略只能支撑纯计算和明确注册的 Host 回调。 [原生隔离证据](../evidence/emulator-workflow-sandbox-2026-11-17.json)

## 复现

在仓库根目录准备锁定的 Node 子模块和 DevEco SDK。

```sh
mkdir -p .build/amaro-probe
npm --registry=https://registry.npmjs.org pack binaryen@132.0.0 --pack-destination .build/amaro-probe
python3 tests/probes/harmonyos-ptc/generate-amaro.py \
  .build/amaro-probe/binaryen-132.0.0.tgz .build/amaro-probe/portable
/Applications/DevEco-Studio.app/Contents/tools/node/bin/node \
  tests/probes/harmonyos-ptc/compare-strip.cjs \
  vendor/repos/node/deps/amaro/dist/index.js .build/amaro-probe/portable/reference.json
HARMONY_AMARO_PROBE_DIR="$PWD/.build/amaro-probe/portable" \
  HARMONY_INPUTS_DIR=/absolute/path/to/harmonyos-inputs \
  tests/probes/harmonyos-workflow-sandbox/build.sh
hdc -t <loopback-target> install -r .build/stage/harmonyos-workflow-sandbox/entry/build/default/outputs/default/entry-default-unsigned.hap
hdc -t <loopback-target> shell aa start -a EntryAbility -b org.mobileharness.workflowsandbox
hdc -t <loopback-target> shell hilog -x | rg WorkflowNodeProbe
```

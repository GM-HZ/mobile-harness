# AGENTS.md — Host 运行时 overlay（`packages/dsh-host`）

本目录是 L1：在 Host 进程里加载的启动器/桥/模块级 patch。**它是最后手段，不是第一选择。**

## 规则

1. **先找上游 seam**：plugin/bundle/provider/slot 能解决就不写 overlay；其次 `patches/` 包级补丁；
   最后才是本目录的运行时 patch。
2. **每个 patch 函数都有锚点**：新增/修改 `replacePinned` 类改写，必须同时在
   `adaptation/anchors.json` 加锚点、`scripts/adaptation/host_contracts.py` 加行为合同、
   `adaptation/convergence.json` 给出迁移目标与优先级；否则不合并。
3. **不要新增无名全局**：`globalThis.__x` 只能用于跨模块/注入点，且必须在该文件注释说明
   所有者、生命周期、消费方；新业务状态用显式参数或 service。
4. **启动顺序敏感**：`dsh-native-web.cjs` 在 dsh-client 启动前设置 `globalThis` 注入；
   不要在 dsh-client 已加载后依赖懒初始化。
5. **安全**：不打印/落盘凭据；不把 shell 命令拼接成未转义字符串（用 `quoteShellArgument`）；
   改动 `__harmonyGh`/账号桥时同时检查 `docs/architecture/seams/forge-upstream-seam.md`。
6. **真机与模拟器差异**：签名构建走 packaged spawn 路径（`__harmonyPackagedShell`/`__harmonyProotSpawn`），
   不要回退到 streaming guest-shell 路径；由 G1 `host-regressions` 守卫。
7. **每改一个文件跑**：`node --check <file>`、`python3 gates/run.py --tier G1`。

## 快速检查清单

- [ ] 新增 patch 有锚点 + 合同 + convergence 行；
- [ ] 没有新增未登记 manifest 的文件（inventory 重生成）；
- [ ] G1 全绿（host-syntax/anchors/contracts/regressions）；
- [ ] 涉及真机行为时补 G2/G3 用例与证据。

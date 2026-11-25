# AGENTS.md — 打包/装配（`runtime/harmonyos/packaging` 与 `scripts/build`）

这一层决定 HAP 里装什么、上游怎么装配、补丁什么时候应用。**可重复性优先。**

## 规则

1. **输入必须 pin**：新增外部输入 → `docs/build-inputs.sha256`（或 lock 文件）记录 hash；
   构建脚本必须校验，不允许隐式下载未 pin 内容。
2. **stage 顺序敏感**：`stage_assets → dsh layer（patch 应用）→ guest extras（库/扩展）→
   native shell → hvigor`；改动顺序要同步 `stage-harmonyos.py` 与文档。
3. **补丁只在装配期应用**：`harmonyos_dsh.py` 在 `npm ci` 后按 `patches/series.json` 应用并校验 marker；
   cache key 包含补丁 hash；不要恢复"运行时字符串替换"来替代。
4. **变体**：`HARMONY_SELF_BUILD`、`HARMONY_GUEST_LIB_GROUPS`、signing profile 的语义在
   `variants/*.json` 定义；新增开关先加变体与断言。
5. **体积/许可证**：overlay 库受 `variants/*.json` 的 maxBytes 限制；新增库要更新 NOTICE/LICENSE。
6. **可诊断**：装配日志写 `.build/batch-*/`；失败信息要指出文件/哈希/步骤。
7. **包内签名工具**：`guest-tools-lock.json` 中的 `installAs` 生成校验清单，CLI 和动态依赖随同组的 HAP 签名。更新附加层后要核对覆盖安装会重新解包。

## 检查清单

- [ ] `HARMONY_UNSIGNED=1 ./build.sh --package` 与 self 构建都通过；
- [ ] `store_build_check.py`、`variant_check.py` 通过；
- [ ] 新增/修改输入已更新 hash 与 inventory。

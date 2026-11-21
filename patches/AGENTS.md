# AGENTS.md — 上游包级补丁（`patches/`）

## 规则

1. **只补 npm 包**：路径相对于 `node_modules`（`-p1`）；上游源码 fork 不接受，优先上游 seam。
2. **每条补丁三件套**：`series.json` 行（marker/removed）+ `TARGETS.md` 行 + `targets.json` 同步；
   `patch_rehearsal.py` 必须应用到 pin 的 tarball。
3. **锚点进 anchors.json**：补丁替换的运行时锚点必须登记；bump 排练会检查。
4. **构建只应用一次**：`harmonyos_dsh.py` 按序应用并校验 marker；cache key 含补丁 hash；
   不要在运行时再改同一处。
5. **可回滚**：一个小补丁只做一件事；不要夹带无关格式改动。
6. **验证**：`python3 scripts/adaptation/patch_rehearsal.py` + 真实构建 + 对应 G2/G3。

## 检查清单

- [ ] series/TARGETS/targets.json/anchors 四方一致；
- [ ] rehearsal 通过；
- [ ] 装配后的 layer 含 marker（`anchors.py` 检查）。

# AGENTS.md — HarmonyOS 兼容层（`runtime/harmonyos/compat`）

这些模块是"上游能力在手机上无法原样运行"时的功能适配，不是上游源码的 fork。

## 规则

1. **先判定 seam**：上游是否真的没有 provider/slot/config 注入点？在
   `docs/architecture/seams/` 写判断（参考 forge/liveshare/speech）。
2. **登记三件套**：`adaptation/compat.json` 行 + `docs/architecture/compat-layer.md` 小节 +
   至少一个 gate id；G1 `compat-inventory` 会强制。
3. **消费者真实存在**：`consumers` 必须指向真实文件且在文件中被引用；不要登记死模块。
4. **决策必须写**：`keep-compat` / `upstream-seam-candidate` / `migrate-patch` / `converged`；
   候选面要写 seamEvidence。
5. **行为合同**：纯逻辑（forge 命令守卫、package registry provenance 等）进
   `scripts/adaptation/compat_contracts.py`；设备相关进 G2/G3。
6. **不引入新依赖**：compat 里只用 Host/guest 已有能力；新增 npm 包要走 `patches/` 与 lock。
7. **退出条件**：上游出现 seam 时按 `convergence.json` 迁移，迁移后改决策为 `converged`。

## 检查清单

- [ ] compat.json / compat-layer.md / seam doc 三处一致；
- [ ] G1 compat-inventory + compat-contracts 通过；
- [ ] 有对应 G2/G3 用例（能 fixture 的用 loopback fixture）。

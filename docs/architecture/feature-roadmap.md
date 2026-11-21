# 能力矩阵与新增功能的落点

本文件描述**当前能力状态**与"新功能该加在哪里"。状态随实现变化时在同一提交更新。

## 1. 能力矩阵

| 能力 | 状态 | 说明 / 证据 |
| --- | --- | --- |
| 签名 ELF 加载（静态/动态） | ✅ | `mh-exec`、动态 ELF、透明 exec；真机 vs 模拟器证据 |
| 透明 exec（`./tool`） | ✅ | LD_PRELOAD shim + packed spawn；真机 G3 exec |
| 运行时下载静态/动态工具 | ✅ | busybox/jq 等；`docs/evidence/` |
| 常用动态库覆盖 | ✅ | `patches/`? 不，`docs/guest-tools-lock.json` libraries + `HARMONY_GUEST_LIB_GROUPS` |
| 构建期签名原生扩展（dlopen） | ✅ | `extensions[]` overlay；node 扩展 dlopen 实测 |
| 运行时任意未签名 `.so` dlopen | ❌ | 只有构建期签名；需用户态 dlopen 加载器（大工程） |
| Forge（真实账号/GitHub） | ✅ | 真实私有 PR 验收；launcher 走 packaged spawn |
| LiveShare（relay/浏览器） | 🔶 | 本地/中继 fixture 通过；真机与公网 Relay 未验 |
| 语音输入（SenseVoice） | 🔶 | 设备路径适配中；`emulator-voice-input` |
| Office 预览/转换 | 🔶 | compat worker；`emulator-office*` |
| 包管理（pnpm/插件） | 🔶 | pnpm 桥 + fetch shim；`emulator-plugin-*` |
| PTY / 终端 | ⏸ 延期 | 平台无 `/dev/ptmx`；不作为当前目标 |
| GUI/手机操控、容器/systemd/dbus | ⏸ 范围外 | 平台边界 |
| Node JIT | ⏸ 当前 jitless | 构建默认 `--jitless`；可另评估 |
| 真机自动化门禁 | 🔶 | device_lab 协议就绪；需解锁/在线，脚本化调度待接 CI |
| CI runner 实跑 | 🔶 | 4 个 workflow 已定义；本地等价验证完成，未在 runner 实跑 |

## 2. 新增功能的落点（按类型）

### A. 增加一个签名库/扩展
1. `docs/guest-tools-lock.json`：`libraries[]` 或 `extensions[]`（group/base/archive/sha256/files）；
2. `python3 scripts/adaptation/inventory.py`；G4 `variant_check` 会检查体积预算；
3. 真机/模拟器用 `tests/smoke/mate60-proot-exec.py --probe native-overlay` 或对应 G2 用例验证。

### B. 增加一个上游包级补丁
1. `patches/<name>.patch`（git-style diff，node_modules 相对路径）；
2. `patches/series.json`（含 marker/removed）、`patches/TARGETS.md` 行；
3. `python3 scripts/adaptation/patch_rehearsal.py`；`patch_targets.py` 重生成；
4. 若替换运行时改写，更新 `adaptation/anchors.json` + `convergence.json`，删除 host 改写。

### C. 新增/修改 host overlay（`packages/dsh-host`）
1. 先确认不能走上游 seam / pnpm patch；
2. 若必须运行时改写：在 `dsh-native-web.cjs` 加 patch 函数，同时在 `anchors.json` 加锚点、
   `host_contracts.py` 加行为合同、`convergence.json` 给出迁移目标；
3. 加 G1 守卫（参考 `host_regressions.py`）；涉及真机行为的加 G2/G3 用例。

### D. 增加 compat 模块（`runtime/harmonyos/compat`）
1. 先写 seam 判断（上游是否真的没有 provider/slot）；
2. `adaptation/compat.json` 行（consumers/upstream/gates/decision/priority）；
3. `docs/architecture/compat-layer.md` 对应小节；G1 `compat_check` 会强制；
4. 至少一个 G2/G3 行为门禁；能写成 fixture 的写 fixture（loopback-only）。

### E. 增加门禁/用例
1. `gates/registry.json`（tier/command/requires/timeout）；
2. 证据写 `docs/evidence/<area>/`；需要设备用 `device_lab` 协议；
3. 新用例先在本机跑通，再纳入 nightly 子集；flake 用 `--retries`。

### F. 上游 bundle/plugin 能力
优先把上游 bundle 挂进 mobile profile，而不是在 host overlay 里重写；参考 forge
（`patches/forge-github-guest-runner.patch` + `__harmonyPackagedShell`）。

## 3. 待办优先级

| 优先级 | 事项 | 落点 |
| --- | --- | --- |
| P0 | 全量锚点扫描（host patch 全覆盖） | `scripts/adaptation/anchors.py` + bump |
| P0 | pinned PRoot 供应链（源码/构建脚本/版本） | `docs/build-inputs.sha256` + 新 build 脚本 |
| P1 | CI 真跑（PR/nightly/release） | `.github/workflows/*` + self-hosted runner |
| P1 | 真机门禁调度（解锁检测、异步队列） | `device_lab.py` + gate-device |
| P1 | 运行时任意 dlopen（若产品需要） | 新 loader 项目，不属于当前框架 |
| P2 | Liveshare/语音/Office 真机验收 | G2/G3 用例 |
| P2 | JIT 评估（Node 构建变体） | 构建/变体矩阵 |

## 4. 判定规则

- 新能力如果没有 gate、没有证据、没有 manifest/compat 登记：**视为未完成**；
- 能通过上游 seam 解决时，不允许新增运行时 patch；
- 任何"只在模拟器能跑"的东西，必须明确写出真机风险与验证计划。

# 能力矩阵与新增功能的落点

> **当前阶段：功能锁定（feature freeze），目标"第一可用版本"。**
> 本文件保留为能力现状与未来扩展的参考；冻结期间不新增能力，只修 bug/稳定性/体验/性能。
> 解锁新功能必须先更新 `docs/work/` 的阶段说明并经确认。

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
| LSP（代码智能） | 🔶 | 默认 opt-in（PluginManager 启用）；payload 在 optional 层 |
| 语音输入（SenseVoice） | 🔶 | 设备路径适配中；`emulator-voice-input` |
| Office 预览/转换 | 🔶 | compat worker；`emulator-office*` |
| 包管理（pnpm/插件） | 🔶 | pnpm 桥 + fetch shim；`emulator-plugin-*` |
| PTY / 终端 | ⏸ 延期 | 平台无 `/dev/ptmx`；不作为当前目标 |
| GUI/手机操控、容器/systemd/dbus | ⏸ 范围外 | 平台边界 |
| Node JIT | ⏸ 当前 jitless | 构建默认 `--jitless`；可另评估 |
| 后台常驻（HarmonyOS 长时任务） | ✅ | dataTransfer + running lock + cancel 重试；真机后台 35 分钟/锁屏通过；通知停止 action 待点击验证 |
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

## 3. 动态 dlopen 待办（独立项目，当前不支持）

运行时任意未签名 `.so` 的 dlopen 仍是 ❌。要做成需要用户态共享库加载器；按以下顺序拆项：

| ID | 事项 | 验收 |
| --- | --- | --- |
| D1 | `LD_PRELOAD` 拦截 `dlopen/dlsym/dlerror/dlclose`，未签名文件转交用户态 loader | 简单 `.so` 可 dlopen，签名文件仍走系统路径 |
| D2 | ELF 映射与重定位（PT_LOAD/RELATIVE/GLOB_DAT/JUMP_SLOT…） | 无外部依赖的 PIE `.so` 可加载并调用函数 |
| D3 | 符号解析（dlsym 宿主动态表）与 DT_NEEDED 依赖（签名库直映，未签名递归） | `.so` 依赖签名库/未签名库混合可用 |
| D4 | TLS、`DT_INIT/INIT_ARRAY` 构造器、析构 | 带构造器/TLS 的库可加载 |
| D5 | Python C 扩展（wheel） | `import` 一个 C 扩展模块成功 |
| D6 | Node `.node` addon（`process.dlopen` 路径） | 简单 N-API 扩展可 require |
| D7 | ABI/版本检查与错误诊断（缺符号、ABI 不匹配） | 错误可定位，不崩溃进程 |
| D8 | 安全门禁：仅 self/lab 构建启用，store 关闭 | `store_build_check` 断言、G4 |
| D9 | G2/G3 证据（模拟器 + 真机） | loader 用例进 nightly/device lab |
| D10 | 文档与回滚（支持边界、已知限制） | framework/README 更新 |

当前进度：①exec（main executable）已实现；②动态可执行文件依赖库仅覆盖签名 overlay；
③dlopen loader 未开始。

## 4. 插件支持策略与稳定性待办

- **P1** 插件支持策略文档：支持纯 JS/Cordis、bundle；不支持运行时原生 `.so`/需编译/PTY/桌面能力；
- **P1** 崩溃安全：坏插件导致 Host 退出后，下次启动自动进入安全模式，并提供"禁用最近插件"的恢复路径
  （现有 `BootRecovery` 已能自动安全模式，需补 UI 与 profile 回滚）；
- **P0/P1** 插件门禁：`nightly-plugin-git-update` 已加入 nightly（本地 PASS）；
  插件回滚（last-known-good snapshot + 恢复页按钮）已实现，UI 点击需解锁后的手工/自动化验证；
  市场/公开图用例需要模型 key，暂不纳入；
- **P2** 原生插件走构建期 `extensions[]` 签名 overlay（不承诺运行时任意 dlopen）；
- **P2** 安全模型：插件拥有 App 权限，需明示来源/信任与审核策略。

## 5. 待办优先级

| 优先级 | 事项 | 落点 |
| --- | --- | --- |
| P0 | ~~全量锚点扫描（host patch 全覆盖）~~ 已完成：44 literal 全映射/校验，15 ambiguous 仅存在性 | `anchors.full.json` + `anchor_scan.py` + bump |
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

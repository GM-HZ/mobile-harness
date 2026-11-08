# Mobile Harness 长期工程结构设计

2026-11-08，提案待评审。基线为 `main@ae44ac2` 和已验收的 `v0.4.24-bench`。

## 目标

把 Mobile Harness 做成以 DSH 为核心的单仓工程。鸿蒙首发拆清原生 UI、DSH Host、插件组装、设备运行时与构建输入。内置和后续安装的插件继续走 DSH 机制。原生恢复入口必须能在 Host 不可用时使用，Host 崩溃时 UI 仍存活作为独立的真机验收项。安卓、云端与远端控制沿用这些边界。[Host、插件与恢复体系](2026-11-08-host-plugin-recovery.md)

## 上游对照

- DSH 将应用入口放在 `apps/`，将 Host、SDK、会话、工具等按能力组织在 `packages/`，原生支持单独维护。Mobile Harness 复用 DSH 的会话、Agent 循环、工具和 bundle/profile，自己维护端上集成与设备边界。 [DSH 固定提交的目录](https://github.com/deepseek-ai/deepseek-harness/tree/fcc0ad462172522aaf5c93a7b2e01f6b9f0b0159) · [工作区清单](https://github.com/deepseek-ai/deepseek-harness/blob/fcc0ad462172522aaf5c93a7b2e01f6b9f0b0159/pnpm-workspace.yaml)
- dsh-go 将 Flutter 应用与 `runtime/` 下的运行时打包、桥接、锁和测试分开，`sdk/` 与配套服务也有各自的所有者。借鉴其分层与按 ABI 打包。dsh-go 本身只作为结构和体验对照，项目主体使用 AGPL-3.0，`sdk/` 和 `examples/` 有独立 MIT 声明，未来若实际引入代码再确认适用许可证和集成方式。 [dsh-go 固定提交的结构](https://github.com/ccch1mneyyy/dsh-Go/tree/3a91fab9e80d2a92be071a74b8b208214d7e6277) · [架构说明](https://github.com/ccch1mneyyy/dsh-Go/blob/3a91fab9e80d2a92be071a74b8b208214d7e6277/docs/architecture.md) · [许可说明](https://github.com/ccch1mneyyy/dsh-Go/blob/3a91fab9e80d2a92be071a74b8b208214d7e6277/README.md#许可证与致谢)

## 目标目录

```text
mobile-harness/
  apps/
    harmonyos/                 DevEco 工程、原生入口与恢复页、ArkWeb、HAP 装配
  packages/
    dsh-host/                  DSH 入口、宿主与平台适配契约
    bundles/                   选中的 DSH profile 和随包能力组合
    plugins/                   本项目维护的 DSH 插件，例如未来的 Phone Use
  runtime/
    harmonyos/
      control/                 Host 启动、监测和恢复控制的设备实现
      native/                  OHOS Node 加载、N-API、命令桥与子进程管理
      compat/                  文件、进程、图片、插件安装等鸿蒙适配
      capabilities/            Phone Use 等平台执行端，按实际能力加入
      packaging/               按 API/ABI 生成运行层、构建配方及映射表
  vendor/
    repos/                     Git submodule，仅含上游源码检出
    patches/                   逐组件维护的有序补丁
    components.json            选中组件、构建配方、许可证与补丁入口
    artifacts.lock.json        上游发行归档与系统工具链的版本、校验和
  scripts/
    vendor/                    初始化、校验、构建上游组件与记录 pin
    build/                     从构建输入到 HAP 的统一入口
  tests/
    contract/                  宿主与平台契约，权限、取消、退出码和错误
    smoke/                     模拟器与真机的包内端到端验证
    bench/                     首次启动、强停重启及资源消耗
  docs/                        架构、提案、开发规范、版本和证据
  .build/                      源码构建副本、下载缓存、平台暂存与制品，Git 忽略
```

- `apps/harmonyos` 拥有原生首屏、前台与应用生命周期、恢复入口、签名及 ArkWeb 回环鉴权。恢复界面依赖平台控制接口。聊天与日常插件管理可沿用 DSH UI。DevEco 工程自身的 `AppScope/`、`entry/` 和 `hvigor/` 一起移动。
- `packages/dsh-host` 拥有 DSH 装配及选中的 bundle/profile。平台差异通过少量已使用的入口注入，例如数据根、命令执行和兼容组件。优先使用上游扩展点。先保留当前 CJS 入口和行为，后续独立迁移对固定 DSH 模块源码的加载钩子。需要补丁时按上游版本和预期匹配数量校验，在构建阶段失败并报告。
- `packages/bundles` 使用 DSH 的 bundle/profile 组合基础服务、随包可选插件与安全模式。`packages/plugins` 只放本项目维护的插件代码。上游 DSH 插件跟随 DSH 的 gitlink，独立源码插件分别用 submodule 管理。随包、激活和设备授权由各自阶段决定。
- `runtime/harmonyos` 拥有 Host 控制与设备能力实现。将当前 `poc.c` 内的探针、Node 启动与 PRoot 工具执行拆开，把兼容代码从 HAP 的 `rawfile` 源目录移到明确所有者。按需 PRoot 继续只服务已选工具。应用包内的库名、数据目录和运行时资源名按兼容契约交付。进程边界在普通签名 Phone 上单独验证。
- 跨端接口跟着实际第二个消费者出现。远端阶段再引入 `packages/task-protocol` 和 `services/remote-runner`，先明确设备绑定、任务版本、审批、取消、恢复及执行结果不确定时的重试语义。到安卓阶段再引入 `apps/android` 和 `runtime/android`。这些目录随实现进入仓库。

## 依赖与构建

### 源码通过 Git submodule 锁定

| 源码组件 | 首轮来源及消费方式 |
| --- | --- |
| DSH | `deepseek-ai/deepseek-harness@fcc0ad462172522aaf5c93a7b2e01f6b9f0b0159`。从对应工作区和锁文件构建现有 Host、Web 与已选插件的生产依赖闭包 |
| Node.js | `nodejs/node@d89bb1b482fa09245c4f2cbb3b5b6a70bea6deaf`（v24.14.1）。迁入已用 OHOS 交叉编译配方和补丁，生成目标 ABI 的共享库 |
| PRoot | 已记录基线 `termux/proot@60485d2646c1e09105099772da4a20deda8d020d`。从 0.4.24 制品反查完整补丁序列，包含 Termony 的 OHOS 补丁、预加载和后续兼容修复，并核对 talloc 2.4.3 的来源 |
| DSHM fetch 垫片 | `sol5766/dshm@1cb0db693ea5121f0dab0208b1144b4c1b8ee2c0`。现有垫片与本机锁定的来源文件 SHA-256 一致。按清单提取所需文件和 MIT 许可证 |
| 其他直接源码 | 凡构建实际读取的 Termony 补丁源、talloc 源码和随包独立插件，核对仓库与完整 commit 后纳入。安装包发布后由用户添加的插件继续走 DSH 原生管理流程。需要长期维护的上游改动进入可访问的 fork |

`.gitmodules` 管理路径和仓库，父仓库的 gitlink 是 commit 的唯一版本来源。`components.json` 管理构建行为及选择范围。编译前校验子模块已初始化、工作树干净、HEAD 与 gitlink 一致且补丁可应用。发布前检查依赖提交的远端可达性，先推组件提交再推父仓库。更新按组件分开提交，升级 DSH 时先跑兼容测试，再上设备。

### 发行归档与工具链

直接参与构建的 Git 源码统一使用 submodule。npm 和 ohpm 传递依赖仍通过原生锁文件管理。现有 Alpine APK、已发布的 pnpm 归档、Sharp 原生附件等发行输入用版本、来源和完整性摘要固定。DevEco SDK 与编译器记录版本、目标 API/ABI 及可取得的校验信息。这些输入是构建清单中的显式分类。

### 构建流

```text
固定 gitlink + 原生锁文件 + 构建工具链
    → .build/vendor/ 中准备上游源码、应用补丁、编译
    → 组装选中的 Node、DSH、工具和插件运行层
    → .build/stage/harmonyos/<abi>/ 生成 DevEco 打包工程
    → hvigor 构建 HAP，输出组件来源与产物校验清单
```

保留根 `./build.sh` 作为入口，调到分阶段脚本。默认由暂存工程完成构建和 DevEco 调试，生成内容随源码更新重新同步。应用交付包只带选中的运行产物和随包许可证。签名配置从本机注入。生成清单包含父仓库 commit、子模块 commit、补丁与依赖摘要、工具链、目标设备架构和 HAP SHA-256。允许复用校验通过的缓存。

## 迁移顺序和验收

| 步骤 | 变更 | 通过条件 |
| --- | --- | --- |
| 1. 找齐基线输入 | 从 0.4.24 的构建清单追溯 Node、DSH、PRoot、两个原生附属库和工具包。核对补丁顺序及产物来源 | 每项都有明确的可获取输入或被记录为阻塞。上游候选版本与手机实测制品的绑定有证据 |
| 2. 固定依赖并复建 | 添加 submodule，建立输入锁和构建暂存区。保留旧目录作为当前装配入口直至新流水线通过 | 独立克隆、初始化子模块、按文档准备 SDK 后，可从固定输入生成 API 26 ARM64 HAP。构建路径独立于 Downloads 下的历史 PoC |
| 3. 搬迁工程与拆边界 | 先移动 DevEco 工程并更新构建路径，再分提交拆分 Host、原生桥与兼容层。复用现有 bundle/profile，保持已签名调试包身份及数据布局。并行验证原生恢复入口与 Phone 进程边界 | 覆盖安装后旧会话和设置可读，现有功能保持行为等价。分别记录重开可恢复和杀掉 Host 后 UI 当场仍可操作的结果 |
| 4. 验证插件管线并发版 | 用一个随包 submodule 插件和一个运行期插件验证 DSH 安装、隔离、激活、回滚，固化设备回归 | 在模拟器和 Mate 60 验证构建制品、鉴权、旧会话续接、工具及故障恢复，按同口径记录启动时间。Phone Use 随第一条能力链路单独验收 |

建议每一步独立提交。在设备回归通过后再落新版本标签。测试密钥和签名通过本机配置提供。基线的 GitHub 直连、系统 PTY、账号授权与图像理解仍按各自的实测范围记录。 [0.4.24 真机证据](../evidence/mate60-core-0.4.23-0.4.24.json) · [现有回归矩阵](../workspace-validation.md) · [现有构建输入摘要](../build-inputs.sha256)

## 首轮最大的验证项

现有 `build.sh` 调用 ohpm 与 hvigor 并消费已放到 DevEco 工程的二进制和资源。Node 与 PRoot 的部分来源依赖外层 PoC 的 `.build`，四个已提交 PRoot 补丁不足以证明整个链路可从干净检出复建。先解决输入来源，再用一次全新检出证明流水线可复现。另一项先决验证是在目标 Phone 上确认 Host 退出后 UI 仍可恢复。 [当前构建入口](../../build.sh) · [PRoot 历史来源](../archive/harmonyos-poc/proot-emulator-validation.md) · [进程验证方案](2026-11-08-host-plugin-recovery.md#鸿蒙-phone-上的进程验证)

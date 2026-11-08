# Mate 60 的 Shell 限制、DevEco 执行路径与可行突破方向

> 历史实验记录。命令与结论适用于当时的环境和版本。原始日志与二进制保存在本机。现行结论见[研究索引](../../research/harmonyos-runtime.md)。

调研日期：2026-11-07（Asia/Shanghai）。这里将用户所说的“devecho”按 DevEco Studio 理解，也核对了 DevEco Code 与鸿蒙电脑版 DevEco 的区别。

后续补充：开源项目专项调研发现了 HapInstaller 的 Phone HAP 进程内 HDC 动态库与无线调试/Shell 调用实现，详见 [开源项目调研](open-source-phone-shell-survey.md)。这为本机 HDC 实验提供了更直接的复用基础；本机 Mate 60 自连仍未实测，不改变下述普通 App 身份的失败记录。

## 结论

有可继续推进的路线。本轮已经在 **Mate 60 的普通 Debug HAP 应用进程里**，用自编译 Node v24.14.1 直接启动 `/system/bin/toybox echo`，得到预期输出和退出码 0；同一应用启动 `/system/bin/sh` 返回 EACCES，打开 `/dev/ptmx` 也返回 EACCES。

因此，不能用“鸿蒙手机所有 spawn 都被禁止”概括本次结果。更准确的结论是：**当前普通应用不能取得通用 Shell/PTY，但受限系统工具的无 Shell 执行链存在。** 官方 AbilityKit 的子进程能力查询和 POSIX/Node 的个别系统程序启动不是同一接口、同一授权对象。

对于独立手机 Agent，优先采用“直调系统工具 + 进程内文件/网络/脚本能力”的可替换工具插件。若目标必须包含完整交互 Shell，当前没有查到普通 Phone 应用可通过一个公开权限开关获得它的依据；另有值得单独验证的“本机 HDC 调试代理”实验，但尚未证明手机能够授权连接自己的 hdcd，也不能把这个实验当作普通沙箱能力。

## 1. 证据口径和基线

| 证据等级 | 本报告如何使用 |
| --- | --- |
| 本次真机实测 | 当前 Mate 60 / Phone / API 26 的实际应用身份、返回值、日志与制品绑定 |
| 官方文档、当前本地 SDK | 说明公开支持范围和接口契约，不能代替真机试验 |
| 精确 DSHM 制品源码、开发者问题记录 | 解释调用链和既有失败；不外推为所有鸿蒙设备结论 |
| 推断、待验证方案 | 明确标注，不宣称已经突破或已经支持上架 |

环境：Mate 60，系统标识 OpenHarmony-7.0.0.111，API 26，arm64-v8a；DevEco Studio 26.0.0。独立实验目录 `harmony-dsh-poc/`，不使用或修改 SayAct 仓库。

两个实验应用必须区分：

- DSHM 1.1.0，core 0.2.1-alpha.1+dshm.6，实际内置 Node v24.2.0；原版 payload 重签后部署，HAP SHA-256 `c3ce7ce834ac5708c3346dd4d403b3d4f223839bdeaddd1d7a90d259b69a9755`。
- 独立进程探针 `org.sayact.nodepoc`，自编译 Node v24.14.1，只申请 INTERNET，实际安全上下文为 `o:r:debug_hap:...`。历史包名保留用于复用调试签名与数据，不依赖 SayAct 代码。探针与 DSHM 不是同一权限配置，不能将其能力完全互相替代。

## 2. DevEco 为什么能执行

### 2.1 本机 macOS DevEco 的集成终端

```text
macOS DevEco 进程 → 本机 PTY / Shell → 本机 Node、Hvigor、Git、编译器
```

本地安装包只读检查：`tools/node/bin/node` 与 SDK `toolchains/hdc` 都是 Mach-O arm64 程序。终端插件含 `LocalTerminalDirectRunner`、`PtyProcess` 和本地进程创建入口。这说明本机集成终端首先是 macOS 上的命令入口，不能把其工具执行能力视为手机 App 的权限。

JetBrains 官方终端文档说明了这类集成终端调用命令行工具的用途；本机二进制和插件检查是对当前安装的额外佐证。[JetBrains Terminal](https://www.jetbrains.com/help/idea/terminal-emulator.html)

### 2.2 DevEco 连接手机执行 `hdc shell`

```text
电脑上的 IDE / hdc client
    → 电脑上的 hdc server
    → 已授权的 USB / TCP 调试连接
    → 手机上的 hdcd
    → 调试 Shell 执行域
```

官方 HDC 文档明确区分 client、server、设备 daemon。本轮 `hdc shell id` 返回 UID 2000(shell)，安全上下文为 `u:r:sh:s0`；普通探针应用则是应用 UID 和 `debug_hap` 域。两者执行位置都可以在手机上，但身份与访问路径不同。

`hdc shell -b <debug bundle>` 还支持调试包的数据目录访问；本轮通过它读取了 PoC 的私有诊断文件。它不是给任意应用授予通用 Shell 的 API。

不能把“在手机上执行”与“由普通应用自己的身份执行”等同，也不能简单说 DevEco 的命令全在电脑上：`hdc shell` 确实是在设备侧执行。[官方 HDC](https://developer.huawei.com/consumer/cn/doc/HarmonyOS-Guides/hdc/)

### 2.3 鸿蒙电脑上的 DevEco

鸿蒙电脑版 DevEco 是 PC 开发环境，不是手机版 IDE 的执行证据。官方为 PC/2in1 开发工具提供 CUSTOM_SANDBOX 等受限能力；ALLOW_EXTERNAL_NATIVE_CODE 的公开支持设备也是 PC/2in1。官方还提供 HAP 集成可执行 bin 的方式，并有 PC/2in1 设备边界。

这些公开机制能解释鸿蒙 PC 上开发工具存在受支持的执行通道。但本轮没有取得鸿蒙 PC 版 DevEco 的实际安装包或真实权限状态，**不能声称已经复原它的完整内部实现或确切 manifest**。

来源：[鸿蒙电脑版 DevEco 概述](https://developer.huawei.com/consumer/cn/doc/doccenter-deveco-studio/ide-hmos-tools-overview)、[受限权限](https://developer.huawei.com/consumer/cn/doc/harmonyos-guides/restricted-permissions/)、[HAP 集成 bin](https://developer.huawei.com/consumer/en/doc/harmonyos-guides/hap-bin/)。

### 2.4 如果“devecho”指 DevEco Code

官方将 DevEco Code 定位为可在 DevEco Studio 集成终端调用的开发工具；这同样不证明其 Agent 或 Shell 在普通 Phone HAP 内运行。需要沿实际运行平台、工具后端和 HDC 通道追踪，不能只看界面名。[官方安装说明](https://developer.huawei.com/consumer/cn/doc/HarmonyOS-Guides/ide-deveco-code-install/)

## 3. 本轮新增真机结果

### 3.1 普通应用身份的进程边界矩阵

下表均来自同一份 Node v24.14.1 真机探针，不是 HDC 代执行。

| 项目 | 本次实际结果 | 能得出的结论 |
| --- | --- | --- |
| Node JS 入口 | v24.14.1 / openharmony / arm64 / ready / done | 新运行时已在零售真机实际执行本次 JS，不仅是模拟器通过 |
| `isArkChildProcessSupported()` | false | 当前调用者不能使用该类 ArkTS 子进程能力 |
| `isNativeChildProcessSupported()` | false | 当前调用者不能使用该类 Native 子进程能力 |
| `open('/dev/ptmx', ...)` | EACCES，errno 13 | 普通应用 PTY 设备访问受阻 |
| stat/access `/system/bin/sh` 与 `/bin/sh` | EACCES | 不是 HDC 看到的 0755 就意味着 App 可用 |
| `spawnSync('/system/bin/sh', ...)` | EACCES | 直接写绝对路径也未解决 |
| `spawnSync('/bin/sh', ...)` | EACCES | 换同一系统 Shell 的入口无效 |
| `/usr/bin/zsh` | App stat/spawn ENOENT | 此应用视角不可用；不能套用 2in1 的 zsh 成功记录 |
| `/system/bin/toybox` | stat 755，X_OK；直接 spawn 退出 0，输出 `HARMONY_POC_CHILD_OK` | 存在无 Shell、无 PTY 的系统命令执行通道 |
| `os.userInfo()` | uv_os_get_passwd ENOENT | 账户信息还有独立兼容缺口；初版探针因此退出，显式记录异常后才完成矩阵 |
| `prctl(PR_GET_SECCOMP)` | -1 / EINVAL | 此查询无有效结果，不能据此认定 seccomp 已关闭或断定具体内核机制 |

官方 SDK 26 新增的支持查询正好可用于本次判别；官方 Native 子进程 API 的设备说明为 Tablet、PC/2in1，其他类型返回不支持。但本次 toybox 成功说明不能将这一文档范围扩大成“所有 POSIX/Node 系统工具启动绝对失败”。未经测试的裸 fork、任意 ELF、其他系统命令仍为未知。[官方 childProcessManager](https://developer.huawei.com/consumer/cn/doc/harmonyos-references/js-apis-app-ability-childprocessmanager/)

本轮从同一系统 toybox 的 HDC 视角取得 applet 清单，列有 ls/cat/grep/find/sed/head/tail/sort/uniq/wc/tar，但没有 sh/bash/ash，也没有 git/python3。**清单存在不等于这些 applet 均已在 App 身份完成测试**；当前 App 实测命令只有 echo。不能用 `toybox sh` 拼出当前未编入的 Shell。

### 3.2 DSHM 实际授权不等于 PC 能力

通过设备权限服务只读查询：

- CUSTOM_SANDBOX：grantStatus=0（已授予），FILE_ACCESS_PERSIST、READ_WRITE_USER_FILE 等也已授予。
- ALLOW_EXTERNAL_NATIVE_CODE：此 Mate 60 的权限定义查询直接返回“不存在”。
- token 列表没有 ALLOW_EXTERNAL_NATIVE_CODE / ACCESS_USER_FULL_DISK；不能只因 HAP manifest 或签名 Profile 声明了它们，就声称已获这些能力。
- 麦克风为未授予，和此次 Shell 失败不构成因果证据；本轮没有申请麦克风。

所以“再重签一次”“把所有权限点开”目前没有足够依据能解决 Shell。`hdc install -g` 是 debug 授权参数，不会创造系统没有定义的权限，本轮未用它扩大授权。

官方 API 26 变更还特别说明了 bin 独立进程权限调整不涉及手机应用；这是平台支持范围的依据，不是对某个 errno 的逐条归因。[官方 7.0 权限策略变更](https://developer.huawei.com/consumer/cn/doc/doccenter-release-notes/changelogs-for-all-apps-7001/)

### 3.3 DSHM 的失败链

精确安装包及实际 Host 日志显示：

1. `busybox` 用于工具链解包，但 spawn 返回 EACCES；Python/git 归档因此未正常落位。
2. ash/bash/rg 探针为 denied。
3. node-pty 原生模块本体可以加载，但 pty-spawn 失败：`forkpty(3) failed`。这不等于已经定位 forkpty 的每个内部失败点；普通探针的 ptmx EACCES 是另一条相关证据。
4. subprocess-local 的 executable resolver 对 stat/access(X_OK) 的异常统一吞掉，最后报“not found / not an executable file”。因此“找不到 sh”可能掩盖权限错误。
5. ondevice profile 中的 terminal-bash 指向 `/usr/bin/zsh` 并带有 2in1 来源说明；侧栏终端 controller 又会独立读取环境默认 Shell。因此只改 profile 那一行，既不能保证覆盖侧栏发现链，也不能解决 PTY 和 exec 拒绝。

上游已有与此接近的手机问题，不能把其中不同设备、不同年代的成功与失败混在一起：[DSHM 手机适配 Issue #2](https://github.com/sol5766/dshm/issues/2)。

## 4. 有哪些突破方向

| 路线 | 能解决什么 | 当前证据和限制 | 建议 |
| --- | --- | --- | --- |
| 直调系统 toybox，使用管道 stdio，不经过 sh/PTY | 可构建单命令执行、输出捕获，后续验证文件搜索等 | App 内 echo 已通过；其他 applet、取消和文件权限未测；没有完整 Shell 语义 | 第一优先继续验证 |
| 进程内 Node/原生库工具插件 | 文件、网络、归档、文本、数据处理等，不依赖 exec | Node 进程内路线已有真机/模拟器分项证据；具体提供者仍须逐项回归 | 独立手机 Agent 的主路线 |
| Python 作为受打包签名约束的 libpython 嵌入 | 可运行一部分 Python 脚本 | CPython 支持嵌入；OHOS ABI/标准库/扩展模块/取消与崩溃隔离未验证；subprocess/multiprocessing 不会自动恢复 | 有明确 Python 需求再做 |
| 纯 JS Git 或 libgit2 类能力 | 某些 Git 操作不需要 git 子进程 | isomorphic-git 有 fs/http API；本机 OHOS 未验，不能承诺所有 Git 特性、SSH、hooks、filters | 按任务所需选型，不伪装完整 CLI |
| 经用户授权的“手机连接自身 hdcd” | 若成功，可让设备调试服务承担 Shell/终端执行 | 仅有 HDC TCP 协议与可复用实现的基础；Phone 自连、授权、后台重连、文件边界都未验证 | 作为独立开发者实验，不能先算普通 App 通过 |
| OEM/系统级合作 | 可能取得不同于普通 App 的执行策略 | 需要厂商授权/系统集成，没有公开普通开发者一键获取途径 | 商业合作路线，不能自行赋予系统身份 |
| 换 PC/2in1 平台 | 有公开 bin/开发工具能力通道 | 改变设备目标，不能解决“这台手机独立运行” | 只作对照 |

Python 嵌入和纯 JS Git 的依据分别来自 [CPython 嵌入接口](https://docs.python.org/3/extending/embedding.html)、[isomorphic-git API 示例](https://isomorphic-git.org/docs/en/quickstart)。它们支持技术方向，不构成本轮 OHOS 兼容结论。

### 4.1 最值得先做的普通 App 方案

```text
Phone HAP
  └─ 同进程 Node / DSH
      └─ 可替换的 OHOS 工具提供者
          ├─ fs / HTTP / WebSocket / 文本与归档库
          ├─ 指定系统工具：spawn('/system/bin/toybox', [applet, ...args])
          └─ 必要的、随 HAP 打包签名的 NAPI / .so
```

工具入口应接收结构化的 `command / args[] / cwd / timeout`，通过 `shell:false` 执行，返回 stdout/stderr/exit/error；不要把任意 `bash -c <字符串>` 悄悄映射为 toybox，也不要宣称支持所有引号、变量展开、管道、重定向、job control。需要管道时由适配器显式连接流并测试取消与退出。

复用 dsh 的文件/网络和 provider 扩展入口；为此设备组合装配 profile，禁用或如实标注不可用的通用终端/bash 工具，再提供明确的 OHOS command 工具。不能把终端 UI 画出来就算终端成功，也不需要因此另造 Agent 运行框架。

边界：系统工具子进程可能只能看到相应授权文件；应用公共文件访问还要走系统 Picker/授权链。当前 Echo 的成功没有证明其他目录、所有命令或后台长期运行。

### 4.2 本机 HDC：值得查，但暂时不是已实现方案

候选结构为：

```text
手机 HAP 内的协议客户端（Node/Rust/C++ 库，不 spawn 一个 hdc CLI）
   → 用户显式开启并授权的本机调试通道
   → 此手机自己的 hdcd
   → 此手机的调试 Shell
```

它的计算可以仍在同一部手机，不必是远程 Host；但执行身份离开原先应用沙箱，权限和生命周期模型随之改变。必须单独验收，不能拿这个结果给“普通 App 自己 exec”的路线打勾。

可复用基础：[OpenHarmony 官方 HDC 架构与源码](https://github.com/openharmony/developtools_hdc)、[Muka Rust HDC](https://github.com/Attect/muka_rust_hdc)（主机侧重实现，不能据其 README 认定已支持 Phone HAP）。当前某些工具可在鸿蒙 PC 连接自身，仍不能外推到 Phone。

关键未知：

1. 手机应用能否连接本机调试端点；loopback 与设备 IP 的行为是否不同。
2. 是否能按官方授权流程为应用自己的客户端建立独立信任，不复制电脑私钥、不绕过认证。
3. 断开电脑、重启、切网、锁屏后是否还能连；调试端口变化如何恢复。
4. 调试 Shell 能否访问所需工作区；调试身份与 App 私有目录之间如何安全交付输入输出。
5. 真实 PTY、交互会话、取消/断连/退出语义，而非只跑一条 echo。
6. 普通发行是否允许/适合依赖开发者模式；不预先承诺上架。

本轮只进行了静态调研，**没有开启无线调试、没有改监听地址、没有启用 root、没有跳过 HDC 认证**。本机调试代理需独立授权和实验规格。

## 5. 不应作为当前修复结论的做法

- 改 PATH、chmod +x、将 sh 复制/改名/设 symlink：不足以解释或消除当前 App 的 stat/access EACCES 与 ptmx EACCES。
- 将 ELF 简单改成 `.so` 文件名：不产生可嵌入 ABI，也不修复退出、全局状态或 fork 假设。
- 只升级 Node：新版已在真机跑出 JS，但系统 Shell 仍 EACCES，证明这是不同层的问题。
- 只申请 CUSTOM_SANDBOX 或往 Profile 填 PC 权限：本次前者已授予，后者之一在此系统不存在。
- 用 root/改 SELinux/关闭系统保护作为普通用户方案：改变前提，本轮未执行。
- 以电脑 HDC 代执行或模拟器成功代替零售 Phone 普通应用验收。

## 6. 下一阶段的具体验收

建议一次只推进一个明确目标：**普通 Mate 60 上的无 Shell 命令工具**。

1. 同一精确 HAP 与应用身份下，验证 toybox 的 ls/cat/grep/find 对应用自建 fixture 的行为，不操作用户原文件；保留每项退出码和 errno。
2. 验证结构化 argv、cwd、Unicode/空格路径、stdout/stderr、超时、取消与资源回收。
3. 接入单个可替换 dsh 工具插件，只做文件读取→搜索→产出报告的一条真实任务；禁止 fallback 到 Mac/远程 Host。
4. 与既有进程内 fs/http/fetch 能力组合，补齐持久化和真实模型调用；模型 Key 不进源码或诊断日志。
5. 完成后再决定是否投入 Python/libgit2 或独立本机 HDC 实验。

当前交付是详细调研与最小进程边界实测，不是这整个工具插件已经实现。本轮已将手机前台恢复到 DSHM，未修改其原版 payload、系统执行策略或用户工作区。

## 7. 可复核的本机产物

- `reports/shell-breakthrough-research-plan.md`：目标、非目标、基线、验证口径。
- `.build/harmony-node/phone-process-boundary-evidence.json`：精确 HAP、runtime 哈希和结果绑定。
- `.build/harmony-node/phone-process-boundary-result.json`：实际 API/路径/spawn 返回值。
- `.build/harmony-node/node24.14.1-phone-process-probe.hap`：本轮已安装和执行的真实探针包。
- `.build/harmony-node/phone-platform-capabilities.json`：平台支持和 ptmx 查询；最终运行值以完整 result 为准。
- `.build/dshm-release/phone-permission-summary.json`：去除 token/设备标识的权限摘要。
- `.build/dshm-release/phone-toybox-applet-inventory.json`：HDC 视角的系统 applet 清单，仅作清单。
- `.build/harmony-node/build-hap-process-probe*.log` 与安装日志：保留初版 os.userInfo 失败以及修正后完整运行，不只汇报成功。

精确探针 HAP SHA-256：`e4347ba8df56bf1bcfa7e9b48e942d46b60e23cdf1440d9e55748c28bc396b6f`。

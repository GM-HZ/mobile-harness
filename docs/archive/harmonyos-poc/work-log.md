# 鸿蒙原生 DSH 独立调研记录

> 历史实验记录。命令与结论适用于当时的环境和版本。原始日志与二进制保存在本机。现行结论见[研究索引](../../research/harmonyos-runtime.md)。

### 2026-11-07 开源手机 Shell 专项调研

- 用户新增目标：查找可执行鸿蒙手机 Shell 的开源项目。已完成源码与主仓库文档调查，报告见 `open-source-phone-shell-survey.md`。
- 关键新增：HapInstaller 固定 `ef72d65354a899ddca0e806f7b752b5f0cb621a3`，公开 Phone HAP 的 HDC 动态库、进程内 server、无线调试连接及 Shell 调用。作为下一轮最小实验首选；尚未构建/安装或测试 Mate 60 自连。
- 对照 Muka Rust HDC、HiSH、cube-shell-cpp、Termony、SSH/远程终端，明确手机系统 Shell、Linux 模拟环境、PC、远端执行的区别。7 个 GitHub 项目锁完整提交并保存选取源码；提交与 3 个关键源码锚点静态核对通过。未执行第三方脚本或改动手机调试设置。
- 状态：本次调研完成。下一条动作是独立 Phone HAP 的 HDC 本机自连实验；不将调研或文件核对当作设备执行通过。

- 状态：in-progress；规格版本：1
- 来源：用户要求继续验证 HarmonyOS 本机模拟器和已连接真机。
- 范围纠正：起初误在 SayAct 独立 worktree 中建实验；遵用户纠正，已迁至本独立目录，原 worktree 和分支已删除。此调研不以 SayAct 代码或依赖为基线。

## 目标与非目标

先验证 Phone 模拟器和真机加载 ARM64 进程内 Node，观察 JS 入口、基础 API 及 ArkUI 状态。结果为独立调研，不修改其他项目或其生产依赖；不引入远程 Host、完整 Linux 或模拟其他平台。后续 DSH 测试必须固定版本并先通过 P0。

## 验收与验证

- 记录设备、ABI、运行时来源、哈希、构建与安装命令和结果；任何失败或未验项目如实保留。
- 最小 HAP 中 Node 实际执行 JS，提供 ready/error 状态；模拟器与真机分别验证，不将模拟器结果外推。
- 若签名、下载、平台等条件阻塞，则记录复现、限制和下一步，不把宿主机 JS 测试当设备测试。

## 执行与交接

- 当前：设备连通；最小应用与运行时准备中。
- 原工作区和个人应用数据不动；不卸载设备已有应用。

### 2026-11-06 设备验证

- 工程：`harmony-dsh-poc/`，仅测试宿主；没有加载 DSH。签名配置为本机忽略文件，未入库。模拟器 Phone HarmonyOS 7.0.0.107，API 26、arm64-v8a；真机 Mate 60 API 26、arm64-v8a。
- 第三方运行时 `electerm/ohos-node-shared` v24.2.0 ARM64：SHA-256 `3019bf5f9a279d98a87606fc13c53b0e797b6a50cf174f8a1243d880c71151a1`，与发布方一致。`llvm-readelf -h -l` 显示 DYN/AArch64、无 INTERP；并非生产安全审计。
- `ohpm install` 退出 0；hvigor 初次构建因 `CopyOptions.Local` 不存在失败（退出 255），修正后 HAP 编译通过（退出 0）。故意不附 libnode 的模拟器包安装成功且原生日志报告库不存在。
- 加入运行时后，模拟器包 SHA-256 `a0e7ad1d71eb61f6cab07f816ca97e3685b0ebcea47efe169feb6836af4bc9f0`。安装、启动成功，ArkUI 输出实际 JS `ready=true`，Node v24.2.0、`platform=openharmony`、`arch=arm64`、cwd `/`、`--jitless`、`WebAssembly=undefined`，SHA-256 加密输出符合 abc 已知值。
- 下一轮行为测试包 SHA-256 `fa73362fb7c24c2e4d5130ec4bf4aee2aa2a1b3a0e52185635fc238b9f7be2fc`，沙箱结果记录文件写／读／重命名／删除、worker 消息和 100 次 Node HTTP 回环均成功；之后 fetch 测试中进程 SIGABRT。崩溃栈为 Node 未捕获异常导致 `exit(1)`，平台将其转为 abort。原始崩溃日志 SHA-256 `ca8b02c86b36b792a30c62d94fe601b8408bcf0bb12e30cb3a044becb81c42b1`。
- 添加诊断性未捕获异常／拒绝记录后，模拟器包 SHA-256 `fec56f86309823ba84640845b111bfb1571203898ae5ca46ec72c8b8ac2b7377`。文件、worker、100 次 HTTP 再次成功；内置 fetch 回环报 `TypeError: fetch failed`，同时记录未处理拒绝 `ReferenceError: WebAssembly is not defined`。这不是修复，也没有测试外网、DNS、TLS、持久化重启或全面兼容。原始结果 SHA-256 `4f22a407c16dcb7d0967bfb0af1d80b4c7b36e4b8b8614ea942eef05dc725d96`。
- 真机拒绝首次未签名 HAP（HDC 进程退出 0，但输出 code 9568320，无签名）；用户登录并配置签名后，构建签名包 SHA-256 `40882e0bd66cbd0eb9b7d9696e434a6e34c246ead0262cce8464d3a335c515d1`，HDC 安装输出成功，`aa start` 返回成功。当前未观察到应用进程或 Node 日志，不能判定真机 P0；已请用户解锁并打开应用。
- 构建日志、测试结果、对应 HAP 和崩溃日志保存在 本目录的 `.build/harmony-node/`（生成产物，不提交）。未运行 DSH、真实模型、真机 Node、外网或生命周期性能验收。原有语音工作区和设备应用数据保留。
- 下一步：真机前台启动后检查 Node ready 和日志；若真机复现 fetch 问题，研究和验证可替换的 shim，之后才进入固定 DSH 的离线依赖与会话验证。

### 范围纠正及真机进展

- 正确目标：独立 HAP 内嵌 Node 并运行官方 DSH，固定官方提交 `fcc0ad462172522aaf5c93a7b2e01f6b9f0b0159`（0.2.2-rc.1，`engines.node >=24.9.0`），不使用 SayAct 固定版本。Node 24.2.0 低于目标要求，之前的 Node 结果仅为路径探测，不能作为目标版本 P0 通过，更不能据此进入 DSH 阶段。
- 真机首个签名包 SHA-256 `40882e0bd66cbd0eb9b7d9696e434a6e34c246ead0262cce8464d3a335c515d1`，设备日志显示启动 Node 后因 seccomp 拦截系统调用 425（io_uring_setup）而 SIGSYS 闪退；设备 faultlog 文件不可读，保留系统 hilog，SHA-256 `e342a56250379d0c6f01d155d1d72e4e0ef087b9ff6afc8e3364c062269ad72c`。
- 参考 electerm 的处理，独立 PoC 增加实验性的进程级 SIGSYS 处理，仅对 425 返回不可用，不使被拒绝的系统调用执行。真机签名包 SHA-256 `7be0da2c413135fb82e0d45ae6d93a4b92593f2649f3abd14c4c9fad1c88ece2`；设备日志显示 Node 24.2 实际 ready、文件及 worker 通过、HTTP 100 次通过，`uring_denied=1`，fetch 失败并记录 WebAssembly 不存在。日志 SHA-256 `5fb7741d0d94bc7a09434d7ed4896f8d68a4c347f1f333c68efec0b17c20e18d`。该处理影响整个进程，尚未验证与系统既有信号处理及生命周期的兼容性，不能当作生产方案。
- 下一步：取得满足 >=24.9.0 的、ABI 匹配且可复现的 libnode，固定构建输入，重跑模拟器和真机 P0；随后处理 P1 的 fetch/undici 与持久化，方可进入官方 DSH 依赖和 Host 测试。

### 运行时来源补查

DSHM 固定提交的 tools/node-runtime/build-node-ohos.sh 默认自编译 Node v22.23.2；docs/device-validation.md 中真实设备启动记录则为 v24.2.0，文档与交付版本有差别。它可作为复用参考，但该已记录版本不满足本实验所选当前官方 DSH 的 >=24.9.0。自行编译的目的仅为提供满足版本要求的 OHOS 共享运行时，并非改写 DSH 或以宿主机测试替代鸿蒙设备验证。

现成 DSHM 部署及手机签名待办见 reports/dshm-deployment.md（相对于独立 PoC 根目录）。当前新 Node 构建日志为 .build/harmony-node/build-node24-clang20-resource.log；不要沿用旧构建通过结论。

2026-11-07：DSHM 原包重签获授权，但 DevEco 被 macOS 拒绝读取 Downloads，详情见 dshm-deployment.md；Node 新构建见 build-node24-builtin-vector.log，上一轮 ranges 缺项失败已保留。

当前（2026-11-07）：DSHM 原包重签和114项payload比对成功；准确制品与哈希见 dshm-deployment.md。Mate 60 再次 Offline，安装未成功。Node 新构建使用 OHOS 专用 libc++ 头文件，日志 build-node24-ohos-libcxx.log，完整构建和设备验证未通过。

### 2026-11-07 Node 24.14.1 模拟器 P0

- 交叉构建最终退出 0，ELF AArch64 DYN 和 SONAME libnode.so 已核对；HAP 构建退出 0并包含 libc++_shared、libnode、libpoc。签名 HAP 不能覆盖模拟器此前无签名包，安装报 9568332/sign info inconsistent；没有 uninstall 清空数据。误启动旧应用读到 v24.2.0 的结果被明确排除。
- 改用本轮 unsigned HAP 后覆盖安装明确成功，force-stop/restart 后结果实际版本 v24.14.1、platform openharmony、arch arm64、entry 为独立沙箱 JS；crypto/zlib/file/worker PASS，HTTP pass:100，done true，原生 fetch TypeError。结果 `.build/harmony-node/emulator-node24-baseline-result.json`，准确 unsigned HAP SHA `d3eba6e7c5983bf6e531183611a4191c4b42c7f2785afe7183ec83976611d4c3`。
- 复用固定 DSHM commit 的未修改 fetch shim，Git blob SHA 与参考树一致，MIT LICENSE 与来源元数据保留在 js/vendor/dshm/。按显式 POC_FETCH_SHIM=dshm 打包，仅测试 HTTP/POST/headers/SSE/abort/DNS/HTTPS，未引入整个 DSHM Host，也未替代原生 fetch 失败记录。完整 P1 未通过前不进入官方 DSH Host 验收。

- DSHM fetch 垫片模式的实际设备结果：Node v24.14.1、WASM undefined、installed true，原有 crypto/zlib/file/worker/100HTTP 通过，fetchLoopback、POST JSON/native Headers、SSE 2 chunks、AbortError 取消、DNS IPv4、HTTPS example.com 都 PASS；没有关闭 TLS 校验。HAP SHA `bedcc9e1104825caf763ad839e1dbaf7dde2f24d77fe89d19eee8f508b0b2122`，完整绑定 `.build/harmony-node/emulator-node24-dshm-fetch-evidence.json`。未将这些部分 API 结果计为完整 P1。
- 真机 DSHM 安装成功并截图确认主界面；本轮最后 pidof 仍返回同一进程。没有切走真机测试新 Node；未配置 Key、未向模型发送内容。

2026-11-07 终端专项：用户报告“找不到 sh”；已读取真实 DSHM 日志，确认外部 Shell/PTY 失败（busybox EACCES、ash/bash denied、forkpty failed），系统 sh 文件在 HDC 视角确实存在。记录进 dshm-deployment.md，未修改系统限制或改 PATH 假装修复。此结果不受此前 Node 进程内 HTTP/fetch 成功替代。

### 2026-11-07 DevEco 与突破路径详细调研

- 已完成 `reports/shell-breakthrough-research.md`：区分 Mac 集成终端、设备 HDC 调试身份、鸿蒙 PC 开发工具能力；普通 Phone 工具路线与本机 HDC 实验分别列明。
- 新增可选择的 js/process-probe.cjs，ArkTS SDK 26 支持查询与 NAPI 只读 ptmx/身份探针。修改的是独立 PoC，不是 SayAct；未新增 App 权限。
- 初版因 os.userInfo() -> uv_os_get_passwd ENOENT 未捕获而退出，私有 stdio 已通过官方 hdc shell -b 读取；随后显式记录该错误，保留失败并完成其余探针。不是用系统策略放行来解决。
- 最终 signed HAP 构建与安装退出 0，实际 Node v24.14.1/openharmony/arm64/ready/done，system sh EACCES、ptmx EACCES、zsh ENOENT；直接 `/system/bin/toybox echo` exit 0。HAP SHA e4347ba8df56bf1bcfa7e9b48e942d46b60e23cdf1440d9e55748c28bc396b6f。
- DSHM CUSTOM_SANDBOX 已授予；ALLOW_EXTERNAL_NATIVE_CODE 在此手机权限服务无定义；未执行 install -g 扩大授权、无线调试切换或 root/SELinux 变更。已恢复 DSHM 前台。
- 下一条明确目标建议：无 Shell 的 OHOS command 工具插件，在同一真机验证 toybox ls/cat/grep/find 的应用自建 fixture、结构化 argv、取消与资源回收，再接入一条 dsh 真实任务。当前仅 echo 已按 App 身份实测，清单中的其他 applet 不计通过。

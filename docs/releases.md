# 版本记录

## 0.4.4

现存 PRoot 源码基线。启动时探测 seccomp 追踪加速，Mate 60 实际回退到兼容模式。引擎由应用进程持有，Home 重进复用。内置 ESM 源码索引和回环鉴权路径优化已加入。真机约 219.8 秒显示聊天页。

签名 HAP SHA-256 为 `ecf3229ca8d566bcc96e790919684e17ad35fc3ffaccb2025b37874fc8b0373a`。

## 0.4.6 原生启动试验

鸿蒙原生 Node 24.14.1 启动官方 DSH Web Host，PRoot 负责同工作区的固定 Bash 探针。修复 PRoot 等待子进程被信号中断后的处理。Mate 60 已解包冷启动 10.2 秒，独立模拟器全新安装首次启动 15.4 秒。探针模式使用独立账号和会话目录。

签名 HAP SHA-256 为 `43b6b29e06f7e9d8cb98341ddbfda641e172b52a4789c1df1580f13e30320985`。 [计时证据](evidence/native-web-comparison-0.4.6.json)

## 0.4.7 真机工具验证包

鸿蒙原生 Web 的首次工作区使用官方 `documentsDirectory` 配置，目录在 App 私有工作区。Bash 仍先经过 DSH 的默认权限和审批逻辑，允许的非交互子进程转交 PRoot。保留真实退出状态、独立 stdout 和 stderr，命令子进程不继承宿主文件描述符或凭据环境。

签名 HAP SHA-256 为 `344e6399200799a1557e922a44d4c377964023f99f3ac9cd5d70202c8b3d59a5`。 [验收范围](workspace-validation.md)

0.4.7 在独立模拟器里成功创建了首次工作区。实际一次性审批后，固定命令写入了文件，但 C 启动分支没有把进程和管道交回给 Node，DSH 工具结果被记为错误。0.4.8 补齐该分支。

## 0.4.8 真机 Bash 回传

补齐 PRoot 启动后向 Node 返回的进程 ID 和输出管道。Mate 60 通过实际聊天中的一次性审批，执行固定 Bash 管道并在工作区写文件，DSH 收到成功结果。非零退出码的真机测试仍被显示为成功，需要后续修复。

签名 HAP SHA-256 为 `3436b52de7923e12683c3890e52aa32012b0767ef679d29f7ee948da356335de`。

## 0.4.9 退出码验证

尝试保留 PRoot 首个 tracee 的退出状态。Mate 60 安装与启动成功，真实一次性审批后的 `exit 7` 仍没有返回退出码标记。保留该版供问题复现。

签名 HAP SHA-256 为 `b2a2d462844978f43914ab61cb4ca488919f43e24c9e959a2533d3c130f3b201`。

## 0.4.10 模拟器退出码与附件

Bash 使用单独的状态管道回传命令退出码，命令本身的 Bash 进程关闭该管道。去掉 0.4.9 未生效的 PRoot 改动，复用 0.4.8 HAP 的 PRoot 二进制。文本附件把目录同步边界限定在应用私有目录，硬链接被拒时使用无覆盖发布，保留摘要校验。

API 26 Phone 模拟器通过 `exit 7`、同名重复上传、同内容异名上传。该版走原生试验入口，仅在模拟器部署。真机保留 0.4.9。 [模拟器和制品证据](evidence/emulator-core-0.4.10.json)

## 0.4.11 默认原生启动与搜索通道

原生 DSH 成为默认入口，继续使用原生试验期间的会话与工作区。旧 PRoot 模式留在独立调试入口。启动不再运行 Bash 探针，也不会删除工作区里的 `result.txt`。API 26 Phone 模拟器移除旧测试开关后，冷启动到 ArkWeb 完成约 7.5 秒，已有会话可读取。

`grep` 通过已有子进程接口调用包内 ripgrep，真实模型调用搜到工作区文件。工作区外搜索被拒，默认文件写权限同样拒绝写入工作区外。 `glob` 仍因 ripgrep 的修改时间排序依赖 `/proc/self/exe` 失败。图片上传重现 Sharp 无法加载。

已部署的 unsigned HAP SHA-256 为 `f9de68e9a40db69f761645163a2e36068cb81933647d4f7d9c90730293917fbc`。本机构建 signed HAP SHA-256 为 `2eed67ed10b43ceef55f2e5c1cd05c6a16da679187fef22daddb01d30775a1df`。

## 0.4.12 glob 排序

保留 ripgrep 路径筛选，用原生 Node 文件时间排序代替依赖 `/proc` 的排序。API 26 Phone 模拟器经真实模型调用，分别测试指定目录和默认工作区的 glob，两次都按修改时间返回两个文件。清理 Bash 进程退出后的状态管道。

已部署的 unsigned HAP SHA-256 为 `34d4e367cb4679cece57117f804bae65d58a7b046ada5d30800b2809d193dd0d`。本机构建 signed HAP SHA-256 为 `9a493cca1e61228ee95ee3a0a19645682b1c904a6729f7115e5e9a725a1a4493`。

## 0.4.13 图片附件

DSH 原有 Sharp 通过短生命周期的 PRoot 子进程运行，沿用原有内容校验、像素限制、方向处理和压缩策略。API 26 Phone 模拟器通过 PNG 无损上传、GIF 转 WebP、大图缩放、损坏图像及 MIME 不符拒绝。后台 Bash 经一次批准启动，`job_output` 回读真实作业输出。 [结果](evidence/emulator-images-and-jobs-0.4.13.json)

已部署的 unsigned HAP SHA-256 为 `01bd4514b1a47c6dba4334b8fe3b56481a8869df6dcb2dc4c4257c3b5a2e9cfa`。本机构建 signed HAP SHA-256 为 `a41267112b8522ade35207524044ca3d7c7473a822259dea30fd61acb7b14a76`。

## 0.4.14 命令行工具包

封装固定版本的 Alpine aarch64 Git 2.49.1、Python 3.12.16 与依赖，以及 BusyBox 常用命令。库和解释器由 HAP 签名后映射到已有 Shell 环境。Python 的 JSON、路径、SQLite、压缩和 SSL 模块导入通过，`sleep` 通过。Git 可启动和创建仓库，`git add` 缺少 `/dev/urandom` 而失败。

已部署的 unsigned HAP SHA-256 为 `67ef69e5d4c4e22eea028f64382b85aee7abe959be3e21e35b02a078fae2b4bd`。本机构建 signed HAP SHA-256 为 `0a79833171c1c6e972e6e2deb7e6f4d3f70cf97451b66ce137dc448c2a11f389`。

## 0.4.15 Git 本地工作流

为 PRoot 增加单独的 `/dev/urandom` 映射。API 26 Phone 模拟器经实际一次性批准完成 Git 建仓、暂存、提交和日志，随后运行 Python SQLite 和 BusyBox。Git HTTPS 远端测试仍找不到 helper。ArkWeb 打开了 DeepSeek 官方登录页，验收停在登录凭据输入前。回到主屏再启动后复用同一进程。

已部署的 unsigned HAP SHA-256 为 `974ef14f11d9b4c3fcfe6598b8319745b9fb9a0b4efa1b429289bcd6c5680972`。本机构建 signed HAP SHA-256 为 `896c2f048ffebdaa530a426ef7f0b0e51b1e36a3f8e1c4687153a70cfe9b982e`。

## 0.4.16 Git helper 路径验证

指定 Git 已打包的 helper 和模板路径。模拟器能直接运行 helper，但 Git 自己仍找不到它。Git 在查找 PATH 时检查 `stat()` 的执行位，而 HAP 安装的签名库显示为 0644。另验证通过 Shell 运行内置 Node JS 脚本。pnpm 11 即使使用 hoisted 和 copy，仍试图为 store 注册项目软链接，触发 EACCES。

已部署的 unsigned HAP SHA-256 为 `e790c2921a50f951f42eea46df3f4adc4da13926060bd1f23958392aba1c32ab`。本机构建 signed HAP SHA-256 为 `1c18c581c171000e59785cfffe5ce72bfa0f10b2f1f6dd0e6a9cb2ac20360ffb`。

## 0.4.17 签名 Git 映射验证

尝试只为两个签名 Git 文件返回虚拟执行位。实际 Git HTTPS 仍未找到 helper，准备继续核对 stat 路径。工具的 stderr 已保留错误并去掉正常 PRoot 加载日志。独立模拟器验证，去掉 pnpm 的 store 项目软链接登记后，hoisted 和 copy 能在该文件系统安装本地纯 JS 依赖。该 pnpm 实验尚未进入此版本 HAP。

已部署的 unsigned HAP SHA-256 为 `e38061d2e59634de9fc1e0a3273b4cbe250af50699de0769731c8d2e58bde42c`。本机构建 signed HAP SHA-256 为 `1425f5fb0b2079f9d7927be710c9cd0dc0007530b496844a8075866b1a449c67`。

## 0.4.18 纯 JavaScript 组合包

固定 pnpm 11.28.5，通过 DSH 插件管理服务调用。适配应用私有目录的软链接限制，使用 hoisted 和 copy，跳过非必要的项目软链接登记。安装生命周期脚本保持关闭。模拟器经 `pluginManager/installBundle` 安装本地纯 JS 测试组合包，6.4 秒包安装，14.3 秒内完成安装与启用，插件状态为 active。

已部署的 unsigned HAP SHA-256 为 `9d51c6fce9bfb75cd6fbc225f3e8d80976c574c50ca2178f04894248642d8af8`。本机构建 signed HAP SHA-256 为 `3f4559b3370e8e9b709339d9d8ec5583fb8d4ffc09acb52cc175f4bbbe4dde85`。

## 0.4.19 ARM64 Git helper 探测

将签名 Git 文件的虚拟执行位补到 ARM64 实际使用的 `fstatat64` 路径。Git 远程查询已越过找不到 helper，默认等待超时，限时测试收到 SIGSEGV。DNS 查询有结果，HTTPS 尚未通过。0.4.18 的纯 JS 插件禁用、启用和覆盖安装后恢复通过。npm 元数据探测发现查询命令不接受安装参数。

已部署的 unsigned HAP SHA-256 为 `965b0a0e875abe7bdcd06fd8ea0562e3c4520d5d45314c5ce3d495dece207e0c`。本机构建 signed HAP SHA-256 为 `55255abd13655bacd77d5c137ce92ce4f74e6a3dc3a087e277b455f33b7b6671`。

## 0.4.20 区分插件查询与安装

只对包变更命令传安装专用参数。实际 npm 元数据查询进入 fetch，两个 registry 均返回网络失败。通过已装的兼容 fetch 垫片，guest Node 请求同一 npm 元数据和回环 Git 测试服务器均返回 HTTP 200。Git 通过自己的 HTTP helper 访问回环服务器仍超时。

已部署的 unsigned HAP SHA-256 为 `c6907e19ecd1bb08b64e377d27c652e7a5997d244ad6ed692ccebfc9eb99ca08`。本机构建 signed HAP SHA-256 为 `252650e12f03f0f78f6acd0c7b77eddd9ed5dd1b0722e8c61fd5d73fbf3440d8`。

## 0.4.21 插件仓库与启动复测

pnpm 默认直连通过已有 fetch 适配层，保留已有代理、自定义证书处理和依赖完整性校验。API 26 Phone 模拟器从 npm 官方仓库读取真实元数据，并下载纯 JS 测试组合包声明的依赖，安装和激活合计 19.3 秒。Bash 的非零退出码和取消回归通过。

从零应用数据启动到 ArkWeb 加载完成约 15.6 秒，强停后重启约 6.1 秒。全新默认工作区已创建。真机保留 0.4.9。 [设备和制品证据](evidence/emulator-core-0.4.21.json)

## 0.4.22 修复嵌入式 exec 文件描述符

PRoot 加载器模拟真正 exec 时的 `FD_CLOEXEC` 行为。模拟器里的普通 Git 通过回环 HTTP 和带证书验证的 smart HTTPS 查询 HEAD、克隆并读取文件。Bash 退出码、取消和从 npm 安装组合包回归通过。Python 通过 PATH 启动时 `sys.executable` 为空，在独立描述符验证里暴露。 [结果和制品校验](evidence/emulator-cloexec-0.4.22.json)

## 0.4.23 Python 解释器路径与最终启动复测

在 PRoot 的签名可执行文件探测中加入随包 Python。API 26 Phone 模拟器通过 `python3` 查找解释器、使用 `sys.executable` 重新执行、检查关闭描述符 200 并保留可继承描述符 201。再次通过有证书验证的 smart HTTPS Git 查询和克隆。

最终 HAP 从零应用数据启动到 ArkWeb 加载完成约 15.6 秒，强停后重启约 6.0 秒。全新默认工作区创建成功，无凭证访问回环页面返回 401。 [结果和制品校验](evidence/emulator-core-0.4.23.json)

## 0.4.24 Mate 60 图片库加载修复

PRoot 在 Sharp 的库搜索路径绑定 HAP 内的签名 libvips，解决 Mate 60 从解包目录加载共享库时的权限拒绝。真机覆盖安装后，PNG 上传、GIF 转 WebP、无效数据和 MIME 不匹配校验均通过。

保留数据强停重启到聊天页加载完成耗时 10.4 秒。旧会话、自定义 Skill、已安装插件及审批后的 Bash 管道均通过。真机签名 HAP SHA-256 为 `c43c1b66c0e2e8ad61bfacf924cd6a11f4f70b37f0729acef73d9cc2bb4ff19e`。 [真机和制品证据](evidence/mate60-core-0.4.23-0.4.24.json)

## 0.4.25 工程重构与模拟器恢复回归

将鸿蒙 DevEco 工程、DSH Host、bundle 和鸿蒙运行时拆分。DSH、Node、Termux PRoot、DSHM 和 Termony 通过 Git 子模块固定。干净检出可用显式提供并校验过的基线输入完成 HAP 打包。运行时全量源码复建为下一阶段工作。

普通包在 Phone 模拟器上覆盖升级。安装未启用的真实 DSH 测试插件并触发启动故障后，重新打开自动使用安全 profile，跳过故障插件并保留同一会话。原生恢复页可返回正常模式，单次批准后实测 Bash 管道和 Git、Python、Node。独立实验包验证 UI 与 Host 为两个 PID，终止 Host 后 UI 留在原进程，可启动新 Host。进程探针和普通包分别记录。 [制品与回归证据](evidence/emulator-restructure-0.4.25.json)

### 0.4.25 Mate 60 真机补验

签名普通包由 0.4.24 覆盖升级，保留旧会话。原生恢复页可在安全模式和正常模式之间切换，已安装的测试插件在安全模式停用，回到正常模式重新激活。普通包恢复安装后，保留数据强停重启到 ArkWeb 完成用时 11.7 秒，Bash 单次审批与管道通过。

独立制品使用既有调试包名与签名，在应用私有目录下单列数据根。恢复页控制终止旧 Host 后，UI PID 保持，替换 Host 返回 HTTP 200。已恢复普通包。 [真机和制品证据](evidence/mate60-restructure-0.4.25.json)

## 0.4.26 DSH-MH 鸿蒙打包

聊天页直接显示 DSH 原有界面。运行时恢复入口移到「设置 → 通用」，正常启动后可从这里选择安全模式或正常模式。启动异常时，原生恢复入口仍可用。桌面和启动页采用新的鲸鱼图标。

`./build.sh --package` 生成带版本号的 HAP 和 SHA-256 校验文件。 [构建与发布流程](development.md#打包与发布)

## 0.4.27 DSH RC.3 与鸿蒙工具层

升级官方 DSH 到 `0.2.2-rc.3`。npm 的 `next` 指向 RC.3，`latest` 仍指向 RC.1。源码子模块与 npm 发布依赖分别固定。鸿蒙构建从锁文件生成运行时层，保留会话、工作区和 DSH profile 路径。RC.3 使用独立的解包目录。搜索和设置恢复页的适配迁移到 RC.3 的新入口。

鸿蒙工具层增加 curl、sqlite3、tzdata 和常用 BusyBox 命令入口。Node CLI 复用现有 fetch 兼容层，CPython 通过普通 fork 启动子进程，并提供 `python3 -m pip` 的工作区安装方式。普通 Bash 继续执行默认沙箱检查和单次审批。

API 26 Phone 模拟器通过 RC.1 到 RC.3 的覆盖启动、旧会话回读、文件工具、图片附件、子代理、后台作业和插件故障恢复。两个工作区用标准 pip 命令安装并导入不同版本的离线纯 Python wheel。公网 PyPI 安装超时。标准 `venv` 仍因符号链接权限失败。`workflow` 实测在 JITless Host 的 TypeScript 转换步骤失败。系统 PTY、Phone Use 以及这版的 Mate 60 回归待验。 [包管理约定](harmonyos-package-management.md) · [验收记录](evidence/emulator-dsh-rc3-0.4.27.json)

### 0.4.27 调度器与 MCP 补验

Phone 模拟器在预约任务到期前强停并重启应用，重开后从原任务记录按时投递，目标会话收到真实模型回复。Streamable HTTP MCP 通过实际模型调用测试工具，结果回到 DSH 会话。测试用的调度项、MCP 配置和临时凭据均已清理。

同一版本的本地 MCP stdio 探针由宿主直接启动 `/bin/node`，在协议初始化前返回 `ENOENT`。现有 CLI 的 Node 由 PRoot 映射，本地 stdio 仍需接入可双向传输的子进程后端。定时任务跨强停重开后的投递已经验证，应用停止期间的系统唤醒和后台 Bash 作业跨进程续跑需要独立验收。 [调度器及 MCP 证据](evidence/emulator-dsh-capabilities-0.4.27.json)

## 0.4.28 鸿蒙本地 MCP stdio

MCP 的本地命令通过现有签名 PRoot 执行桥启动。宿主为 MCP SDK 提供 stdin、stdout、stderr 和退出事件。配置的命令和参数按原值传递，工作目录可以使用 `/workspace-native` 或其子目录。子进程先清空宿主环境，再接收 MCP 项显式配置的变量。安全模式拒绝启动本地 MCP 服务。

Phone 模拟器分别通过 `node` 和 `python3` 启动本地 MCP 测试服务。两套服务均完成初始化、工具发现、真实模型调用和响应回传。含引号的参数、含换行的环境变量和宿主凭据隔离由服务端断言。 [0.4.28 验收记录](evidence/emulator-mcp-stdio-0.4.28.json)

## 0.4.29 鸿蒙 Workflow

正式包启用 RC.3 Workflow。专用 Node worker 安装 seccomp 后接收脚本，由 DSH Host 负责子任务和进度。API 26 Phone 模拟器验证两个真实并行子任务、同步死循环超时、运行中取消、带活跃子任务取消和后台作业结果投递。五次 Workflow 均确认回收 worker。 [验收记录](evidence/emulator-workflow-0.4.29.json) · [实现与边界](research/harmonyos-workflow-sandbox.md)

同一安装包回归了重启后的定时投递、Streamable HTTP MCP，以及 Node 和 Python 本地 stdio MCP。四条链路均获得真实模型结果。 [回归记录](evidence/emulator-workflow-0.4.29.json)

## 0.4.30 Python 虚拟环境

鸿蒙受管 Bash 支持 CPython 的默认 `venv` 和 `--copies`。API 26 Phone 模拟器覆盖安装后，在实际 DSH Bash 单次审批中创建两个虚拟环境，用 Pip 25.0.1 分别安装纯 Python wheel 1.0 和 2.0。两套环境的导入与命令入口各自返回对应版本，直接从未激活的 shell 执行命令入口也通过。 [验收记录](evidence/emulator-venv-0.4.30.json)

同一安装包从公网 PyPI 下载并安装 `packaging==24.2`，随后验证了导入版本。Pip 遇到一次读超时，重试后成功。 [联网验收](evidence/emulator-venv-0.4.30.json)


## 0.4.31 DSH RC.4 与默认通用 PTC

运行时升级到官方 npm `0.2.2-rc.4`，328 个直接 DSH 包均锁定 RC.4。公开源码暂未发布 RC.4 标签，子模块继续固定 RC.3；构建仍检查发布依赖和七个原生绑定的精确字节。PTC、Workflow、MCP 入口经对照保持兼容。

普通构建自动生成并校验 JITless 可用的 Amaro JS，包含通用 PTC worker，不再要求实验构建参数。支持上游 REPL／Script、TypeScript、文件授权、附加目录、工具回调、单次审批、取消和 Agent 生命周期；恢复模式继续跳过该后端。

API 26 Phone 模拟器通过 16 组 PTC／Workflow／MCP／定时任务／故障恢复，以及一组完整 Bash 工具链和五个文件工具回归。实际点击设置恢复入口和原生正常模式按钮也通过。升级前包含 venv 结果的会话历史仍可读取；覆盖升级约 22.7 秒，恢复到正常模式约 5.7 秒。工具链首次采用 90 秒等待，触发原有转后台策略后被模型取消，该次失败保留；180 秒预算下完整夹具通过，未减少功能断言。

真机、首次清空数据后的启动、系统唤醒、每种提供者和可选插件尚未逐一回归。Bash 默认无内核沙箱仍拒绝；PRoot 不作为隔离后端。通用 PTC 的 enforcement 为 partial。系统 PTY 和 Phone Use 继续暂缓。[准确制品与全部回归](evidence/emulator-dsh-rc4-0.4.31.json) · [能力矩阵](dsh-capabilities.md)

## 0.4.32 原生 Office 与 RC.4 源码锁定

标准 Office skill 保留上游服务，转换、页面附件和公式重算交给受管理的独立原生 Node，使用同一官方 LibreOffice Kit WASM 与手机系统字体。当前 Phone 模拟器正常操作约 2–3 秒；主 Host 与通用 PTC 保持 jitless。失败能力探测可选用 Guest 兼容路径，但本版真机及强制回退尚未验收。

真实模型完成 DOCX／PPTX PDF、图像附件回读、Excel 公式缓存 0→42、缓存复用、损坏文档拒绝，以及取消后同会话继续执行。独立 OfficeKit 的取消、超时、空闲／在途销毁、故障后新请求恢复和全部 helper 回收均通过。18 组既有链路回归通过。保留 Guest 超时、死连接、模型复述等失败尝试，准确绑定源码和两次包内字节相同的构建，不混用 HAP 摘要。

官方 RC.4 源码标签已补发，Gitlink 固定 `3f321d32bfe382212a8ed8785c1d47a5a300aa23`，npm 仍固定 RC.4。其余能力清点继续，额外网页 HTTP/1 测试失败尚待修复。[证据与命令](evidence/emulator-office-0.4.32.json) · [架构与性能边界](research/harmonyos-native-office.md)

## 0.4.33 标准工具与 HTTP/1

将同一固定 llhttp WASM 在构建时转为 JS，补齐 jitless Host 直接调用 Undici 的 HTTP/1 路径，保留上游网络策略、限额、代理和取消。电脑原生 WASM／jitless 两组 11 项网络对照通过，Phone 模拟器实际网页、中文分块、跳转、拒绝、取消后复用及 DeepSeek 搜索通过。

10 组模拟器检查通过：标准状态工具、网页、Office、Office 取消、Workflow、提问与计划审批、PTC、PTC 审批、本地 MCP、HTTP MCP 与定时。目标和团队任务跨强停重开持久化，单次插件发现审批绑定实际工具。Workflow 取消增强为观察真实同步片段和进程回收；原失败、模型拒绝及测试口径修正全部保留。

最终普通 HAP 已覆盖安装，旧 RC.3 会话与 venv 标记保留，匿名 401／鉴权 200，测试凭据和临时 Host patch 已清理。DSH 仍为 npm／源码同步锁定的 RC.4，本版真机和剩余可选能力未宣称通过。[准确制品与逐项记录](evidence/emulator-http-standard-0.4.33.json) · [实现](research/harmonyos-http.md)

### 0.4.33 Agent 续接补验

同一准确 HAP 通过工作目录、fork 上下文、独立 cwd、消息控制与应用重启后继续同一子会话。自动目标轮实际执行文件工具并完成；隐藏夹具精确43字节回读通过。仅新增验证和证据，没有把旧包改名成新版本，未额外宣称长期任务／后台唤醒。[续接与失败记录](evidence/emulator-agent-continuation-0.4.33.json)

### 0.4.33 官方可选能力补验

同一准确 HAP 临时启用官方 Ralph／session-search bundle，四项固定来源组合验收退出0：两轮不同 fresh 子代理与文件字节结果、执行中取消并回收 helper、归档会话跨重启索引与五个查询工具、工作区边界。原 profile／锁文件恢复摘要一致，可选项仍遵循默认开关。仅新增验证，不生成或重命名应用包。[完整证据](evidence/emulator-optional-iteration-0.4.33.json)

## 0.4.34 公共子进程与工作树

替换公共 subprocess provider，复用上游 Local 输出收集与生命周期，连接随包 Git／Node。空目录根与 PRoot 绑定让官方工作树控制文件保持 Host 原生路径，Bash／MCP 保留旧视图并可读取该原生别名；没有第二份 rootfs。修复 pnpm remove 的参数兼容，保留跳过安装脚本策略。

同一最终普通 HAP 的五组通过记录：工作树、子进程／插件管理、工具链、MCP stdio、崩溃恢复。工作树默认仍拒绝无沙箱执行；明确选择完整权限的自建会话完成创建、独立读写、重启续接与归档清理。插件实际安装、启用、禁用、卸载通过，postinstall 未运行。恢复测试返回普通模式、配置／锁文件摘要一致，匿名401、鉴权200，测试凭据清除，旧会话保留。重启恢复约4.7–7.9秒，不代表清空数据首次启动。

制品源为 `7b66db814dd599cd1d07b5892d92f43ac3dee269`，未签名 HAP 650,936,407字节，SHA-256 `efa9ffd8fb5529d24971b410d32911da9ab0f47a5065107e242627fdb9192c31`。四组测试来自该提交；子进程组在只修复测试收尾后，于 `5d6eeb52158739e19837f718a5194a03167f1257` 重跑通过。没有替换制品或隐去原失败批次。[准确命令、失败与最终审计](evidence/emulator-subprocess-worktree-0.4.34.json) · [设计](research/harmonyos-host-subprocess.md)

DSH 仍锁定官方 RC.4。LSP、压缩、其他可选能力、工作树 restore／专门取消和本版真机继续验收；尚不宣称桌面全部能力等价。

## 0.4.35 官方 LSP 与可控 bundle

DSH 保持最新官方 RC.4，随包331个 DSH 组件版本一致。补充官方 LSP 三插件和真实 TypeScript language server；编译器独立放置，解决递归监听整棵 DSH 依赖引起的60秒超时。生产字节与 TypeScript 6.0.3 精确包匹配，相关源码以标准 submodule 锁定。通过公共 SDK 的安装锚声明自带 bundle，不修改上游核心。工厂配置只迁移一次，用户可以禁用并跨重启保留；恢复 profile 不运行 LSP。DSH 解包标记绑定实际层 SHA-256，避免同一 RC 增加依赖却被旧标记跳过。

同一最终 HAP 共11组检查退出0：三组 LSP 语义／bundle／生命周期，加工具链、MCP、PTC、Workflow、Office、子进程、工作树和崩溃恢复八组。严格核对源位置、引用、实现、悬停、标准库、UTF-16、修改后刷新、边界拒绝、复用及真实崩溃重建；取消／销毁夹具暂扣真实服务器的语义回复，专门检查升级、路由注销、回收及新请求恢复。先前锚点错误、超时、构建 Python 兼容、测试恢复截断和无损 JSON 输出失败均保留。

生产源 `684d101e97a61a8b929e2628d2cd43022dab48d8`，未签名 HAP 662,455,928字节，SHA-256 `555be71d17877797b50e42c1f6150a1a83898a7668ddc52670226320550ba64e`。原配置／锁文件恢复，默认 workspace-write、匿名401／鉴权200，测试凭据与临时 patch 清理，旧 RC.3 会话30事件保留。该版为模拟器结果；压缩、其他适用可选能力、工作树 restore／专门取消和真机仍继续验收。[准确证据](evidence/emulator-lsp-0.4.35.json) · [实现](research/harmonyos-lsp.md)。

### 0.4.35 会话压缩补验

沿用同一准确HAP，未修改生产代码或重命名制品。三组新增实测退出0：默认 /compact 的真实摘要、工具配对、精确事实与重启恢复；真实模型输出后的 HTTP取消／忙碌拒绝／流错误和真实重试；完整standard临时预设的低阈值自动压力，未调用手动命令。原配置、锁文件、预设与默认权限恢复，测试凭据及插件清理，旧RC.3会话30事件保留。本补验不表示此前11组重新执行，也不代表默认满容量、真实API overflow或真机已验。[证据与源码](evidence/emulator-compaction-0.4.35.json)。

## 0.4.36 原子创建、Cordis 与替代编辑

修复 HarmonyOS 拒绝 hard-link 导致的 createIfAbsent 失败。通过上游公开 I/O 边界复用已有原生 no-replace rename，保留暂存、同步、版本及权限。正式模块与启动资源复制清单同步；恢复模式继续原 provider。默认工具开关不变。

九组模拟器检查退出0：替代编辑／apply_patch、实际文件发布竞争与取消、Cordis Host及真实ArkWeb查询，加工具链、PTC、LSP、原生Office、工作树和故障恢复。包含精确UTF-8字节、已有目标不覆盖、歧义／越界／只读拒绝、多文件预检零修改、提交阶段失败的准确部分报告、准确schema／分页／retention及重启。

最终制品源 `3ff6db7f33b985e08eabb564c9af9b506fb13213`，未签名HAP 662,457,444字节，SHA-256 `3108593b6f797a73fda41c93f904edb9babc6d8632a16438ef87273259d30e82`；九组测试源为 `65da1909e3acbc38f20bfe12f4d2e0308c146eb0`。首次候选包漏复制、模型参数偏差、Cordis结果截断误判和原生摘要比较误判均保留。最终审计恢复普通模式、配置与锁文件原字节，默认workspace-write、匿名401／鉴权200、临时Key清除及旧会话30事件保留。

可选诊断Inspector单独失败：Worker profile-resolution bootstrap 缺少 require-builtin 鸿蒙绑定；其余诊断插件活跃，不影响主聊天。没有把Cordis查询或页面存在当完整CDP验收。DSH仍为最新官方RC.4；其余适用能力与真机继续，尚未桌面全功能等价。[准确命令、原失败及审计](evidence/emulator-inspection-editing-0.4.36.json) · [文件发布适配](research/harmonyos-file-publication.md)。

## 0.4.37 随包可选目录与工作树恢复

安装清单登记官方 Forge、Ralph、会话搜索和独立工作树。四个随包组件保持 RC.4 并默认关闭，使用上游插件管理分类。真实启停、跨重启状态和锁文件无变动均通过。

通过 Forge 正式 RPC 恢复原分支最新提交，缺失分支则从记录的基准重建。实际 worktree add 后暂停夹具的最终 reset，HTTP 断开回收子进程并保留部分检出及分支，重试和会话跨重启验证通过。LSP 管理与故障恢复也通过。同版共三组模拟器检查，真机及 Forge 托管平台联动尚待验收。[准确制品、命令与原失败](evidence/emulator-worktree-catalog-0.4.37.json)

## 0.4.38 会话标题与徽标技能

插件管理可启停官方「跟随会话的标题」和「DSH 徽标技能」，两者默认关闭。模拟器以真实模型验证标题来源从第一轮扩展到两轮消息。手动固定标题、后续对话和重启均保留固定结果，停用扩展后默认首轮标题提供者恢复。徽标技能实际被模型调用，设备 PNG 与锁定源码逐字节一致，生成的 Markdown 写入自建工作区。停用后技能从目录消失。

同时回归 LSP 开关和插件故障恢复。DSH 继续固定官方 RC.4。真机与 ArkWeb 视觉验收另行记录。[制品、命令和实测](evidence/emulator-titles-badge-0.4.38.json)

## 0.4.39 DeepSeek 会话导入

在官方插件管理登记随包 DeepSeek 会话导入，默认关闭。模拟器通过 v3 ZIP 上传、坏档案与坏记录处理、并发占用和断开后重试。导入保留主题、时间、分支选取、搜索记录、PNG 和缺原件的文件卡片。关闭扩展后，重启仍可读历史与图片，真实模型能继续导入的文本会话。

实际 ArkWeb 导入按钮、弹窗与原生文件选择器均已打开，停用后按钮消失。ZIP 的保存与续接通过同一官方上传接口验证。另通过 LSP 开关和故障恢复。DSH 继续固定官方 RC.4，本版未部署真机。[制品、测试和审计](evidence/emulator-chat-import-0.4.39.json)

## 0.4.41 官方插件市场与回滚

默认关闭的官方插件市场可查看索引和安装来源。模拟器通过真实 npm 安装、纯 JS 依赖、升级、候选激活失败后回滚及卸载。0.4.40 暴露了跨重启丢失私有仓库来源的问题。0.4.41 按已安装版本原子记录来源，卸载时清除。套件按官方 `module-comparison` 结果重启，并用真实模型核对运行中的工具版本。

四组检查退出 0，覆盖市场生命周期、ArkWeb 确认与取消、LSP 开关和崩溃恢复。制品源为 `e28c9672ff621a2c68b581161496ab69dae3597a`，未签名 HAP 662,461,574 字节，SHA-256 `a68ca83b6660a95fcad1341a509a08a4eec9f14933f3536f394ab8ab3e94d132`。公共索引、Git 来源及真机仍需验收。[制品、命令、原失败及审计](evidence/emulator-plugin-market-0.4.41.json)

## 0.4.42 DSH RC.5

官方源码和 npm 同步固定 RC.5。HAP 检查通过 330 个实际随包版本，七个原生输入的字节保持一致。覆盖安装到模拟器后，旧会话 30 条事件、原配置摘要、默认工作区写权限和鉴权结果均保持。升级启动约 24.2 秒。

六组模拟器检查覆盖真实 Messages 搜索和 HTTP 回归、PTC、TypeScript LSP、真实插件市场更新回滚、ArkWeb 安装确认及故障恢复。电脑另经正式 WebRuntime 验证模型路由与显式选择。未签名 HAP 662,474,000 字节，SHA-256 `3ea9d25db0a553732e0c73e3b6398b2ca040b2cd9cc8e4ec3150af494d09c7ce`，生产源 `fa97d2eb281d39370033573122164f8b5e7cb1f5`。Mate 60 实测仍待安排。[制品、命令、原失败及审计](evidence/emulator-dsh-rc5-0.4.42.json)

## 0.4.44 鸿蒙 Inspector

发布官方 Inspector bundle，默认关闭。鸿蒙 Worker 通过 Node 内置解析接口启动。DevTools 使用既有的同源会话鉴权，Worker 的发现和直连 CDP 需要内部令牌。模拟器通过真实 Host 和 ArkWeb 求值、原生快捷键打开 DevTools、停用回收及三组 Cordis／LSP／恢复回归。原配置、旧会话事件与回环鉴权保持。

未签名 HAP 662,477,680 字节，SHA-256 `65f055bfffd9f5068f49250cc444bf495439faa922375f6f5eb9ba62adf8ce05`，生产源 `1823a4846b87f01f5422d93f0694e5facc4191f7`。0.4.43 的安装空间及 Worker 参数初始化失败保留在证据中。本版为模拟器验证。[制品、命令与审计](evidence/emulator-inspector-0.4.44.json)

## 0.4.45 思考内容翻译

登记官方 RC.5 翻译 bundle，默认关闭。实际 ArkWeb 通过展开、查看原文和译文、复用已保存结果、失败重试、停用取消和原会话核对。受控匿名请求通过两种上游协议。真实 DeepSeek Flash 的合成文本翻译、Inspector 和故障恢复通过。公开 Bing 返回 HTTP 400，Google 设备探针超时，两条公网匿名路径继续验收。

未签名 HAP 662,477,690 字节，SHA-256 `352182591fcfcd34afb326636e400074d7aef8cd4ba753e84d36b855460eefc1`，生产源 `c234fc2f5456736bad348c5abcb393453f9a4449`。最终记录存储、认证、默认开关、原权限和旧会话摘要。本版为模拟器验证。[制品、命令、失败及审计](evidence/emulator-cot-translation-0.4.45.json)

## 0.4.46 个性化推荐

登记官方推荐 bundle，默认关闭。真实模型发出两类卡片。ArkWeb 通过启用现有插件、选择页面位置、暂不创建、重启复用和关闭后移除推荐技能。Creator 生成了本地包，安装失败。用最小本地包复现 pnpm 对目录创建符号链接时被系统拒绝。页面呈现、撤销与恢复待验。

Inspector 和故障恢复两组回归通过，原配置、权限、旧会话摘要与鉴权保持。未签名 HAP 662,477,712 字节，SHA-256 `6b77237a5cc3ee1a3e59769d7798a2e8294b3dd98b71966b702f4f8755c4e7c0`，生产源 `aa72905bb060b59389dba24b5ca0ba2cf8364217`。本版在模拟器验证。 [制品、运行结果和失败](evidence/emulator-personalized-recommendations-0.4.46.json)

## 0.4.47 本地插件与可选 bundle

鸿蒙包管理器将 pnpm add 的裸绝对目录转换为 `file:` 安装以复制包，其他来源与显式前缀沿用原行为。最小夹具的裸目录安装和 Creator 生成包的正式安装通过。第一次 Creator 测试停在页签查找。第二次生成返回 `ready:false`，子会话确认上游仍引用 RC.5 已移除的 `cordis-plugin-development` 技能。页面操作、撤销和恢复仍待验。

Auto review 与 LiveShare 默认关闭。Auto review 的显式会话选择、实际只读工具、重启保持和默认权限通过。受控审查补验畸形响应、拒绝、取消都阻止真实文件写入。LiveShare 通过本机 Owner 接口，暂未发布 Relay 共享。Forge 面板和真实工作树恢复、Inspector 与故障恢复通过。原配置、权限、鉴权和旧会话摘要已复核。

未签名 HAP 662,478,181 字节，SHA-256 `6730145ac50ba15723d56dc8fdbf912cb43173b96dc6f637128060caecefd4e2`，生产源 `8cbf4d96d3942231776d49e8dcb2c92a42084663`。本版为模拟器验证。 [准确制品和完整结果](evidence/emulator-optional-batch-0.4.47.json)

## 0.4.51 鸿蒙原生语音输入

登记默认关闭的 DSH 官方语音输入。随包提供官方鸿蒙 ARM64 Sherpa ONNX 1.13.8 库、ONNX Runtime 1.16.3 和随附许可。权重继续使用官方准备流程按需下载。鸿蒙 Node 在线程中处理音频，复用 DSH 语音接口、模型校验、超时、取消和工作进程回收。留存 0.4.48 启动资源漏拷贝，以及 0.4.49 至私有 HTTP 识别端的 WAV 拒绝。0.4.50 改用 worker 通道传递 PCM 后恢复。

0.4.51 通过校验后缓存准备、正式 Remote 自动与中文识别、畸形音频拒绝、连续复用和停用回收。未签名 HAP 679,565,360 字节，SHA-256 `0fe5d79036dc5beafbf1518ebb6fea518b2baf0009fcb37ec3ade15d94297538`，生产源 `2df29ff57c57bf950dfba5f3933884f44722c28e`。模拟器保留原有权限、配置、旧会话与正常启动模式。真实麦克风、ArkWeb 草稿回填与此版真机仍待验。

Creator 已使用 `dsh-doc`，子会话仍因需要 Bash 验证和客户端查询超时返回未完成。Bash 默认限制保持。0.4.50 的 Inspector 和故障恢复通过。0.4.51 的 HAP 相比 0.4.50 仅增加两个许可证文件并更新两项包版本元数据。 [准确制品、结果和失败记录](evidence/emulator-voice-input-0.4.51.json)

## 0.4.52 至 0.4.53 页面生成与语音前端

0.4.52 的 Creator 使用 DSH 随附的 JavaScript 插件模板和文件工具，在默认权限下生成并安装了计数器。实际 ArkWeb 页面通过增加和重置。首次撤销保存了操作但要求重启，卡片仍显示安装。0.4.53 只在变更已保存且目录清单确认包被移除时更新撤销状态，仍显示所需的重启提示。完整撤销和恢复待验。后续三次分别遇到中文页签、模型输出的内部页签标识和一次启动时系统 `getenv` 崩溃。已恢复普通启动和原配置。

0.4.53 从空缓存准备模型，经限速本机镜像完整下载并校验 int8 模型、词表和 Silero VAD。真实 ArkWeb 录音器处理合成普通话，转写进入草稿，第二次录音取消和插件停用回收通过。未限速的镜像曾收到连接重置，公网准备和真机麦克风仍待验。重复的 Inspector 和故障恢复检查通过。

本机 Git 服务覆盖固定提交安装、拒绝浮动分支升级、更新到指定提交、重启保留和配置恢复。未签名 HAP 679,566,498 字节，SHA-256 `7b1438f493726b2968be1ab7744bbe1e0797a58b62e1d8e3855d059d9a5e498e`，生产源 `c4516a26d9ec2175017fe666da27fb949f0940c6`。旧会话、鉴权和默认权限通过核对。 [测试结果、失败与制品](evidence/emulator-creator-and-voice-0.4.53.json)

## 0.4.54 至 0.4.55 Creator 与 LiveShare

0.4.54 将 DSH 环境变量和应用私有目录留在嵌入的 Node，避免直接写入 ArkUI 共享的原生进程环境。这是针对上版在渲染线程的 `getenv` 崩溃采取的修复。模拟器五次连续重启的本机服务就绪时间为 4,582 至 4,782 ms，每次均观察到 ArkWeb 加载。

Creator 生成后计数器可以增加和重置。撤销写入需要重启的提示，重启后确认包被移除，恢复同一保留副本再次验证控件。npm 实际下载中取消后，原清单和锁文件逐字节一致。正常重试、依赖加载、升级、激活失败回滚和卸载通过。公网 Bing／Google 翻译复测仍失败。

0.4.55 将 LiveShare 网关接入 Node worker，复用官方网关及管理 RPC。私有回环 Relay 验证预检、发布、添加会话、重启后恢复、撤销 Relay 记录及关闭网关。公网 Relay、真实授权及跨设备访问仍待验。模拟器用未签名 HAP 679,570,311 字节，SHA-256 `fbccf23c04f51504a6de47e7c3a520518dca123dff8f07facc09050919ff3be2`，生产源 `350d638c2f1d26cf6b99c490d4b530210e5d21ee`。 [两版准确制品、实测和失败](evidence/emulator-creator-liveshare-0.4.55.json)

## 0.4.56 至 0.4.57 Forge 与长会话恢复

随包的 Alpine ARM64 GitHub CLI 接入官方 Forge provider，恢复其指定提交文件读取和提交分页路径。模拟器使用私有 TLS 夹具、合成凭据及受信代理。公网 GitHub 登录与外部写入仍待验。HAP 比 0.4.55 增加 40,947,984 字节，主要来自 `gh`。

用回环 Messages 服务返回两次 `context_length_exceeded`。真实 Host 自动压缩并在原回合重试，输入历史从 19,758 与 20,197 字节分别缩至 1,897 字节，原始日志逐条一致，重启后继续使用最近检查点。PTC、LiveShare、故障恢复及旧会话审计同时通过。首次安装因模拟器空间不足失败，清理可重建的 RC.3 解包缓存后覆盖安装成功。

未签名 HAP 720,518,295 字节，SHA-256 `ef858e482d779bdf76a6d1c56d3ee7d2080e99aa16f52d789dc24e665630c90d`，生产源 `83c5bcc056c5e32169e2dbbec0d4645d3e85fb5d`。 [实测与制品](evidence/emulator-forge-overflow-0.4.57.json)

### 0.4.57 公网语音与多模态补验

已发布的同一模拟器 HAP 从空缓存经默认公网来源完成准备，核对模型、词表、VAD 三份原始摘要，并通过转写、ArkWeb 草稿回填、取消和线程回收。显式公网镜像完成下载与转写。Hugging Face 主站在模拟器上返回连接被拒。真实 DeepSeek Flash 正确识别两张随机 PNG 中的四个颜色，重启后附件字节一致，测试密钥已移除。 [补验记录](evidence/emulator-public-voice-vision-0.4.57.json)

### 0.4.57 LiveShare 查看者与 Goal 续跑补验

同一模拟器 HAP 通过独立回环客户端的共享读取、模型对话、身份来源与撤销。Goal 经过两次 Host 重启完成三个检查点，重启后工作历史与文件内容一致。用尽轮次和旧修订恢复均被拒，新修订恢复成功。回归后核对旧会话、默认权限和原 profile。 [补验记录](evidence/emulator-live-reader-goals-0.4.57.json)

### 0.4.57 公网插件依赖与实际页面翻译补验

同一 HAP 通过公网 npm 插件安装、依赖校验、重启后的实际工具调用和卸载。DSH 插件 API 来自包内同一实例。ArkWeb 用 DeepSeek Flash 翻译合成会话，重启时移除密钥仍可打开已保存的译文。此前未通过的匿名翻译端点仍保留在待验清单。 [补验记录](evidence/emulator-public-plugin-translation-0.4.57.json)

### 0.4.57 Node 原生扩展与 WASM 补验

同一 HAP 通过 Alpine 的自编译 N-API addon、公网 ARM64 musl CRC32 addon、显式启用的 WASM、TypeScript 文件和内置 fetch。DSH 工具通过标准 subprocess 接口调用，退出、取消、卸载及原配置恢复均核对通过。鸿蒙主 Host 能加载 HAP 内置的语音 addon，测试中的外部鸿蒙 addon 返回 `ERR_DLOPEN_FAILED`。 [补验记录](evidence/emulator-node-extensions-0.4.57.json)

### 0.4.57 官方登录入口与 Python 原生 wheel 补验

同一 HAP 在 ArkWeb 打开并退出公开 DeepSeek 登录页。隔离回环服务通过账号回调、重启保留与登出撤销。公网 PyPI 的 ARM64 musllinux `xxhash 3.6.0` 经正式 Bash 单次审批安装，SHA-256、venv 模块边界和原生摘要均符合预期。下载第一次超时，重试成功。 [补验记录](evidence/emulator-account-python-wheel-0.4.57.json)

### 0.4.57 Forge 写入与调试签名包

已验收的模拟器包通过隔离服务验证评审、邀请评审、旧提交拒绝与重启后合并，并保留 403 拒绝和 503 未知结果。新构建的调试签名包通过 DevEco 应用签名和 debug profile 校验。Node、原生 Host、ArkWeb 字节码和 DSH 层的 SHA-256 与模拟器包一致。Mate 60 离线，仍需验证 UDID 覆盖和实际安装。 [补验记录](evidence/emulator-forge-writes-signed-0.4.57.json)

### 0.4.57 公网上下文错误与后台任务补验

公网 DeepSeek Flash 的 Messages API 实际拒绝 1,060,044 token 的合成流式请求，返回 1,048,576 token 的上下文上限。模拟器回放同一错误后，DSH 两次完成自动压缩、原回合重试和重启恢复。模拟器另在后台约 81 秒完成三次真实模型任务，返回前台核对 Host、历史和准确回忆。 [补验记录](evidence/emulator-context-background-0.4.57.json)

## 0.4.58 公网上下文溢出恢复

保留当前回合输入，摘要仅覆盖先前历史。鸿蒙模拟器从 0.4.57 覆盖安装 0.4.58 后，请求公网 DeepSeek Flash，收到实际 HTTP 400。随后摘要只发送 688,454 个输入 token，原回合在约 19.2 秒内完成并返回准确标签，重启后再次准确回忆。复验了两次受控溢出、手动压缩、阈值压缩和旧会话。

未签名 HAP SHA-256 `37fa495563b212e1e46ad918cf27040872a7b3660fefadf27214c5295fb4d458`。调试签名 HAP SHA-256 `8c825f80a959ea493ba4ab380d011a80e1227b648884fff7b974a65ec86daa6d`，通过离线验签。Mate 60 离线，尚未安装此版。 [制品与实测](evidence/emulator-live-overflow-0.4.58.json)

## 0.4.59 公网翻译代理

鸿蒙的匿名翻译使用 DSH 已配置的代理策略。独立模拟器从 0.4.58 覆盖安装，两条官方默认翻译地址均实际建立 HTTPS 隧道并返回译文。重启后回读译文，ArkWeb 受控回归及真实 DeepSeek Flash 通过。

未签名 HAP SHA-256 `662b1e28302f0a997aca46ebce2929d7f720f459729272c727e675b3d456a72b`。调试签名 HAP SHA-256 `9026c2b5843a9dc8ac45f15de0501b7fddf6b291b0134250809c7920fe7fb125`，离线验签及 204 个 payload 条目比对通过。Mate 60 安装待验。 [制品与实测](evidence/emulator-translation-proxy-0.4.59.json)

## 0.4.60 LiveShare 所有者授权

鸿蒙 ArkWeb 支持 LiveShare 所有者登录窗口及授权回传。模拟器覆盖安装后完成隔离 Relay 的 PKCE 交换，验证重启恢复、独立查看端对话、范围拒绝及撤销。真实 DeepSeek 登录入口与受控账号回调均通过。

未签名 HAP SHA-256 `46a930c796f2da483e8f875e33c04befaddf98c6d302711fd58cee88a241ceb5`。调试签名 HAP SHA-256 `67ef2fad340b3a6aac2925755eae984ca23d12809746e0a0773c8f0fb029bb3d`，离线验签及 204 个 payload 条目比对通过。公网 Relay 和 Mate 60 安装待验。 [制品与实测](evidence/emulator-liveshare-owner-0.4.60.json)

## 0.4.61 工作区依赖与 Office Python

鸿蒙普通 profile 启用 DSH 的工作区依赖工具，并交付上游同版本的 13 个 Python 库。真实模型查询路径，Office 技能指向随包运行时。单次批准后的 NumPy、pandas、DOCX、PPTX、XLSX、PNG、XML 与 pnpm 子命令实测通过。

未签名 HAP 增加约 39.5 MiB。独立模拟器清空测试数据到观测 ArkWeb 加载完成约 48.4 秒，强停重启约 14.3 秒。调试签名 SHA-256 `eb38f9509c9a6a932bdde0465529d2b5ec320bfab5da6ddbfd11d2c9e40804a6`，离线验签及 208 个 payload 条目比对通过。Mate 60 安装待验。 [制品与实测](evidence/emulator-workspace-dependencies-0.4.61.json)

## 0.4.62 持久 Bash

Minimal 预设通过官方持久 Bash 工具复用一个受管 Alpine Shell。模拟器覆盖安装后，两条会话保留各自的目录、环境和函数。验证默认权限拒绝、明确授权后的后台任务、命令退出码，以及取消后进程回收和状态重建。Standard 预设经单次审批运行常用工具链，文件工具回归通过。

同包复验工作区依赖、Office Python 和 pnpm。模拟器中的故障插件触发安全恢复，原会话可读，恢复后 profile 清单摘要一致。

调试签名 HAP SHA-256 `9d6f5def40a5e2699418e180814ede28f7a19716936eddaf50307cc5501d0b41`，离线验签及 209 个 payload 条目比对通过。Mate 60 安装待验。 [制品与实测](evidence/emulator-persistent-bash-0.4.62.json)

## 0.4.63 Python 代码导航和启动恢复

官方 DSH LSP 通过随包 Pyright 提供 Python 源码、类型存根和标准库导航。实测定义、引用、类型提示与进程复用，保留 TypeScript 回归。原生 Host 的 60 秒启动计时在解包结束后开始。插件真实故障后仍可在安全模式读取会话，并恢复普通模式。

独立模拟器全新安装约 28.3 秒显示聊天页，已解包重启约 7.4 秒。调试签名 HAP SHA-256 `803a08d5c679eb85ad1141d9d26de3e134bf656bfe9cf2227ab61b9d81aedf66`，离线验签及 209 个 payload 条目比对通过。Mate 60 安装待验。 [制品与实测](evidence/emulator-python-lsp-0.4.63.json)

## 0.4.64 LiveShare 程序权限

访客用实际链接和派生会话的授权运行 PTC，文件范围取共享目录与会话现有权限的交集。每个程序使用独立 worker。模拟器实测并存链接的只读与可写权限、内置写工具限制、派生重放与撤销、拒绝扩大权限及主人执行。ArkWeb 登录与真模型对话通过回归。

调试签名 HAP SHA-256 `cec88d56f79f8fc004e10d2c7423fa334504105473446475c004aa0fc5bfa393`，离线验签及 209 个 payload 条目比对通过。当前验收使用回环 Relay，Mate 60 和公网 Relay 待验。 [制品与实测](evidence/emulator-liveshare-ptc-0.4.64.json)

## 0.4.65 Forge GitHub 设备登录

「设置 → 通用设置 → Forge GitHub 账号」使用包内 GitHub CLI 申请设备码，通过系统浏览器完成授权。CLI 保存设备账号供 Forge 读取。模拟器通过真实 GitHub 公网设备码签发与取消。隔离 TLS 服务通过原生授权、重启后读回账号、Forge 使用设备凭据读取仓库及退出登录。

调试签名 HAP SHA-256 `b8c88cee23beedcd36c3b6ed768d8c14b2eeffaa7c556fc750d819c00eb973a0`，离线验签及 209 个 payload 条目比对通过。仍待真实账号完成授权以及在 Mate 60 复验。 [制品与实测](evidence/emulator-forge-account-0.4.65.json)

## 0.4.69 PTC 单链接读取加固与本地模型路由回归

PTC 文件代理对普通文件的读取与 stat 补充单链接校验，与既有写路径规则一致；显式命名空间根授权保持原有范围。模拟器上应用数据视图无法创建符号链接和硬链接（应用上下文 `ln` 返回 `Operation not permitted`／`Permission denied`），工作区没有符号链接且普通文件链接数为 1，因此符号链接／硬链接端到端压力场景仍缺可用夹具。代理的路径解析每次从预打开根描述符用 `RESOLVE_NO_SYMLINKS` 重新解析，并发移动父目录只会退化为 `ENOENT`／`ELOOP`。

同一制品通过 PTC 边界压力：临时宿主插件按门控把程序父目录移出授权根，4 轮读写全部以 `ENOENT` 拒绝、被移出目录未被写入，恢复后原路径继续可用；程序自建符号链接／硬链接、读链接目标、改元数据与改写打开均被拒绝。该插件随后移除，profile manifest 字节恢复一致。同一制品通过崩溃恢复、语音转写与本机 Ollama 路由回归。故障插件注入后自动进入安全模式，5.2 秒就绪，匿名请求 401，故障插件未再次加载；SenseVoice 两次转写与 ArkWeb 草稿通过；本机 Ollama 的 `openai-completions` 与 `openai-responses` 两种协议完成模型发现、真实流式请求、工具目录、图片附件与重启保持。本机小模型不具备稳定的工具调用和视觉问答能力，工具与视觉语义仍由 DeepSeek 路由证据覆盖。

LiveShare 跨设备：owner 在真实 ArkWeb 中完成对测试 Relay 的分享授权与 PKCE 交换；测试 Relay 取回 index 资源并注入官方 `viewerCarrierScript`，在第二台模拟器的真实华为浏览器打开 viewer 页面。页面读取 `/__liveshare/context`、加载 10 个资源、经会话 cookie 完成 viewer RPC，并渲染共享会话的标题、历史消息与时间戳；界面显示只读观看者与锁定模型，且未调用所有者管理接口。第一台设备的 profile、启动配置与分享状态清理一致。该验收使用自建 Relay 与本机回环端口转发，官方 Relay 服务、真实身份提供方与公网部署仍未验证。

同一制品的 Forge 公开读回归经宿主已认证的桌面 `gh` 重新验证：包内 GitHub CLI 通过白名单网关读取 GM-HZ/omnix PR #9 的固定提交文件与提交列表，文件 SHA-256 与 GitHub 参考一致；设备端仍使用一次性夹具凭据。真实账号同意与托管仓库写操作仍待外部授权。

同一制品在全新应用数据的第二台模拟器上复验账号入口：实际 ArkWeb 打开公网 DeepSeek 授权页并返回，取消后保持登出；回环夹具完成 PKCE 交换、跨重启保持与登出撤销，profile 恢复一致。

外部原生 addon 的位置限制:0.4.69 用随包 Inspector 在 Host 主进程内测量同一份 `libdshshell.so` 字节：按安装目录 soname 从 `libs/arm64` 加载成功，复制到应用数据目录后绝对路径加载返回 `ERR_DLOPEN_FAILED`（`Error loading shared library …: No error information`）。因此外部插件携带的鸿蒙原生 addon 无法在运行时装入主 Host，插件应提供 Alpine ARM64 musl addon、纯 JS 或随 HAP 打包。探测器在结束时停用 Inspector 并恢复 profile。

语音麦克风:0.4.69 用模拟器原生麦克风完成真实声学采集——宿主外放已知的合成普通话，设备在 ArkWeb 真实录音状态下录到 5.67 秒 48 kHz 音频（RMS 0.036、峰值 0.29），官方录音器与 SenseVoice worker 转写回同一句中文并写入草稿；系统麦克风授权在结束后恢复。真机麦克风与真人说话仍待验。

未签名 HAP 为 `.build/artifacts/harmonyos/dsh-mh-harmonyos-arm64-v0.4.69-unsigned.hap`，SHA-256 `8a8832751e6eebadd0ce5859e8a99f9d537cbfd04570cc38f33a4a68a54c4daf`。 [本轮实测](evidence/emulator-capability-parity-0.4.69.json) · [PTC 边界](evidence/emulator-ptc-boundary-0.4.69.json) · [LiveShare 跨设备](evidence/emulator-liveshare-cross-device-0.4.69.json) · [Forge 公开读](evidence/emulator-forge-public-read-0.4.69.json) · [账号入口](evidence/emulator-account-fresh-0.4.69.json) · [addon 位置实测](evidence/emulator-native-addon-location-0.4.69.json) · [原生麦克风采集](evidence/emulator-voice-native-capture-0.4.69.json)

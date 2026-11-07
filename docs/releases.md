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

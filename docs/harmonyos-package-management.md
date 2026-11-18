# 鸿蒙工具与依赖管理

本约定适用于 Mobile Harness 的鸿蒙端。DSH Host 使用鸿蒙原生 Node，按需把命令交给 Alpine ARM64 的 PRoot 环境。Android 端沿用 dsh-Go 和 Ubuntu 的打包方式。两端可以对工具暴露同名命令，各自维护适用的制品和 ABI。

## 目录与归属

下表中以 `/` 开头的运行时路径均为 PRoot 内的路径。

| 内容 | 位置 | 管理方式 |
| --- | --- | --- |
| Alpine 命令和共享库 | `/bin`、`/usr/bin`、`/lib`、`/usr/lib` | 保留 Alpine 路径和 ABI 版本名，由 HAP 版本统一升级。Bash 保留在 `/bin/bash`，Git 和 Python 保留在 `/usr/bin`。 |
| Alpine 辅助程序、数据和配置 | `/usr/libexec`、`/usr/share`、`/etc` | 保留原包的加载位置，包括 Git helpers、模板和 CA 证书。Python 扩展和 Node 原生扩展保留模块各自的加载路径。 |
| Mobile Harness 管理的额外命令 | `/usr/local/bin` | 使用经打包验证的入口，启用时把该目录加入受管 Shell 的 `PATH`。 |
| 多文件工具及私有依赖 | `/opt/mobile-harness/tools/<工具>/<版本>/{bin,lib,share}` | 命令入口选定明确版本，私有库由工具自己的加载路径解析。 |
| Python 与 Node 项目依赖 | 工作区的 Python 依赖目录和 `node_modules` | Python 使用 `pip`，Node 使用项目声明的管理器和锁文件。环境可从锁文件重建，下载缓存可清理。 |
| DSH 插件 | DSH 管理的插件目录及 bundle／profile | 通过 DSH 插件管理器安装、启停和恢复，插件依赖按插件版本管理。 |

`/usr/local/bin` 和工具私有目录是新增工具的约定。当前鸿蒙受管 Shell 的 `PATH` 是 `/bin:/usr/bin`。宿主的鸿蒙 NDK 库由 HAP 原生加载器加载。Linux ELF 随 HAP 交付时也可以使用 `libguest_*.so` 包内名，再由 PRoot 映射回 Linux 路径。按文件用途和 ABI 分类。比如 `libguest_bash.so` 实际暴露的是命令 `/bin/bash`，`libguest_musl.so` 暴露的是 Linux 加载器和 libc。见 [随包映射](../runtime/harmonyos/native/poc.c) 和 [生成的工具映射](../runtime/harmonyos/native/guest-tools.inc)。

## Alpine 基础包

参考 Alpine 的 `/etc/apk/world` 与 `/etc/apk/repositories`。构建维护显式的工具需求和仓库范围，以 Alpine 同一稳定分支的 `main`、`community` 及目标架构解析依赖。直接需求按包名声明。随包锁定解析后的直接和传递依赖，包括 Alpine 包修订号、来源和 SHA-256。保留可重新取得的归档，构建按清单验证后再打包。受支持的基本命令随 HAP 更新。手机端首期以安装项目级语言依赖为主。

当前 [guest-tools-lock.json](guest-tools-lock.json) 锁定 Alpine 3.22 ARM64 的 Git、Python、选定共享库和数据包。BusyBox、Bash、musl 和历史运行时层另有 [构建输入摘要](build-inputs.sha256)。打包脚本按路径选取 ELF 与资源，`guest-tools.inc` 将包内 ELF 对应到命令、共享库和 helper 路径。当前构建从已锁定的历史运行时制品暂存。将完整 Alpine 依赖解析、下载和 HAP 映射生成接入正常构建是下一阶段工作。

纳入新的原生工具或库时，记录包名和版本、来源、SHA-256、目标架构和 libc、HAP 内文件、PRoot 路径以及实际依赖。共享库需要保留其运行时名称（如 `libssl.so.3`）。同一工具的入口、共享库及数据由同一版本交付并验证。构建发现不同制品占用同一目标路径时应失败，显式别名可映射到同一个包内文件。

## 项目包管理器

- **Python**。从 0.4.30 起，受管 Bash 支持 `python3 -m venv .venv`、`source .venv/bin/activate` 和 `pip install -r requirements.txt`。也可直接调用 `.venv/bin/python` 和项目安装的命令。Alpine Python 用 `lib` 安装模块，鸿蒙拒绝创建兼容的 `lib64` 链接时仍可继续，解释器由 CPython 复制。基础 Python 标记为 `EXTERNALLY-MANAGED`，原有 `pip install --target .python-packages` 工作流仍可用。 [Python venv](https://docs.python.org/3.12/library/venv.html) · [0.4.30 实测](evidence/emulator-venv-0.4.30.json)
- **Python 原生扩展**。带原生代码的 wheel 需要验证 CPython ABI、`musllinux` 平台标签、共享库及真机加载。已验收且经常使用的扩展可以纳入签名 HAP。仅有 glibc `manylinux` 制品的依赖交给具备相应环境的执行端。
- **Node**。现有 pnpm 适配已验证 DSH 插件纯 JS 依赖安装。项目级支持独立验收，沿用项目自己的 `package.json` 和锁文件。优先复用已有 hoisted、copy 和网络适配。纯 JS 安装与含原生 addon 或安装脚本的项目分别验收。
- **DSH 插件**。复用现有 bundle、profile 和插件管理器。保持现有安装、启动和恢复入口。安装项目依赖时，依赖写入该项目，启用的插件及其依赖通过 DSH 自己管理。

## 0.4.27 工具层

`guest-tools-lock.json` 的 `extras` 扩展基础输入。curl 和 sqlite3 与当前 Alpine 分支、架构及随包库匹配，两个 ELF 随 HAP 交付并映射到 `/usr/bin`。tzdata 以数据文件交付，设备时区能匹配数据库时在启动时更新 `/etc/localtime`。受管 Shell 用应用实际 UID 配置账号记录，并为 BusyBox 增加常用命令入口。

工具层从已锁定的 Python 输入提取原有 pip wheel，将它加入 Python 模块路径。CPython 在 PRoot 下执行子进程时改用常规 fork。模拟器中，pip 的发行版和平台标签探测会走子进程，使用 vfork 时出现崩溃。Node CLI 复用 DSHM 的 fetch 兼容层，仍处于 JITless 模式。应用升级通过独立版本的 ZIP 标记安装工具数据。

## 验收顺序

1. **现有基础层**。核对锁定 APK、HAP 暂存输入、生成映射及依赖位置；在 Phone 模拟器回归启动。既有 Bash、Git 和 Python 实测记录见 [回归矩阵](workspace-validation.md)。
2. **pip 和虚拟环境**。在两个工作区创建环境，安装同一个纯 Python 包的不同版本，分别验证导入与命令入口。验收 TLS 和离线可重复安装，验证解释器副本或符号链接能通过鸿蒙加载，再部署签名包到 Mate 60 复测。单独记录原生 wheel 的加载结果。
3. **工作区 Node 依赖及升级**。按锁安装纯 JS 依赖并运行。覆盖安装新 HAP 后回归 Bash、Git、Python、项目环境和 DSH 恢复，核对保留数据、重建项目环境和启动时间。对不具备本机 ABI 或加载支持的制品返回具体原因。

## 0.4.26 打包基线核对

以远端主分支的 `e7d0e34` 为基线，用现有打包脚本和锁定 Alpine APK 在独立暂存目录中重建工具层。逐项比对通过：110 个 ARM64 ELF 的字节与构建输入一致，136 条 PRoot 映射与仓库一致，655 个解压后的资源文件与锁定工具层一致。工具层包含 CA 证书、`venv`、`ensurepip` 和 `pip-25.0.1-py3-none-any.whl`，全局 `pip` 尚未作为命令交付。文件存在与目标解释器能启动、虚拟环境能安装包是不同的验收项。

本轮用 `HARMONY_UNSIGNED=1 HARMONY_INPUTS_DIR=<基线输入目录> ./build.sh` 构建未签名 HAP，DevEco 构建成功。包内包含上述 110 个 ARM64 ELF，以及 Bash 和 musl。内嵌工具层的 SHA-256 与构建输入清单一致。本轮 HAP SHA-256 为 `0be1fcb9273c812673e7722f5f1974c2a99e045b4e9d27aeed8a44529d79c1bb`。Phone 模拟器及 Mate 60 的 HDC 连接未就绪，设备上的启动和 pip 安装回归尚待执行。

参考 [Alpine apk 手册](https://docs.alpinelinux.org/user-handbook/0.1a/Working/apk.html) · [Alpine ARM64 py3-pip 文件清单](https://pkgs.alpinelinux.org/contents?arch=aarch64&branch=v3.22&name=py3-pip&repo=community) · [Python venv](https://docs.python.org/3.12/library/venv.html) · [Python 平台标签](https://packaging.python.org/en/latest/specifications/platform-compatibility-tags/) · [pip 可复现安装](https://pip.pypa.io/en/stable/topics/repeatable-installs/)

## 0.4.35 LSP 编译器工具链

自带 LSP 的编译器放在 Host 发布目录 `<alpine>/.dsh-0.2.2-rc.5/toolchains/lsp/node_modules/typescript/`，与 DSH 的 node_modules 为兄弟目录。它是版本锁定的只读生产输入，由 HAP 更新，来自同一 npm 锁文件，不是用户项目的包安装目录；原 npm 副本保留。此布局避免 tsserver 为标准库递归监听全部 DSH 依赖，仍保留工作区依赖监听。语言服务器和插件经正式 bundle／profile 管理。见 [实现及复现](research/harmonyos-lsp.md)。

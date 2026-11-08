# 鸿蒙手机 Shell 开源项目调研

> 历史实验记录。命令与结论适用于当时的环境和版本。原始日志与二进制保存在本机。现行结论见[研究索引](../../research/harmonyos-runtime.md)。

日期：2026-11-07。状态：静态调研完成；本次未构建或安装这些项目，未开启手机无线调试。

## 目标、边界与结论

用户要求查找能够执行鸿蒙手机 Shell 的开源项目。沿用原任务书的原生 HAP、进程内运行时方向；调查中列出 QEMU、远程 SSH、PC 项目，是为了判断其执行位置与适用范围，不代表采用这些架构。

**找到了比“自行移植一个 shell”更直接的参考：LMV475/hap-installer。** 它公开了将官方 HDC host 编译为手机 HAP 内 `.so` 的代码，在应用进程内启动 server，经无线调试连接目标设备，再发送 `shell` 命令。其页面与业务代码明确面向手机本机连接，值得作为下一轮首选实验。

这补充了此前研究中“本机 HDC 值得试，但缺少现成 Phone HAP 实现”的证据：现在已经找到手机端实现源码；**仍缺这台 Mate 60 的实际构建、授权、自连接、Shell 返回结果与断开电脑后的验证**。不能因此把普通应用直接 `exec('/system/bin/sh')` 判为成功。

检索范围包括 GitHub、GitCode/AtomGit 的鸿蒙终端、手机 HDC、自调试、SSH、Shizuku 替代与 DSH 移植项目。未发现可直接据公开实测证据认定在当前 Mate 60 普通应用身份下获得完整系统 Shell/PTY 的现成方案；这不是断言此类项目绝不存在。

## 候选项目比较

| 项目 | 实际执行链路 | Phone 相关证据 | 对当前目标的价值 |
| --- | --- | --- | --- |
| [HapInstaller](https://github.com/LMV475/hap-installer) | 手机 HAP → 进程内 HDC host/server → 无线调试设备 daemon → 系统 Shell | manifest 含 phone；无线调试连接页；本机 UDID 查询、Shell 探活与终端代码 | **首选验证。** 已有端侧 C++/NAPI 适配，免去从零实现协议 |
| [官方 HDC](https://github.com/openharmony/developtools_hdc) | 通常是电脑 client/server → 手机 daemon → 系统 Shell | 官方文档支持设备端 Shell；此前本机 USB HDC 对 Mate 60 已测成功 | 正式协议与实现基础；不能把桌面程序直接作为 HAP 子进程运行 |
| [Muka Rust HDC](https://github.com/Attect/muka_rust_hdc) | Rust 主机工具 → USB/TCP → 手机 daemon | 作者声明已对真实 HarmonyOS 设备验证；支持单命令和交互 PTY | 协议、认证和交互 Shell 的第二参考；尚非现成 Phone HAP SDK |
| [HiSH](https://github.com/harmoninux/HiSH) | 手机 HAP → QEMU → Linux 内核/rootfs → Linux Shell | README 明确支持 phone；独立 phone module；提供非 JIT TCI 构建 | 真正的手机本地 Linux Shell，但不属于原任务书的原生系统工具路线 |
| [cube-shell-cpp](https://github.com/Cubeiic-HanXuan/cube-shell-cpp) | SSH 远端；另有鸿蒙 PC 本地 PTY | CMake 将 forkpty/QProcess 的可行性明确限定为鸿蒙 PC | 可读终端实现，不能外推手机沙箱已放行 |
| [Termony](https://github.com/TermonyHQ/Termony) | 鸿蒙 Computer 终端及移植工具；包括 qemu-vroot | README 定位 HarmonyOS Computer | PC 生态参考，不作为 Phone 可行性证据 |
| [ohos_ssh](https://github.com/wzrazsh/ohos_ssh)、[TermArk](https://gitcode.com/leveleven/TermArk) | 手机 SSH 客户端 → 远端主机 Shell/PTY | 有手机 UI、VT、SSH 流式终端 | 可参考输入/渲染；不提供手机本机 Shell |
| [CortexTerminal2](https://github.com/monster-echo/CortexTerminal2) | 手机界面 → Gateway/Worker → Worker 主机 PTY | 源码 README 的 Worker/session 架构 | 远程终端产品参考，不解决手机本机执行 |

## 首选：HapInstaller 的代码证据

固定提交：`ef72d65354a899ddca0e806f7b752b5f0cb621a3`，提交日期 2026-09-28。自有代码 Apache-2.0；第三方组件仍各自遵循其许可证。

1. [hdctools/CMakeLists.txt](https://github.com/LMV475/hap-installer/blob/ef72d65354a899ddca0e806f7b752b5f0cb621a3/entry/src/main/cpp/hdctools/CMakeLists.txt)：将 HDC host/common 源码与自有入口编译为 `hdc_z SHARED`，链接 uv、OpenSSL、NAPI；启用 `HDC_NO_USB`，移除 libusb 后端。这是动态库嵌入方式。
2. [napi.cpp](https://github.com/LMV475/hap-installer/blob/ef72d65354a899ddca0e806f7b752b5f0cb621a3/entry/src/main/cpp/hdctools/napi.cpp#L96)：`hdcStartServer(tempDir)` 使用 C++ 线程调用 `server()`；`hdcRun()` 在线程调用 `cmd()`，再通过 NAPI callback 返回输出。
3. [main.cpp](https://github.com/LMV475/hap-installer/blob/ef72d65354a899ddca0e806f7b752b5f0cb621a3/entry/src/main/cpp/hdctools/main.cpp#L607)：`cmd()` 连接应用内 `127.0.0.1:18711` 的 HDC server；`server()` 在当前进程执行 `RunServerMode()`。**18711 是应用内 client/server 端口，不是手机系统无线调试 daemon 的目标端口。**
4. [ConnectDeviceSheet.ets](https://github.com/LMV475/hap-installer/blob/ef72d65354a899ddca0e806f7b752b5f0cb621a3/entry/src/main/ets/components/ConnectDeviceSheet.ets)：引导打开手机无线调试设置，填写该页面显示的 IP 和端口。
5. [Home.ets](https://github.com/LMV475/hap-installer/blob/ef72d65354a899ddca0e806f7b752b5f0cb621a3/entry/src/main/ets/pages/Home.ets#L338)：发送 `tconn`；612 行调用 `shell bm get --udid`；1478 行用 `shell echo hapinstaller-alive` 检查会话是否真的可用。这里有实际 Shell 命令调用点，不只是“终端”名称。
6. [Terminal.ets](https://github.com/LMV475/hap-installer/blob/ef72d65354a899ddca0e806f7b752b5f0cb621a3/entry/src/main/ets/pages/Terminal.ets)：输入 HDC 命令，经 HdcService 调用动态库并显示输出。
7. [module.json5](https://github.com/LMV475/hap-installer/blob/ef72d65354a899ddca0e806f7b752b5f0cb621a3/entry/src/main/module.json5)：包含 phone/tablet/2in1，只声明 INTERNET、GET_NETWORK_INFO、KEEP_BACKGROUND_RUNNING。该清单没有声明一个直接解除 Shell 沙箱限制的特权。

其执行关系为：

```text
手机上的 HAP
  ArkTS / Node 工具适配层
      → NAPI → libhdc_z.so（应用进程中的 HDC host/server）
      → 用户授权的无线调试 TCP 连接
      → 同一手机的系统 hdcd
      → 设备系统 Shell
```

本地 server 仍在 App 身份；真正创建 Shell 的是设备 daemon。若同机连接在 Mate 60 成功，可以把命令实际执行留在手机，不需要远程电脑承担执行。其前提是设备允许连接、调试认证和持续可用的通道，不能先宣称已得到默认离线原生应用能力。

### 需要保留的限制

- 本次只确认公开源码中的实现链路。没有找到足以替代我们实测的完整 Mate 60/API 26 复现记录；仓库首页的功能描述不是我们的验收结果。
- [README](https://github.com/LMV475/hap-installer/blob/ef72d65354a899ddca0e806f7b752b5f0cb621a3/README.md) 要求另行获取 HDC、签名工具及依赖并打补丁。仅锁本仓库 commit 不足以获得完整可复现构建，后续必须再锁实际 HDC/OpenSSL 等依赖版本。
- AGC 证书申请模块是未公开实现的 stub；这不等于 HDC/Shell 桥接未公开。测试 Shell 不需要把该应用的证书申请业务一起接入。
- 当前桥接以命令结束后读取文件返回为主，读取上限 512 KiB；UI 没有持续输入/输出通道。**不是已经完成的 vim/top 等交互终端。**
- `freopen()` 重定向的是整个进程的 stdout/stderr；`cmd()` 使用全局选项变量和固定输出文件。直接放入运行 Node 的同一进程，有日志污染、竞态和生命周期问题；应串行执行并重做输出捕获接口。
- `server()` 设置进程级 HOME/USERPROFILE 到临时目录。不能原样搬进既有应用；应把密钥与临时路径改为 HDC 自身配置，持久密钥不能依赖可清理的 tempDir。
- ArkTS 的 Promise 超时不等于取消 native 线程/设备命令。接入 DSH 前还缺退出码、stderr、取消、超时、连接失效与实际执行结果契约。
- HDC Shell 可见的文件与 App 沙箱文件不是天然同一视图；工作区映射、文件传入/传回需单独验证，不能把原来的 App 私有 cwd 直接当 Shell cwd。

## 第二参考：Muka Rust HDC

固定提交：`7d5f04404d29c3b105ac820d01fe26b22cf8bd07`，2026-10-12；MIT。

[README](https://github.com/Attect/muka_rust_hdc/blob/7d5f04404d29c3b105ac820d01fe26b22cf8bd07/README.md) 声明对齐 HDC 3.2.0f、支持 TCP/Wi-Fi、RSA 认证、单命令和交互 PTY，并声明真实 HarmonyOS 设备验证。

[server.rs](https://github.com/Attect/muka_rust_hdc/blob/7d5f04404d29c3b105ac820d01fe26b22cf8bd07/hdc/src/server.rs#L1847) 有 TCP 连接与 KernelHandshake/auth 流程；2318 行后发出 `ShellInit` 建立交互 Shell。[auth.rs](https://github.com/Attect/muka_rust_hdc/blob/7d5f04404d29c3b105ac820d01fe26b22cf8bd07/hdc/src/auth.rs) 提供密钥和签名实现。

但 [Cargo.toml](https://github.com/Attect/muka_rust_hdc/blob/7d5f04404d29c3b105ac820d01fe26b22cf8bd07/hdc/Cargo.toml) 目前是 `[[bin]]` 主机工具，含 rusb/libusb、portable-pty 等依赖。发布平台为 Windows/Linux/macOS，不能把 Linux arm64 产物视为 HarmonyOS HAP 库。作为手机移植起点，HapInstaller 的端侧适配更接近现状；Muka 适合核对协议与后续流式终端。

它的 8710 文档主要讲 client↔host server 协议，不能误当成直接连手机 daemon 的完整协议说明。

## 另外几类项目为什么不能混算

### HiSH：手机本地可以有 Shell，但执行在模拟的 Linux 中

固定提交 `96e12913273aed97e1ff4dacfacd9f26f741d6c3`，2026-10-30；主仓库许可证标为 MIT，QEMU 等依赖另看各自许可证。

[README](https://github.com/harmoninux/HiSH/blob/96e12913273aed97e1ff4dacfacd9f26f741d6c3/README.md) 明确支持手机、完整 arm64 Linux 内核、Alpine rootfs；Phone 不支持其 JIT 路线，提供 QEMU TCG 解释器 TCI 构建。代码树有 `product/phone` 和 QEMU 库集成。

它能提供 Linux Shell 生态，是“手机本地执行”的真实候选；但不证明普通 HAP 获得 HarmonyOS 系统 `/system/bin/sh` 权限，也不满足原任务书排除 QEMU/rootfs 的条件。本次没有下载或部署其 HAP。

### cube-shell-cpp / Termony：PC 可用不能外推 Phone

cube-shell-cpp 固定 `c555a6be8fabf54f57de4824c0153966a27754d9`，2026-11-06；LGPL-3.0。其 [CMakeLists.txt 51–73 行](https://github.com/Cubeiic-HanXuan/cube-shell-cpp/blob/c555a6be8fabf54f57de4824c0153966a27754d9/CMakeLists.txt#L51) 对本地 PTY 的主张是鸿蒙 PC 的 NDK/Qt 实测，不是 Phone；仓库也包含常规 forkpty 后端。

Termony 固定 `2fe84795201dbe14a586819f7de641db6b6c18b7`，2026-07-07；MIT。[README](https://github.com/TermonyHQ/Termony/blob/2fe84795201dbe14a586819f7de641db6b6c18b7/README.md) 明确定位 HarmonyOS Computer，工具中含 QEMU、qemu-vroot。不能仅凭“Termux for HarmonyOS”误判为手机方案。

### SSH 与远程终端

ohos_ssh 固定 `1db3f1a565e107e1a30985141f34dc04bc214cdb`，2026-02-26；GitHub 元数据未识别许可证，不先默认允许产品复用。其 [README](https://github.com/wzrazsh/ohos_ssh/blob/1db3f1a565e107e1a30985141f34dc04bc214cdb/README.md) 的手机运行 codex 指通过 SSH 交互，命令在远端执行。

[TermArk](https://gitcode.com/leveleven/TermArk) 明确是 SSH 客户端，具有 VT、远程 PTY resize 和触控输入；仓库页面标 MIT，本次未锁其 GitCode commit。

CortexTerminal2 固定 `d1fb55a6085c1a0e1420f6da0df70a709fe92c5a`，2026-11-02；[README](https://github.com/monster-echo/CortexTerminal2/blob/d1fb55a6085c1a0e1420f6da0df70a709fe92c5a/README.md) 描述 Gateway/Worker 和 Worker 的 PTY 工作目录，执行不在手机。README 写 MIT，但本次 GitHub license 元数据为空，若复用还要核对实际 LICENSE 文件。

### 只提供下载或包装 HDC 的项目

[小白调试助手 auto-installer](https://github.com/likuai2010/auto-installer) 声明支持 HarmonyOS NEXT，但当前主分支文件列表主要是 README 与图片，不能把“基于开源 HDC”当成该应用全部实现源码已公开。HapInstaller 则确实公开了我们关心的 NAPI/C++ 适配。

[HoKit](https://github.com/yabi-zzh/HoKit) 的当前 README 定位桌面客户端，终端经 HDC 执行设备命令。它可证明设备调试工具的应用场景，不能凭桌面终端功能证明手机 HAP 自连接。

## 对后续验证的具体建议

优先复用 HapInstaller 的 HDC 动态库架构，在独立 PoC 中只保留连接与单命令执行；不先重做交互终端或签名助手。以下是实验规格，尚未执行：

1. 锁定 HapInstaller 以及实际 HDC/依赖提交，构建 ARM64 `.so`，建立只含必要网络能力的独立 Phone HAP。
2. 由用户在手机设置开启无线调试并完成设备认证。使用设置显示的真实 IP/端口，不猜 `32905`、`8710`、`18711` 是设备 daemon 端口，不移植电脑的私钥或信任记录。
3. 手机 HAP 连接本机无线调试地址，执行 `id`、`pwd`、`echo` 和可清理临时目录的管道/重定向检查。记录应用 PID、HDC 目标、结果与执行身份，区分 UI 成功和设备命令真的完成。
4. 断开电脑 USB、停止开发机参与后复测。验证同机连接是否依赖 Wi-Fi、锁屏与切后台后连接状态、关闭无线调试后的明确失效及重新认证。
5. 单命令通过后，验证 stdout/stderr、退出码、超时/取消，再测交互 PTY 输入输出、窗口大小与 Ctrl-C；不能用 `echo` 成功代替全部终端验收。
6. 再评估 HDC Shell 工作目录与 DSH App 私有文件间的映射。它不会自动补出 git/python/npm 工具链，也不会自动获得其他 App 私有数据访问能力。

本次只完成调研和源码审查，没有进行上述设备配置或部署动作。此前的普通 App `sh`/PTY 失败结果继续有效；HDC 是另一条具有独立身份和授权条件的执行链路。

## 本地产物与验证记录

- 所有查阅源码保存在 `.build/shell-projects/<owner>--<repo>/`；`source.json` 记录完整 commit/日期/许可证元数据，`tree.json` 记录文件列表，`code/` 为选取源码。未执行下载项目的脚本。
- 源码下载脚本正常结束；一次尝试读取不存在的 `pages/Device.ets` 返回 404，实际设备连接实现位于已读取的 `Home.ets` 和 `ConnectDeviceSheet.ets`，没有将 404 当构建失败或隐去。
- 本次无构建、单元测试、手机应用测试或性能测试；只对下载文件、固定提交、关键调用链与报告链接做静态核对。
- 下一条动作：以 HapInstaller 作为首选参考，单独建立“Phone HAP 本机 HDC 自连”的最小实验；实验结果出来前不修改 DSHM 的执行后端，不宣布突破手机 Shell 限制。

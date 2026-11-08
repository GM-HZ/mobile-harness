# 鸿蒙 PRoot 模拟器扩展验证

> 历史实验记录。命令与结论适用于当时的环境和版本。原始日志与二进制保存在本机。现行结论见[研究索引](../../research/harmonyos-runtime.md)。

后续 USB 恢复在线，已完成 Mate 60 真机验证。结果见 [Mate 60 验证报告](proot-mate60-validation.md)。

2026-11-07。继续验证独立 HAP 的 PRoot 预加载方案，范围包括 Linux Node.js、官方 DeepSeek Harness、交互终端及 Mate 60。Phone 模拟器为 OpenHarmony 7.0.0.105、API 26、AArch64。进程以普通 `debug_hap` 身份运行。HDC 用于安装、启动及收集日志。

## 模拟器实测

| 验收项 | 结果 | 实际证据 |
| --- | --- | --- |
| Alpine Shell | 通过 | 上轮已验证独立 HAP 默认入口运行 Alpine 3.22.8、BusyBox、管道、退出码及文件读写。 |
| Linux Node.js 24.14.1 默认模式 | 通过 | `process.platform=linux`、ARM64，文件写读改名删除、SHA-256、WebAssembly 模块、Worker、HTTP 回环和内置 `fetch` 全部通过。`spawnSync` 成功运行 `/bin/sh` 和 GNU Bash 5.2.37，并收到预期输出及子进程退出码。 |
| Linux Node.js `--jitless` 对照 | 部分通过 | 文件、加密、Shell、Worker、HTTP 回环通过。WebAssembly 不可用，内置 `fetch` 失败。 |
| 系统 PTY | 失败 | 应用身份下 `openpty` 和直接打开 `/dev/ptmx` 都返回 `EACCES`。窗口大小同步和作业控制无法进入系统 PTY 验收。 |
| 交互 Shell 的管道输入输出 | 通过两轮 | 在同一个 `/bin/sh -i` 中发送第一条命令，收到确认后发送第二条，两次均收到独立输出标记。Shell 报告无法访问 tty，作业控制关闭。 |
| 官方 DSH Web | HTTP 验收通过 | 回环监听，未鉴权返回 401，启动令牌兑换浏览器 Cookie 返回 303。带 Cookie 的首页和页面引用的入口 JavaScript 均返回 200。真实浏览器渲染和 Web 会话交互未测试。 |
| 官方 DSH Headless 原始包 | 失败 | 创建了 session ID，第一次提交记录时硬链接 `link()` 被拒绝，模型请求数为 0。 |
| DSH Headless 加会话发布兼容层 | 模拟模型回合通过，默认 Shell 工具失败 | 通过 NAPI 调用 `renameat2(RENAME_NOREPLACE)`，碰撞时保留目标与源，正常发布时原子移入目标。只对固定版本首次发布时的 `EACCES` 启用。DSH 成功发布会话、收到本机 HTTP 模拟模型流式结果，进入工具调用并完成回合。默认 `workspace-write` 因缺少可用沙箱后端，拒绝执行 bash。 |
| DSH Headless 固定命令全权限对照 | 失败 | 仅在独立测试 HAP 中选择 DSH 的 `danger-full-access` 模式，输入为本机模拟模型返回的固定无副作用 `printf`。DSH 发出 tool call 后，PRoot 记录目标进程被信号 11 终止，未收到成功工具结果。该结果保留，与默认沙箱拒绝分别记录。 |

DSH 运行使用 npm 发布的 `@deepseek-ai/dsh@0.2.2-rc.1`，锁文件保留在 `full/dsh/package-lock.json`。未直接验证该 npm 制品与 Git 提交 `fcc0ad462172522aaf5c93a7b2e01f6b9f0b0159` 的字节级等价。默认 Web 与 Headless 使用原版 DSH 代码，兼容对照只在指定阶段通过 Node 模块加载钩子替换一处会话发布行为。打包省略类型声明、源码映射、PDB 和 npm 符号链接。模拟模型在 HAP 内仅监听回环地址，未进行真实模型调用。 [官方 DSH CLI 文档](https://github.com/deepseek-ai/deepseek-harness/blob/master/apps/cli/README.md)

Linux Node.js 为 Node.js Unofficial Builds 的 `node-v24.14.1-linux-arm64-musl.tar.xz`。下载与发布方 SHA-256 校验通过，补入 Alpine 3.22 的 Bash 和共享库，使用上轮 PRoot 预加载补丁。这里的默认模式是在调试 Phone 模拟器上的实测。 [Node Linux ARM64 musl 发布文件](https://unofficial-builds.nodejs.org/download/release/v24.14.1/)

## 设备制品和证据

- Linux Node 和 `--jitless` 对照 HAP SHA-256 `0e83a84643438ddca28f6422f645916f3be4d25f2435b89ee28e00048f15699f`。 默认模式日志（本机产物 `../.build/proot-validation/full/proot-embedded-node.log`） · jitless 日志（本机产物 `../.build/proot-validation/full/proot-embedded-node-jitless.log`）
- 双轮管道与 PTY 对照 HAP SHA-256 `33e47858e472a35cc33c03186e56294bbe5b7767643f19f648a2d67861b336f4`。 交互测试日志（本机产物 `../.build/proot-validation/full/proot-embedded-pty-auth.log`）
- DSH Web HAP SHA-256 `1c373fdec2caa3dcbaf269325b8f22e2a293b85f5ab64c3a5f34592a6ff4a56b`。探针用本机 HTTP 请求验证实际静态文件，保留首轮误选 HTML 中注入脚本的 404 记录。复测从前端发布包的 `index.html` 提取入口，核对返回页面引用并读取该入口。 Web 鉴权与资源日志（本机产物 `../.build/proot-validation/full/dsh-web-assets-device.log`）
- DSH 原包 Headless、原子发布兼容对照与工具执行对照。 原包 Headless 日志（本机产物 `../.build/proot-validation/full/dsh-headless-device.log`） · 兼容对照日志（本机产物 `../.build/proot-validation/full/dsh-publish-headless.log`） · 固定命令对照日志（本机产物 `../.build/proot-validation/full/proot-embedded-dsh-headless-command-final.log`） · 无覆盖重命名 NAPI（本机产物 `../.build/proot-validation/full/harmony-publish.c`）

Mate 60 在本轮 HDC 清单中显示 Offline。为同一独立实验复用已有调试签名，签名构建成功。签名 HAP SHA-256 `cdc211d04f9940575ac6bcda740ce86bc8fefce5e19db809f91ddf5cf3e050ec`。待 USB 目标恢复在线后，依次运行 Shell、Node 默认及 jitless、PTY，再进入 DSH。本轮真机安装与运行仍待验证。 真机签名 HAP（本机产物 `../.build/proot-validation/full/phone-dsh-final-signed.hap`）

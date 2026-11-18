# HarmonyOS 官方 LSP 装配与项目加载

2026-11-18，0.4.35 模拟器验证。语义与生命周期已通过，必要回归以配套证据逐项记录。

通过官方 RC.4 `dsh-lsp`、`dsh-lsp-stdio`、`dsh-tool-lsp` 和本工程 `@mobile-harness/lsp` bundle 装配；没有改写 DSH 查询或伪造语言服务器。依赖仍由标准 bundle／profile 管理。默认配置选择 TypeScript language server 5.0.0 与 TypeScript 6.0.3，两者源码以标准 Git submodule 固定发布提交，生产字节来自精确 npm 锁文件。来源与完整摘要见 `runtime/harmonyos/dsh/lsp-sources.json`。language-server 的 npm 元数据没有 gitHead，不据此宣称源码到 npm 的可复现构建。

正常 Host 使用公开 `runProfile` 的 application-owned installAnchor，声明额外插件及自带 bundle。不能仅把包复制到 node_modules 后沿用官方 CLI 原安装清单：上游插件解析遵守声明的依赖闭包。恢复 profile 不组合 LSP。工厂迁移只在普通 profile 执行一次，后续用户的禁用状态必须保留；不得在每次启动时重新打开。

## 文件布局与性能复现

首次真实工具调用曾超过上游60秒超时。直接 stdio 诊断中，同一语言服务器已完成初始化及真实 tsserver IPC，日志停在为整棵 DSH node_modules 建立递归目录监听；25秒截止仍无 definition 返回。独立 Node fork IPC 往返及正常退出仅约1.37秒，不能将阻塞归为 IPC 不受支持。

把同一 TypeScript 包物理复制到独立 node_modules 后，实际定义位置返回第1行第17列，约6.774秒；保留原通配 tsconfig 的复核约8.722秒，两次均真实 shutdown、exit0。因此生产层在原 npm 安装之外附带一份编译器工具链：

```
<alpine>/.dsh-0.2.2-rc.4/
  dsh/package.json
  dsh/node_modules/@mobile-harness/lsp/{package.json,cordis.patch.yml}
  dsh/node_modules/typescript-language-server/lib/cli.mjs
  toolchains/lsp/node_modules/typescript/{package.json,lib/...}
```

服务器指向独立工具链。构建逐字节复制同一个被锁定的 TypeScript 包，不修改工作区、不关闭工作区依赖监听、不改动语言服务器。原 npm 依赖副本保留，其他能力仍可按其声明解析。最终 HAP 已比对140个工具链文件和原生产包字节一致。

DSH 层解包标记绑定实际 ZIP 的 SHA-256，修复“同一 DSH RC 增加依赖后，旧文件名标记跳过解包”的问题；profile 和工作区不在只读发布目录中。新版本覆盖安装按摘要重装，后续重启复用同一个标记。

## 语义及生命周期验收

正常语义脚本使用真实模型调用 `lsp`，严格核对定义、引用、实现、hover、UTF-16 位置、标准库物理路径和新内容；还检查无结果、工作区外源文件拒绝、同一服务器复用与实际进程组崩溃后的重建。模型调用的观测时间包含模型往返，不能直接当作语言服务器基准。

生命周期夹具只在独立测试 bundle 内使用透明 stdio relay：真实服务器先返回 hover，relay 保存实际响应后暂扣这一帧，再触发取消或插件销毁。它不生成 initialize 能力或语义结果；该故障场景专门检查取消升级、进程回收、路由注销和新请求恢复，不能替代正常服务器的四种语义测试。夹具的 shutdown／kill grace 均为250毫秒，实测取消431毫秒、销毁131毫秒；这不是默认配置（上游分别为5秒／2秒）的延迟保证。

LSP 是受信任配置启动的读源码服务，PRoot 不是操作系统隔离。工作区外查询的入口拒绝不代表服务器无法读取其解析所需的标准库或依赖。JS／TS 继续使用 TypeScript language server。0.4.63 在同一 bundle 添加需用时启动的 Pyright `1.1.414`，路由 `.py` 与 `.pyi`。源码使用官方标签的 Git 子模块，安装字节使用官方 npm 锁定摘要。其他语言服务器须另外声明依赖、配置并实测。系统 PTY 和 Phone Use 仍沿用已确认的暂缓范围。

[准确制品、11组命令、失败批次与最终审计](../evidence/emulator-lsp-0.4.35.json)。本节点生产源为 `684d101e97a61a8b929e2628d2cd43022dab48d8`；后续测试修正与生产源码分别绑定。

0.4.63 在 Host 的私有 JavaScript 环境中为两类语言服务器提供固定运行时根目录。该值来自应用自己的安装目录。模拟器验收用普通 DSH 会话分别查询 Python 源文件、类型存根和标准库，另跑原有 TypeScript 语义与故障重建。

```sh
MH_TEST_DEEPSEEK_API_KEY="$DEEPSEEK_API_KEY" \
  python3 tests/smoke/emulator-lsp.py <loopback-target> .build/lsp-python.json --python
```

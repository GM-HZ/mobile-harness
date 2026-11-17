# JITless Host 的 HTTP/1 补齐

2026-11-18，普通 HAP 0.4.33、官方 npm DSH RC.4、API 26 ARM64 Phone 模拟器。

## 复现与原因

0.4.32 实际模型可通过 `web_fetch` 抓取 example.com HTTPS，但抓取受控本机 HTTP/1 服务时返回 `TypeError: fetch failed`。这不是网络策略拒绝：RC.4 的匿名 HTTP provider 明确允许本机与内网。Host 的全局 fetch 兼容层也不能覆盖插件直接导入的 `undici.fetch`。

锁定的 Undici 8.11.2 在 HTTP/1 路径使用 WASM llhttp；主 Host 保持 jitless，没有 WebAssembly。HTTPS 可协商 HTTP/2，因此一次 HTTPS 成功不代表 HTTP/1 成功。电脑的 jitless 对照复现了同一问题。

## 适配边界

构建从锁定 npm 层取出准确 llhttp WASM，校验 SHA-256，再用已经固定完整性的 Binaryen 132.0.0 转为纯 JavaScript。输出另有固定摘要；生成物仅进入 `.build` 与 HAP，手机无需编译器。许可证随包保留。

Host 仅在加载该版本 Undici 的 `client-h1.js` 且没有 WebAssembly 时替换解析器的实例化入口。完整源摘要不符则拒绝适配。Undici 的 HTTP 状态机、回调、dispatcher、代理、连接复用、解压与错误处理保留；上游 Web provider 的 URL、跳转、限额、解码和取消逻辑保留。解析器按首次 HTTP/1 使用延迟实例化，主 Host 的 JIT 配置不变。

这不是任意 WASM 的兼容层，也不保证后来安装的其他版本 Undici 自动适配。带内网访问能力是上游行为，不能将其称为已实现网络隔离。

## 验收

电脑上分别运行原生 WASM 与 `--jitless`，同一套实际网络夹具的 11 项检查均通过：大响应分块／trailer／连接复用、gzip、跳转、HEAD、204、中文 POST、HTTP 错误体、读取中取消及复用、错误 framing、普通转发代理、CONNECT 代理。错误 framing 的准确异常码先由同版本原生对照确定。

手机模拟器通过真实模型执行 HTML→Markdown、分块中文、同源跳转、HTTP 418 正文、跨源跳转拒绝及目标未被访问、超大声明拒绝、带凭据和非 HTTP URL 的联网前拒绝。实际 HTTP 请求到达后取消，约 72 ms 观察到回合中止，同一会话的新抓取成功。公网 HTTPS 和带真实测试凭据的 DeepSeek 搜索也通过。

共 10 组模拟器检查通过，包括标准状态工具、网页、Office、Office 取消、Workflow、交互／计划／插件发现、PTC、PTC 审批、MCP stdio、MCP HTTP 与定时。保留失败尝试与测试修正原因：Markdown 标记转义、模型拒绝无限取消夹具、误用 `/plan on` 和 Keep planning 的预期错误 envelope。Workflow 取消测试现在要求真实同步片段已开始且进程已回收，未减少取消断言。

准确 HAP、源码、命令、逐项退出码及全部尝试见 [0.4.33 证据](../evidence/emulator-http-standard-0.4.33.json)。本版真机、全新数据启动、全部可选插件仍待验证。

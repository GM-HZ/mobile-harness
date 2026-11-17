# 标准 DSH 工具与 HTTP/1 兼容

目标：沿官方 RC.4 标准 preset 完成待办、Skills、交付、目标和团队任务持久化验收，修复已复现的 JITless Host HTTP/1 抓取失败。继续完整能力清点，不把资源存在当作实际执行。

基线：`898b5f3`，`codex/harmonyos-package-management`，普通 HAP 0.4.32 已推送；原生 Office 和 18 组回归已通过。当前唯一在线设备为 API 26 ARM64 Phone 模拟器。

复现：实际模型抓取 example.com HTTPS 成功，但抓取本机 HTTP/1 返回 `TypeError: fetch failed`。随包 Undici 8.11.2 的 H1 解析器使用 WASM llhttp，而 Host 无 WebAssembly；HTTPS 可能协商 HTTP/2，不能据一次 HTTPS 成功判定所有 HTTP 可用。电脑 JITless 同样复现。使用锁定同一 llhttp WASM、固定 Binaryen 转为 JS 后，原样 Undici H1 状态机成功取得分块响应；不替换 Web provider，不绕过代理、URL、重定向、大小或超时策略。

非目标：不修改 Node 二进制、不切换主 Host 的 JIT 配置、不扩大本轮到 Phone Use／PTY。不把所有官方实验插件自动启用，不宣称完整桌面等价。

验收：固定转换输入、工具完整性和输出摘要；电脑 `--jitless` 下真实 HTTP/1、分块、多次请求、HEAD、重定向、错误、取消和代理回归；模拟器经真实工具触发受控 HTTP/1 页面、格式转换、同源／跨源重定向和 URL 校验，再回归标准状态工具、模型与已共享进程链路。最终制品重新构建与安装，精确绑定源码、命令、退出码和历史失败后推送。

测试差异：初版标准测试错误假定 RC.4 拒绝本机地址。源码和 npm 发布包均明确允许内网；通用 `fetch failed` 不能算拒绝策略通过。改为独立验证允许的本机 HTTP 返回、拒绝带凭据或非 HTTP URL，以及上游明确拒绝的跨源跳转。原始失败及已成功的状态子项保留，不称整组通过。

状态：实施中。

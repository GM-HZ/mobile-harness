# 标准 DSH 工具与 HTTP/1 兼容

目标：沿官方 RC.4 标准 preset 完成待办、Skills、交付、目标和团队任务持久化验收，修复已复现的 JITless Host HTTP/1 抓取失败。继续完整能力清点，不把资源存在当作实际执行。

基线：`898b5f3`，`codex/harmonyos-package-management`，普通 HAP 0.4.32 已推送；原生 Office 和 18 组回归已通过。当前唯一在线设备为 API 26 ARM64 Phone 模拟器。

复现：实际模型抓取 example.com HTTPS 成功，但抓取本机 HTTP/1 返回 `TypeError: fetch failed`。随包 Undici 8.11.2 的 H1 解析器使用 WASM llhttp，而 Host 无 WebAssembly；HTTPS 可能协商 HTTP/2，不能据一次 HTTPS 成功判定所有 HTTP 可用。电脑 JITless 同样复现。使用锁定同一 llhttp WASM、固定 Binaryen 转为 JS 后，原样 Undici H1 状态机成功取得分块响应；不替换 Web provider，不绕过代理、URL、重定向、大小或超时策略。

非目标：不修改 Node 二进制、不切换主 Host 的 JIT 配置、不扩大本轮到 Phone Use／PTY。不把所有官方实验插件自动启用，不宣称完整桌面等价。

验收：固定转换输入、工具完整性和输出摘要；电脑 `--jitless` 下真实 HTTP/1、分块、多次请求、HEAD、重定向、错误、取消和代理回归；模拟器经真实工具触发受控 HTTP/1 页面、格式转换、同源／跨源重定向和 URL 校验，再回归标准状态工具、模型与已共享进程链路。最终制品重新构建与安装，精确绑定源码、命令、退出码和历史失败后推送。

测试差异：初版标准测试错误假定 RC.4 拒绝本机地址。源码和 npm 发布包均明确允许内网；通用 `fetch failed` 不能算拒绝策略通过。改为独立验证允许的本机 HTTP 返回、拒绝带凭据或非 HTTP URL，以及上游明确拒绝的跨源跳转。原始失败及已成功的状态子项保留，不称整组通过。

状态：实施中。

完成状态：0.4.33 已构建并覆盖安装，准确实现提交 `d764559f8e3cb279591777ba55dc7106319f4ad9`，HAP SHA-256 `8d5158a203cb1e9801b4976a6dca8534faa19de56ac25e289bd10ea6cf3a3035`。10 组模拟器与两组电脑对照通过，正常模式、匿名鉴权、RC.3 历史与测试清理通过。全部命令、退出码、失败及测试修改原因见 [证据](../evidence/emulator-http-standard-0.4.33.json)。

其他测试修正：HTML 标记换用字母数字以免把正常 Markdown 转义误判成内容丢失。Workflow 取消用 60 秒自止同步循环，仍必须观察取消结果，新增真实同步片段与回收检查；超时测试保留无限循环。`/plan on` 的 on 在上游是新任务文本，应使用无参数 `/plan` 切模式；拒绝计划按上游实际约定精确断言错误 envelope 与模式不退出。第一次失败的完整日志保留。未删失败场景。

本任务的标准工具与 HTTP/1 阶段已完成；原“补全全部 DSH 能力”的目标继续，下一步按 RC.4 清单验证工作目录、fork／控制、自动目标续跑、Ralph／会话搜索等可选能力，并检查 LSP／工作树的 Host 子进程路径。

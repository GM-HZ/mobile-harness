# 鸿蒙翻译代理

0.4.58 的公网对照显示，模拟器直连 Bing 返回 HTTP 400，直连 Google 超时。两个原始端点经现有网络代理均返回中文译文。DSH CLI 已从启动环境和应用私有 `.env` 装配代理策略。鸿蒙 Host 为 jitless 安装的 Fetch 兼容层走原生 HTTP 客户端，绕开了 DSH 的 Undici dispatcher。

普通 Host 为锁定版翻译插件查询 DSH 的 `proxyRouteFor`。该策略决定通过代理时，用同一个 dispatcher 请求原始端点。目标、应用私有 `HTTPS_PROXY` 与 `NO_PROXY` 的解释、回环直连由官方流程负责。翻译插件继续执行其原始请求格式、跳转拒绝、限时、取消和响应上限。

验收在独立模拟器使用原始 Bing、Google 端点与固定合成文本。先复现 0.4.58 在已写入代理配置时未发出 CONNECT，再覆盖安装新 HAP，要求两条真实 HTTPS 隧道和中文译文，检查跨重启历史与临时配置清理。回环 ArkWeb 受控验收仍覆盖原译文切换、重试和取消。另一个模拟器继续执行 0.4.58 两小时后台任务。

0.4.59 验收通过。两条 CONNECT 均为 HTTP 200，两个原始上游均返回中文译文。覆盖安装、重启留存、ArkWeb 受控回归、真实 DeepSeek Flash 及应用私有配置恢复通过。调试签名与 profile 均通过离线验证，Mate 60 仍离线。 [制品与实测](../evidence/emulator-translation-proxy-0.4.59.json)

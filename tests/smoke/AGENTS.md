# AGENTS.md — 测试与探针（`tests/smoke`）

这些是验收/探针脚本，不是单元测试；它们产出 `docs/evidence/` 的证据 JSON。

## 规则

1. **每个 probe 有自己的 DONE 标记**：`ok` 必须来自本 probe 的 `*_DONE`，不要复用 exec 探针的标记；
   `device_lab` 只认探针自己的 `ok:true`。
2. **失败要可诊断**：异常带上下文；证据里保存 `toolCalls/resultText/exits` 关键字段。
3. **设备边界**：破坏性/改配置 fixture 只允许 loopback 模拟器；真机用真实账号/真实网络；
   真机屏幕锁定用 `device_lab.py run --wait-unlock`。
   直接运行真机探针时传入 `--target`，通过设备门禁运行时由 HDC 选择在线 USB 设备。
4. **超时/重试**：`ready()` 等启动类等待用 ≥120s；flake 用 `--retries` 而不是放宽断言。
5. **不泄密**：不把 token/cookie/账号写进证据或日志；临时凭据结束即清理。
6. **不依赖人**：脚本必须自清理（fport/rport/临时目录/进程），失败路径也要 cleanup。
   真机 G3 只清理本次创建并确认归属的测试目录与工作区，结束时归档测试会话。
7. **命名**：`emulator-*` 仅模拟器，`mate60-*` 真机；新增设备类型用明确前缀。
8. **端侧模型协议探针**：`local-llm-agent-probe.py` 只连接 HTTP 回环端点，以内存中的只读工具验证流式协议。证据须说明模型实际运行在宿主机还是设备上。DSH 与真机验收分别记录。
9. **端侧模型 App 端到端验收**：`emulator-local-inference-e2e.py` 从实际 HAP 的设置界面下载未安装的固定模型。验收要求设备内 SHA-256、实际本地文本回复、真实 `read` 调用和工具结果回填、默认项恢复全部通过。文件预置、模型发现和路由事件是诊断证据。

## 检查清单

- [ ] 单跑与在 gate 里跑结果一致；
- [ ] 证据 JSON 能说明"测了什么、通过/失败在哪"；
- [ ] cleanup 在 finally 中执行（fport/文件/进程）。

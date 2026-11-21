# AGENTS.md — 测试与探针（`tests/smoke`）

这些是验收/探针脚本，不是单元测试；它们产出 `docs/evidence/` 的证据 JSON。

## 规则

1. **每个 probe 有自己的 DONE 标记**：`ok` 必须来自本 probe 的 `*_DONE`，不要复用 exec 探针的标记；
   `device_lab` 只认探针自己的 `ok:true`。
2. **失败要可诊断**：异常带上下文；证据里保存 `toolCalls/resultText/exits` 关键字段。
3. **设备边界**：破坏性/改配置 fixture 只允许 loopback 模拟器；真机用真实账号/真实网络；
   真机屏幕锁定用 `device_lab.py run --wait-unlock`。
4. **超时/重试**：`ready()` 等启动类等待用 ≥120s；flake 用 `--retries` 而不是放宽断言。
5. **不泄密**：不把 token/cookie/账号写进证据或日志；临时凭据结束即清理。
6. **不依赖人**：脚本必须自清理（fport/rport/临时目录/进程），失败路径也要 cleanup。
7. **命名**：`emulator-*` 仅模拟器，`mate60-*` 真机；新增设备类型用明确前缀。

## 检查清单

- [ ] 单跑与在 gate 里跑结果一致；
- [ ] 证据 JSON 能说明"测了什么、通过/失败在哪"；
- [ ] cleanup 在 finally 中执行（fport/文件/进程）。

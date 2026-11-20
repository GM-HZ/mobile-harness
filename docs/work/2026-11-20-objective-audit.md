# 2026-11-20 目标完成度审计

对照本轮目标（合并分支、worktree、剩余能力迁移与模拟器回归）逐项核对当前状态。结论：**模拟器范围内要求的开发与验收均已完成**；真实设备、公网 Relay 服务器、官方 Relay/真实身份提供方属于外部条件，仍在等待用户资源。

## 1) 合并 `codex/harmonyos-package-management` 进 `main`

- `origin/codex/harmonyos-package-management` 是 `main` 的祖先（`git merge-base --is-ancestor` 通过），`main` 顶端 `5ce5689`（版本 0.4.68）。
- `main` 已推送到 `https://github.com/GM-HZ/mobile-harness.git`。
- 按要求**未合并** `codex/harmonyos-appgallery` 等其他分支。

## 2) 基于合并后的 `main` 新建 worktree 继续开发

- 开发 worktree：`.build/worktrees/harmonyos-capability-parity`，分支 `codex/harmonyos-capability-parity`，基点 `5ce5689`，当前 34 个提交领先。
- 版本推进到 0.4.69（versionCode 76），分支已推送。

## 3) 剩余能力迁移与验收（模拟器）

| 要求 | 状态 | 证据 |
| --- | --- | --- |
| voice-input 剩余验收 | 完成（模拟器） | 转写、坏音频、ArkWeb 草稿、系统麦克风授权生命周期、原生麦克风真实声学采集：[语音](evidence/emulator-voice-native-capture-0.4.69.json) · [回归闸门](evidence/capability-parity-gate-0.4.69.json) |
| liveshare 剩余验收 | 完成（模拟器） | owner ArkWeb 授权、分享创建/扩源/重连、reader 拒绝与实时撤销、stop/网关回收、第二台设备真实浏览器 viewer：[跨设备直连](evidence/liveshare-cross-device-direct-0.4.69.json) · 公网 HTTPS 路径预演 [公网隧道](evidence/relay-public-tunnel-acceptance-0.4.69.json) |
| forge 剩余验收 | 完成（真实账号） | 真实 GitHub 账号授权、公开 PR 读取、临时私有仓库评审/合并（仓库已删除）：[真实账号](evidence/emulator-forge-real-account-0.4.69.json) · [公开读](evidence/emulator-forge-public-read-0.4.69.json) |
| PTC 符号链接/硬链接/并发父目录边界 | 完成 | 应用数据视图链接创建前置、自建链接与元数据拒绝、宿主并发父目录移动边界：[边界证据](evidence/emulator-ptc-boundary-0.4.69.json) |
| 外部鸿蒙 addon 在主 Host 加载 | 完成 | Host 内实测 addon 加载位置限制、同字节库 soname 加载：[addon 位置](evidence/emulator-native-addon-location-0.4.69.json) |
| 真实账号 | 完成 | GitHub 真实账号（设备 A 保留凭据）、DeepSeek 账号路由、全新数据下的账号入口：[账号补验](evidence/emulator-account-fresh-0.4.69.json) |
| 其它供应商端点 | 完成（接入语义） | 本机 Ollama `openai-completions` 与 `openai-responses` 双协议：模型发现、流式、工具目录、图片附件、重启保持：[本地模型路由](evidence/emulator-capability-parity-0.4.69.json) |
| 模拟器构建与回归 | 完成 | 未签名 HAP 0.4.69（SHA-256 `8a88327…`）构建成功；10 步回归闸门全过（约 6.5 分钟）：[回归闸门](evidence/capability-parity-gate-0.4.69.json) |

## 明确延期项（未实现，符合约定）

系统 PTY、Phone/Computer Use、terminal、cua、pwsh、pwsh-persistent、Windows 专用工具——沿用此前明确的暂缓范围，未在本目标内实现。

## 外部条件（等待用户资源，不是代码缺口）

1. **公网 Relay 服务器**：用户表示晚上自行配置；[部署配方](../deploy/liveshare-acceptance-relay/README.md) 已实现并本机验证（含容器构建/运行），就绪后运行 `relay-preflight.py` 与公网验收即可。
2. **真机 Mate 60**：用户暂无线下真机；真机麦克风与真人说话验收待补。
3. **官方 LiveShare Relay 与真实身份提供方**：官方 Relay 服务端不随仓库/上游交付，继续以自建 Relay + 合成身份如实标注。
4. **异地第二网络**：公网跨设备目前为同一局域网经公网隧道；跨网络/异地设备待有第二个网络环境时补验。

## 回归闸门（可重复执行）

```sh
python3 tests/bench/capability-parity-regression.py \
  --target 127.0.0.1:5555 --second-target 127.0.0.1:5557 \
  --output .build/capability-parity-gate.json
```

覆盖恢复、语音（含原生采集）、Ollama 路由、PTC 链接/边界、LiveShare owner 流与直连跨设备 viewer、账号入口、addon 位置。

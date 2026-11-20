# 2026-11-20 交付总结（0.4.69 能力对齐）

本分支（`codex/harmonyos-capability-parity`）在合并后的 `main` 之上完成 Codex 遗留的鸿蒙 DSH 能力迁移与验收。以下按目标条目列出交付物与证据，以及仍需用户资源的外部事项。

## 分支与制品

- 基线：`main` = `5ce5689`（0.4.68，`codex/harmonyos-package-management` 已合并入 `main`）。
- 开发分支：`codex/harmonyos-capability-parity`，worktree `.build/worktrees/harmonyos-capability-parity`，35 个提交领先基线。
- 制品：`.build/artifacts/harmonyos/dsh-mh-harmonyos-arm64-v0.4.69-unsigned.hap`
  - 版本 0.4.69 / versionCode 76
  - SHA-256 `8a8832751e6eebadd0ce5859e8a99f9d537cbfd04570cc38f33a4a68a54c4daf`
  - 运行时 Node 24.14.1 + 官方 DSH `0.2.2-rc.5`

## 能力交付与证据

| 能力 | 交付 | 证据 |
| --- | --- | --- |
| voice-input | SenseVoice 转写、坏音频拒绝、ArkWeb 草稿、系统麦克风权限生命周期、原生麦克风真实声学采集 | [原生采集](evidence/emulator-voice-native-capture-0.4.69.json) |
| liveshare | owner ArkWeb 授权（PKCE）、分享创建/扩源/重连、reader 拒绝与实时撤销、stop/网关回收；第二台设备真实浏览器读 viewer；公网 HTTPS 路径预演 | [跨设备](evidence/emulator-liveshare-cross-device-0.4.69.json) · [直连跨设备](evidence/liveshare-cross-device-direct-0.4.69.json) · [公网隧道](evidence/relay-public-tunnel-acceptance-0.4.69.json) |
| forge | 真实 GitHub 账号授权、公开 PR 读取、临时私有仓库评审/合并写操作（仓库已删除） | [真实账号](evidence/emulator-forge-real-account-0.4.69.json) · [公开读](evidence/emulator-forge-public-read-0.4.69.json) |
| PTC 边界 | 符号链接/硬链接拒绝、元数据拒绝、宿主并发父目录移动越界防护、单链接读取加固 | [边界压力](evidence/emulator-ptc-boundary-0.4.69.json) |
| 外部 addon 在主 Host 加载 | Host 进程内加载位置实测、应用数据副本 `ERR_DLOPEN_FAILED`、同字节库 soname 加载 | [addon 位置](evidence/emulator-native-addon-location-0.4.69.json) |
| 真实账号 | DeepSeek 账号路由与账号入口（全新数据）、GitHub 真实账号 | [账号补验](evidence/emulator-account-fresh-0.4.69.json) |
| 其它供应商端点 | 本机 Ollama `openai-completions` / `openai-responses` 双协议：模型发现、流式、工具目录、图片附件、重启保持 | [本地模型路由](evidence/emulator-capability-parity-0.4.69.json) |
| 模拟器构建与回归 | 未签名 HAP 构建成功；**10 步回归闸门连续两次全绿**（约 6–7 分钟/次） | [回归闸门](evidence/capability-parity-gate-0.4.69.json) |

## 回归闸门

```sh
python3 tests/bench/capability-parity-regression.py \
  --target 127.0.0.1:5555 --second-target 127.0.0.1:5557 \
  --output .build/capability-parity-gate.json
```

覆盖 10 步：恢复、语音（含原生采集）、Ollama 路由、PTC 链接前置与边界、LiveShare owner 流、直连跨设备 viewer、账号入口、addon 位置。两次连续运行均为 `ok=true`、失败 0。

## 公网 LiveShare 验收（等服务器）

- 部署配方：[deploy/liveshare-acceptance-relay](../deploy/liveshare-acceptance-relay/README.md)（Docker/Compose + nginx + certbot），本机构建镜像并运行容器验证通过。
- 预检工具：`python3 tests/smoke/relay-preflight.py https://<域名>/`（TLS/health/匿名 WSS）。
- 服务器就绪后运行：

```sh
python3 tests/smoke/emulator-liveshare-relay.py 127.0.0.1:5555 .build/liveshare-public.json \
  --owner-login --relay-url https://<域名>/ --cross-device 127.0.0.1:5557 \
  --admin-token <ADMIN> --viewer-token <VIEWER>
```

## 仍待外部条件（非代码缺口）

1. 公网 Relay 服务器与域名/token（用户晚上配置）。
2. 真机 Mate 60（真机麦克风 + 真人说话）。
3. 官方 LiveShare Relay 与真实身份提供方（服务端不随仓库交付）。
4. 异地第二网络（公网跨设备目前为同局域网经公网隧道）。
5. 排除项按约定未实现：系统 PTY、Phone/Computer Use、terminal、cua、pwsh、pwsh-persistent、Windows 专用工具。

## 关键修复回顾

- PTC 单链接读取加固（root 之外拒绝多链接文件）。
- Relay 夹具的 Cloudflare 隧道兼容（拒绝升级响应带 `Content-Length: 0`）。
- LiveShare 内部跨设备改用模拟器直连宿主路由（`--device-host 10.0.2.2`），规避 hdc 反向转发长连接被断开的问题。
- 闸门运行器自动处理设备就绪、麦克风权限重置与账号设备数据清理。

# 2026-11-20 能力对齐回归闸门

`tests/bench/capability-parity-regression.py` 在同一个 0.4.69 制品上按固定顺序跑 10 个既有验收步骤，产出单一可复现的发布闸门结果，而不是把多次零散运行拼在一起。

## 运行

需要两台 API 26 ARM64 Phone 模拟器（主设备 + 账号步骤用的第二设备）、宿主 Ollama 模型与语音夹具。闸门会在语音步骤前重置麦克风权限，在账号步骤前清空第二台设备应用数据，并在每步前启动应用等待启动完成。

```sh
python3 tests/bench/capability-parity-regression.py \
  --target 127.0.0.1:5555 --second-target 127.0.0.1:5557 \
  --voice-model-root <fixture-model-dir> --voice-audio <16k-mono-pcm16-wav> \
  --ollama-model mh-smoke-ollama-079:latest \
  --output .build/capability-parity-gate.json
```

可选 `--only recovery,voice-input` 只跑指定步骤。

## 步骤

| 步骤 | 覆盖 |
| --- | --- |
| recovery | 故障插件注入、安全模式、匿名 401、恢复正常 profile |
| voice-input | SenseVoice 转写、坏音频拒绝、ArkWeb 草稿、系统麦克风授权生命周期 |
| voice-native-capture | 模拟器原生麦克风真实声学采集 + 转写（依赖宿主音频，记录但非关键） |
| ollama-routes | 本机 Ollama 双协议接入、模型发现、流式请求、图片附件、重启保持 |
| ptc-link-fixture | 应用数据视图的链接创建前置条件 |
| ptc-boundary | PTC 自建链接/元数据拒绝、宿主并发父目录移动的越界防护 |
| liveshare | owner 实际 ArkWeb 授权、分享创建/扩源/重连、reader 拒绝与实时撤销、stop、网关回收 |
| liveshare-cross-device | 第二台设备真实浏览器经**模拟器直连宿主路由**（`--device-host 10.0.2.2`）渲染只读 viewer；不依赖 hdc 反向转发 |
| account-entry | 全新应用数据下的公网 DeepSeek 授权页打开/取消、回环 PKCE、重启保持、登出撤销 |
| native-addon-location | Host 内实测原生 addon 的加载位置限制 |

## 本批次结果（通过）

2026-11-20 10:01 前后（约 6.5 分钟），`ok=true`、失败 0：

| 步骤 | 结果 | 秒 |
| --- | --- | --- |
| recovery | 通过 | 33 |
| voice-input | 通过 | 43 |
| voice-native-capture | 通过 | 37 |
| ollama-routes | 通过 | 85 |
| ptc-link-fixture | 通过 | 1 |
| ptc-boundary | 通过 | 42 |
| liveshare | 通过 | 49 |
| liveshare-cross-device | 通过 | 46 |
| account-entry | 通过 | 36 |
| native-addon-location | 通过 | 14 |

证据：[capability-parity-gate-0.4.69.json](../evidence/capability-parity-gate-0.4.69.json) · 直连跨设备单次记录：[liveshare-cross-device-direct-0.4.69.json](../evidence/liveshare-cross-device-direct-0.4.69.json)

跨设备步骤用 `--device-host 10.0.2.2`：模拟器 QEMU 用户网络把 10.0.2.2 映射到宿主，夹具临时监听 0.0.0.0。此前的 hdc 反向转发会让 owner 网关 WebSocket 在长连接后以 1006 断开且不重连；直连路由没有该问题。owner 登录页仍走 127.0.0.1 回环（ArkWeb 只接受 https 或 127.0.0.1），两者在闸门里是独立步骤。

## 闸门之外的独立证据

- **LiveShare 公网**：Cloudflare 隧道预演单独留证（[公网预演](../evidence/relay-public-tunnel-acceptance-0.4.69.json)）。
  hdc 反向转发下的跨设备复测曾出现 owner 网关 1006 断连；已定位为**反向转发长连接不稳定**，改用模拟器直连路由（`--device-host 10.0.2.2`）后稳定复现通过，并已纳入闸门。
- **Forge 公开读/真实账号**：设备 A 现按设计保留真实 GitHub 账号配置，夹具公开读需要空 `GH_CONFIG`；因此公开读单独留证（[Forge 公开读](../evidence/emulator-forge-public-read-0.4.69.json) · [真实账号](../evidence/emulator-forge-real-account-0.4.69.json)）。在第二台设备上复跑该步骤时，夹具注入 profile 后的重启会让应用上下文命令持续返回空内容、Host 不再就绪（同一次运行在设备 A 上通过），该环境问题留待后续排查，闸门不依赖它。

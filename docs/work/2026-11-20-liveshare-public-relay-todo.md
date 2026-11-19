# 公网 LiveShare Relay／真实身份提供方 TODO（待用户配置服务器）

2026-11-20。用户已确认：**有域名，暂时没有启动服务器，晚上回来配置**。在此之前本机双模拟器跨设备验收（`tests/smoke/emulator-liveshare-relay.py --owner-login --cross-device`）是该项当前上限，证据见 [LiveShare 跨设备](../evidence/emulator-liveshare-cross-device-0.4.69.json)。

## 已完成（本机）

- 自建测试 Relay 可向 owner 提供官方 viewer 页面与 `viewerCarrierScript`，第二台模拟器的真实浏览器读取共享会话（标题、历史、时间戳、只读提示）。
- Owner 实际 ArkWeb 分享授权与 PKCE、reader 侧未共享/管理接口拒绝、实时撤销与停止均通过。
- 公网必须 HTTPS：`apps/harmonyos/entry/src/main/ets/pages/Index.ets` 只接受 `https` 或 `http://127.0.0.1` 的 Relay 地址；WSS 在 owner gateway 中走裸 `WebSocket`，不经 DSH 代理。

## 服务器就绪后要做的事

1. **部署 Relay**：官方 Relay 服务端不随上游包或本仓库交付，需要在服务器上部署可用的 LiveShare Relay 实现（或继续用自建 Relay 作替代，并在证据里明确写「替代 Relay」）。
2. **HTTPS/WSS**：域名解析到服务器，公网 CA 证书（Let's Encrypt 等），反向代理支持 WebSocket Upgrade；owner gateway 心跳 25s、2 次丢 pong 自断，需要长连接配置。
3. **真实身份提供方**：注册 OAuth/OIDC client（client_id/secret/redirect_uri），Relay 侧接入真实登录与 actor 映射；ArkWeb 登录页必须是 https 或与 Relay 同源。
4. **测试改造**（当前均为 TODO）：
   - `tests/smoke/emulator-liveshare-relay.py` 增加 `--relay-url https://<domain>/...`，替代固定 `http://127.0.0.1:19769`。
   - 新增公网预检：HTTPS 证书 issuer/有效期、`/health`、WSS 注册帧、无凭证拒绝。
   - 第二台设备（或第二网络）用真实浏览器打开公网分享页；记录公网时延下的读预算/重连/心跳。
5. **验收证据命名**：`docs/evidence/emulator-liveshare-public-<version>.json`，明确区分自建 Relay 与官方 Relay。

## 预检工具（已实现并在本机验证）

公网 Relay 就绪后先跑：

```sh
python3 tests/smoke/relay-preflight.py https://<域名>/ --output .build/relay-preflight.json
```

检查项：HTTPS 证书链与主机名、`/health` 返回 200、匿名 WSS 升级 `/__tunnel_gateway__` 必须被 Relay 以 401/403 拒绝。工具在本机用「自签 TLS 反代 + Relay 夹具」做了正/负向自测（健康 200、匿名 WSS 401 通过；自签在系统信任下被拒；不可达地址被拒），证据见 [relay-preflight-self-test](../evidence/relay-preflight-self-test-0.4.69.json)。

本机自测命令：

```sh
python3 tests/smoke/relay-preflight.py --self-test --output .build/relay-preflight-self-test.json
```

## 复现基线命令（本机）

```sh
python3 tests/smoke/emulator-liveshare-relay.py 127.0.0.1:5555 .build/liveshare-owner-cross-device.json \
  --owner-login --cross-device 127.0.0.1:5557
```

服务器参数（域名、证书、OIDC client、部署方式）到位后，从本 TODO 的第 4 步继续。

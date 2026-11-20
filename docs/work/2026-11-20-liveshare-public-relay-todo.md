# 公网 LiveShare Relay／真实身份提供方 TODO（待用户配置服务器）

2026-11-20。用户已确认：**有域名，暂时没有启动服务器，晚上回来配置**。在此之前本机双模拟器跨设备验收（`tests/smoke/emulator-liveshare-relay.py --owner-login --cross-device`）是该项当前上限，证据见 [LiveShare 跨设备](../evidence/emulator-liveshare-cross-device-0.4.69.json)。

## 已完成（本机）

- 自建测试 Relay 可向 owner 提供官方 viewer 页面与 `viewerCarrierScript`，第二台模拟器的真实浏览器读取共享会话（标题、历史、时间戳、只读提示）。
- Owner 实际 ArkWeb 分享授权与 PKCE、reader 侧未共享/管理接口拒绝、实时撤销与停止均通过。
- 公网必须 HTTPS：`apps/harmonyos/entry/src/main/ets/pages/Index.ets` 只接受 `https` 或 `http://127.0.0.1` 的 Relay 地址；WSS 在 owner gateway 中走裸 `WebSocket`，不经 DSH 代理。

## 部署配方（已实现并在本机验证）

仓库新增 [deploy/liveshare-acceptance-relay](../../deploy/liveshare-acceptance-relay/README.md)：Dockerfile + docker-compose + nginx（含 WebSocket Upgrade、3600s 超时、32m 上传上限）+ certbot 步骤 + .env 模板。本机已验证：token 生效（旧夹具 token 被拒）、owner 登录页（env 与 argv 两种模式）、TLS 反代下预检通过（health 200、匿名 WSS 401、TLS 1.3）、compose YAML 可解析、nginx 关键指令齐全。证据：[relay-deployment-recipe](../evidence/relay-deployment-recipe-0.4.69.json)。Docker 镜像构建未在本机验证（本机 Docker daemon 未运行），需在服务器 `docker compose up -d --build` 后立即跑预检。

## 公网路径已用临时隧道预演（2026-11-20）

在等你的服务器期间，用 Cloudflare 临时隧道（cloudflared quick tunnel）把本机 Relay 暴露成公网 HTTPS 端点，跑通了完整公网路径：

- 预检通过：TLS 1.3、公共 CA（Google Trust Services）、`/health` 200、匿名 WSS 401；
- owner 在 ArkWeb 里对公网 URL 完成分享授权，分享创建/扩源/重连、reader 拒绝与实时撤销、stop、网关回收、profile 恢复全部通过；
- 第二台设备真实浏览器经公网 URL 加载 viewer 页面（18 个页面资源、10 次 `session/list`），渲染出共享会话标题与只读提示。

证据：[relay-public-tunnel-acceptance](../evidence/relay-public-tunnel-acceptance-0.4.69.json)。注意：Relay 仍是仓库夹具（替代 Relay），隧道 URL 已关闭，两台设备在同一局域网；**官方 Relay、你的域名部署和异地第二网络仍未验证**。

过程中发现一个兼容点：被拒绝的 WebSocket Upgrade 响应需要带 `Content-Length: 0`，否则 Cloudflare 边缘返回 500；Relay 夹具已修正并记录拒绝日志。

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

## 外部 Relay 模式（已实现并在本机验证）

验收脚本已支持外部 Relay：`--relay-url`（设备可见地址）、`--relay-call-url`（宿主调用地址，缺省同 `--relay-url`）、`--relay-host-port`（本机转发校验用）、`--admin-token`、`--viewer-token`。Relay 夹具新增部署环境变量：`MH_RELAY_HOST`、`MH_RELAY_PORT`、`MH_RELAY_VIEWER_TOKEN`、`MH_RELAY_ADMIN_TOKEN`、`MH_RELAY_OWNER_LOGIN`、`MH_RELAY_LOGIN_REDIRECT`、`MH_RELAY_VIEWER_CONFIG`。

本机用「独立启动的 Relay 夹具 + hdc rport 回环」验证了该路径（owner 授权、分享创建/扩源/重连、reader 拒绝与撤销、stop、网关回收、配置恢复全部通过；第二设备通过外部 URL 渲染出共享会话标题）。证据：[relay-external-url-validation](../evidence/relay-external-url-validation-0.4.69.json)。

公网地址就绪后，命令只需换成公网 URL（不再需要 `--relay-call-url`/`--relay-host-port`）：

```sh
python3 tests/smoke/relay-preflight.py https://<域名>/ --output .build/relay-preflight.json
python3 tests/smoke/emulator-liveshare-relay.py <target> .build/liveshare-public.json \
  --owner-login --relay-url https://<域名>/ --cross-device <second-target> \
  --admin-token <admin-token> --viewer-token <viewer-token>
```

已知待处理：本机 rport 回环下的跨设备组合出现过 `liveshareShares/stop → relay:unreachable` 的传输抖动（第二设备页面本身正常）；公网直连部署应改用真实网络路径再验收该断言。

## 复现基线命令（本机）

```sh
python3 tests/smoke/emulator-liveshare-relay.py 127.0.0.1:5555 .build/liveshare-owner-cross-device.json \
  --owner-login --cross-device 127.0.0.1:5557
```

服务器参数（域名、证书、OIDC client、部署方式）到位后，从本 TODO 的第 4 步继续。

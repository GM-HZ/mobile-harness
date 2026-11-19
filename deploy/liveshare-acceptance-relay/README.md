# 公网 LiveShare 验收 Relay 部署配方

这是**验收用** Relay：复用仓库内的 LiveShare Relay 夹具，在公网 HTTPS 域名后提供 owner 分享页、viewer 页面与 WSS 网关，用于跑"手机 → 公网 Relay → 第二设备 viewer"的跨网络验收。它**不是**官方 LiveShare Relay，身份是测试身份（合成 viewer token / 合成 owner 授权页），不要用于生产或真实用户。

## 前提

- 一台公网 Linux 服务器（Docker + Docker Compose；ARM64/x86 均可）
- 一个域名（A 记录指向服务器）
- 服务器防火墙放行 80/443
- 本仓库分支 `codex/harmonyos-capability-parity`（已推送）

## 1. 准备 token

```sh
cp .env.example .env
# 生成两个强随机值并写进 .env
openssl rand -hex 24   # MH_RELAY_VIEWER_TOKEN
openssl rand -hex 24   # MH_RELAY_ADMIN_TOKEN
```

`VIEWER_TOKEN` 是 viewer 读取凭证；`ADMIN_TOKEN` 用于测试端配置 viewer 页面与读取 Relay 日志，**不要泄露给非测试人员**。

## 2. 启动 Relay（仅监听 127.0.0.1:8080）

```sh
cd deploy/liveshare-acceptance-relay
docker compose --env-file .env up -d --build
curl -sS http://127.0.0.1:8080/health
```

## 3. 配置 nginx + 证书

```sh
sudo cp nginx/liveshare-acceptance.conf /etc/nginx/conf.d/liveshare-acceptance.conf
sudo sed -i 's/relay.example.com/<你的域名>/g' /etc/nginx/conf.d/liveshare-acceptance.conf
sudo mkdir -p /var/www/certbot
sudo nginx -t && sudo systemctl reload nginx
sudo certbot certonly --webroot -w /var/www/certbot -d <你的域名>
sudo nginx -t && sudo systemctl reload nginx
```

确认反向代理支持 WebSocket Upgrade（配置里已设置 `Upgrade`/`Connection` 与 3600s 超时）。

## 4. 预检（宿主机或开发机）

```sh
python3 tests/smoke/relay-preflight.py https://<你的域名>/ --output .build/relay-preflight.json
```

要求：TLS 证书验证通过、`/health` 200、匿名 WSS 升级返回 401/403。失败时先修证书/反代再继续。

## 5. 跑设备验收（开发机，两台模拟器或一台真机+一台模拟器）

```sh
python3 tests/smoke/emulator-liveshare-relay.py 127.0.0.1:5555 .build/liveshare-public.json \
  --owner-login --relay-url https://<你的域名>/ --cross-device 127.0.0.1:5557 \
  --admin-token <MH_RELAY_ADMIN_TOKEN> --viewer-token <MH_RELAY_VIEWER_TOKEN>
```

通过标准与本地跨设备一致：owner 在 ArkWeb 完成授权、分享创建/重连、reader 拒绝与撤销、第二台设备真实浏览器渲染共享会话标题与历史、stop 后 Relay 释放。

## 6. 验收后清理

```sh
cd deploy/liveshare-acceptance-relay
docker compose down
sudo rm -f /etc/nginx/conf.d/liveshare-acceptance.conf
sudo systemctl reload nginx
```

## 已知限制

- 身份是**合成身份**：viewer cookie token 与 owner 授权页均为夹具行为；真实 OAuth/OIDC 身份提供方不在本配方内。
- 官方 LiveShare Relay 服务端不在上游包与本仓库内，本配方是替代验收环境，证据中必须标注"替代 Relay"。
- 验收期间 Relay 日志包含会话诊断信息，结束后请销毁容器与 `.env`。

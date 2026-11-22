# 远程主机模式（A 直连 + B SSH 隧道）

日期：2026-11-22

## 1. 形态

- **A. direct**：手机不启动本地 Host，WebView 直接加载服务器 DSH Web（URL + token）。
  DSH 官方 CLI 明确拒绝 `--host 0.0.0.0`；直连需要用户自己在服务器侧做反向代理/隧道，
  并把代理 authority 加入 `--trusted-host`。本实现只负责客户端。
- **B. ssh**：手机本地 Host 启动一个 SSH 隧道，把 `127.0.0.1:19592` 转发到远端
  DSH Web 的 `127.0.0.1:19592`，WebView 仍访问本地回环（与 dsh-Go "只连接"思路一致）。

## 2. 实现

- `RemoteHosts.ets`：远程主机持久化（`files/remote-hosts.json`），支持 direct/ssh 字段；
- `RemoteHostsPage.ets`：远程主机列表、添加/删除/使用、切回本机；SSH 字段包括主机/端口/用户/
  密码/私钥/私钥口令/主机指纹/远端 DSH token；
- `DshEngine`：
  - 启动时读取选中主机；direct → 直接发布远程 BrowserSession，不启动本地 Host；
  - ssh → 写 `tmp/remote-host.json`，继续本地 Host 启动，由 Host 内 helper 建隧道；
- `dsh-client.cjs`：检测 `/tmp/remote-host.json`，kind=ssh 时加载
  `dsh-harmony-remote-ssh.cjs`，不再启动本地 DSH Web；
- `dsh-harmony-remote-ssh.cjs`：`ssh2` 连接（密码/私钥/指纹校验）、本地 19592 监听
  `forwardOut`、token→cookie 交换、写 `dsh-client-launch`；
- `runtime/harmonyos/dsh` 增加 `ssh2@1.17.0` 依赖；
- 设置页注入“远程主机”入口；远程模式下 WebView 右上角提供“主机”按钮切回/切换；
- 远程微调：WebView origin 白名单、麦克风 origin、远程会话标记。

## 3. 验证（模拟器）

- A direct：Mac 上 `dsh web --host 127.0.0.1 --port 19592 --trusted-host <LAN>` +
  TCP 反向代理到 0.0.0.0:19600；模拟器配置 `http://192.168.1.4:19600/?token=…`，
  WebView 成功加载远程 DSH UI（预览版说明页面）；
- B ssh：本地 fake SSH server（ssh2，端口 2222，密码 test）监听 tcpip forward 到
  127.0.0.1:19592；模拟器配置 SSH host=10.0.2.2:2222、user test、password test、token，
  App 启动本地 Host → SSH 隧道 → token/cookie → WebView 加载远程 DSH UI 成功。

## 4. 限制

1. A 需要服务器侧反向代理/隧道；DSH 不会监听 0.0.0.0；
2. B 的密码/私钥/token 目前明文存于 App 私有目录，后续应接系统安全存储；
3. SSH 主机指纹可选；未填写时接受首次主机密钥（后续应改为首次确认+固定）；
4. 远程断线重连、SSH 隧道断线恢复、远程模式后台保活尚未做；
5. 真机尚未验证（USB 设备在测试中断开），模拟器端到端已通过。

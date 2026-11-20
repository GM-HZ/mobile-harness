# 2026-11-19 0.4.69 能力补齐批次

整理本批次：把 `codex/harmonyos-package-management` 合并进 `main` 后，在独立 worktree 分支 `codex/harmonyos-capability-parity` 上继续完成 Codex 遗留的能力验收。应用版本 0.4.69（versionCode 76），运行时仍是鸿蒙原生 Node 24.14.1 与官方 npm DSH `0.2.2-rc.5`。

## 基线

- `main` 由 `e7d0e34` 快进到 `5ce5689`（`codex/harmonyos-package-management` 的 0.4.68 批次，239 个提交）。
- 本批次在 `.build/worktrees/harmonyos-capability-parity` 上开发；构建输入复用既有 `.build` 缓存。
- 未签名 HAP `.build/artifacts/harmonyos/dsh-mh-harmonyos-arm64-v0.4.69-unsigned.hap`，SHA-256 `8a8832751e6eebadd0ce5859e8a99f9d537cbfd04570cc38f33a4a68a54c4daf`。

## 代码改动

- `runtime/harmonyos/native/ptc-supervisor.c`：普通文件的读取与 stat 要求单链接（`st_nlink == 1`），与既有写规则一致；显式命名空间根授权保持原范围。符号链接和并发父目录仍由预打开根描述符加 `RESOLVE_NO_SYMLINKS` 的原子 `openat2` 解析保证不逃逸。

## 新增验收脚本

| 脚本 | 覆盖 |
| --- | --- |
| `tests/smoke/emulator-ollama.py` | 本机 Ollama 经标准设置接入，两种 OpenAI 兼容协议的模型发现、流式请求、工具目录、图片附件与重启保持 |
| `tests/smoke/emulator-ptc-link-fixture.py` | 应用数据视图能否创建符号链接／硬链接（PTC 链接压力场景前置条件） |
| `tests/smoke/emulator-ptc-boundary.py` | PTC 自建链接／改写打开被拒；临时宿主插件按门控把程序父目录移出授权根后读写全部拒绝且不写到根外 |
| `tests/smoke/emulator-liveshare-relay.py --cross-device` | 自建 Relay 向第二台模拟器的真实华为浏览器提供官方 viewer 页面，owner 实际 ArkWeb 授权后读取共享会话标题与历史 |
| `tests/smoke/emulator-native-addon-location.py` | 用随包 Inspector 在 Host 进程内测量原生 addon 的加载位置限制 |
| `tests/smoke/emulator-voice-input.py --native-mic-transcribe` | 模拟器原生麦克风真实声学采集：宿主外放合成普通话，设备录制并转写回同一句中文 |

夹具更新：`tests/smoke/fixtures/liveshare-relay.cjs`（viewer 页面组装、cookie 会话、context/health/资源转发、admin 配置与日志）、`tests/smoke/fixtures/inspector-host-eval.cjs`（Host 内表达式求值 CDP 客户端）。

## 证据

- [能力批次汇总](../evidence/emulator-capability-parity-0.4.69.json)：崩溃恢复、语音转写、本机 Ollama 路由、链接夹具前置条件、PTC 加固说明。
- [PTC 边界](../evidence/emulator-ptc-boundary-0.4.69.json)：自建链接被拒（`EPERM`／`EACCES`）、宿主并发移动父目录 4 轮全部 `ENOENT` 且被移出目录未被写入。
- [LiveShare 跨设备](../evidence/emulator-liveshare-cross-device-0.4.69.json)：owner 实际 ArkWeb 授权与 PKCE，第二台设备浏览器渲染共享会话标题、消息与时间戳，viewer RPC 200，界面只读且未调用所有者管理接口。
- [Forge 公开读](../evidence/emulator-forge-public-read-0.4.69.json)：宿主已认证 `gh` 经白名单网关读取公开 PR 的固定提交文件与提交列表。
- [账号入口](../evidence/emulator-account-fresh-0.4.69.json)：全新应用数据下打开公网 DeepSeek 授权页、取消、回环 PKCE 与登出撤销。
- [addon 加载位置](../evidence/emulator-native-addon-location-0.4.69.json)：同一库字节按安装目录 soname 加载成功，应用数据副本 `ERR_DLOPEN_FAILED`。
- [原生麦克风采集](../evidence/emulator-voice-native-capture-0.4.69.json)：模拟器原生麦克风录到宿主外放的已知语句（RMS 0.036、峰值 0.29）并由 SenseVoice 转写正确。
- [Forge 真实账号](../evidence/emulator-forge-real-account-0.4.69.json)：设备端真实 GitHub 设备授权、公开 PR 真实读取，以及临时私有仓库上的评审与 squash 合并写操作（仓库已删除）。
- [公网 Relay 预检自测](../evidence/relay-preflight-self-test-0.4.69.json)：HTTPS 证书、`/health` 与匿名 WSS 升级检查在本机自签反代上正负向通过。
- [外部 Relay URL 验证](../evidence/relay-external-url-validation-0.4.69.json)：验收脚本以外部启动的 Relay + 回环转发跑通 owner 授权、reader 拒绝/撤销、stop 与网关回收；第二设备经外部 URL 渲染共享会话。
- [公网 Relay 部署配方](../evidence/relay-deployment-recipe-0.4.69.json)：Docker/Compose + nginx（WebSocket Upgrade/长超时/上传上限）+ certbot 步骤；本机验证 token 门禁、owner 登录页两种模式、TLS 反代预检与 compose/nginx 配置项，并实际构建镜像、运行容器（healthcheck healthy、owner 登录页与预检通过）。

## 仍受外部条件阻塞

| 项 | 完成所需条件 |
| --- | --- |
| ~~Forge 真实账号同意与托管仓库写~~ | 已完成：真实账号 GM-HZ 授权、公开读取、临时私有仓库评审/合并，仓库已删除 |
| 语音真机采集与真人说话 | 模拟器已通过原生麦克风真实采集合成语句；真机（Mate 60 当前 HDC 离线）、正式签名 HAP、设备麦克风与真人说话仍待验 |
| 公网 LiveShare Relay | 用户已确认有域名、服务器稍后配置；待办见 [公网 Relay TODO](2026-11-20-liveshare-public-relay-todo.md) |
| 公网 LiveShare Relay、真实身份提供方、公网跨设备 | 官方 Relay 服务端不在上游包或本仓库内；需要外部部署、公网 CA/HTTPS 与真实 OAuth/OIDC client |
| 外部鸿蒙 addon 运行时装入主 Host | 平台限制：动态链接器只允许安装目录 `libs/arm64`；已给出替代路径（Alpine ARM64 musl addon、纯 JS、随 HAP 打包） |
| PTC 根内链接指向根外读取 | 应用数据视图拒绝创建链接，夹具不可得；读取侧已按单链接加固，拿到夹具即可复跑 |

## 复现命令

```sh
HARMONY_UNSIGNED=1 ./build.sh --package
hdc -t <target> install -r .build/artifacts/harmonyos/dsh-mh-harmonyos-arm64-v0.4.69-unsigned.hap
python3 tests/smoke/emulator-recovery.py <target> .build/recovery.json
python3 tests/smoke/emulator-voice-input.py <target> .build/voice.json --model-root <dir> --audio <16k-mono-pcm16-wav> --arkweb --native-mic
python3 tests/smoke/emulator-ollama.py <target> .build/ollama.json --model <model> --context-window 16384 --max-tokens 4096
python3 tests/smoke/emulator-ptc-link-fixture.py <target> .build/ptc-link.json
python3 tests/smoke/emulator-ptc-boundary.py <target> .build/ptc-boundary.json
python3 tests/smoke/emulator-liveshare-relay.py <target> .build/liveshare.json --owner-login --cross-device <second-target>
python3 tests/smoke/emulator-forge-github.py <target> .build/forge-public.json --public-read
python3 tests/smoke/emulator-native-addon-location.py <target> .build/addon-location.json
```

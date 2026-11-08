# 实验状态

> 历史实验记录。命令与结论适用于当时的环境和版本。原始日志与二进制保存在本机。现行结论见[研究索引](../../research/harmonyos-runtime.md)。

目标 DSH：官方 `fcc0ad462172522aaf5c93a7b2e01f6b9f0b0159`，Node 要求 `>=24.9.0`。自编译 Node 24.14.1 已在 Phone 模拟器实际到达 JS ready；真机目前展示 DSHM 原包，尚未测试新版独立运行时。

| 项目 | Phone 模拟器：Node 24.14.1 | Mate 60：Node 24.14.1 |
| --- | --- | --- |
| AArch64 HAP 内进程内 JS ready | PASS，实际版本 v24.14.1 | PASS：独立进程边界探针实际 v24.14.1 |
| SHA-256 加密、gzip 往返 | PASS | 未测 |
| 沙箱写/读/重命名/删除 | PASS | 未测 |
| worker 消息 | PASS | 未测 |
| Node HTTP 回环 100 次 | PASS | 未测 |
| 原生 fetch / WASM | FAIL：fetch failed；jitless 下 WASM undefined | 未测 |
| DSHM fetch shim：回环/POST Headers/SSE/abort | PASS；SSE 为 2 段 | 未测 |
| 官方目标 DSH Host、模型及会话 | 未测 | 未测 |
| DNS、垫片 HTTPS（example.com，未禁用 TLS 校验） | PASS | 未测 |
| 跨重启持久化、ArkUI→HTTP、性能与生命周期 | 未测 | 未测 |

本轮基线 HAP SHA-256 `d3eba6e7c5983bf6e531183611a4191c4b42c7f2785afe7183ec83976611d4c3`；结果及制品绑定见 `.build/harmony-node/emulator-node24-baseline-evidence.json`。桥接无进程级 SIGSYS fallback，libuv 源补丁在 OHOS 不使用可选 io_uring。

历史 Node 24.2 探路曾在模拟器与 Mate 60 通过文件/worker/HTTP，真机需实验性 SIGSYS 处理；fetch 失败。它不满足目标 DSH engines，不用于目标验收，原始记录保留在 work-log.md。

现成 DSHM 1.1.0 已在 Mate 60 安装并展示主界面，属于另一固定组合；未发送模型请求，不能代替官方目标 DSH 的验收。详情见 dshm-deployment.md。

垫片实验制品与结果见 `.build/harmony-node/emulator-node24-dshm-fetch-evidence.json`。这里只验证固定 DSHM fetch 垫片的部分 API，尚未覆盖 redirect/FormData/Request/Response 全面语义，未加载其他 DSHM 内部拦截钩子。P1 仍有未验项，不能宣布整体 P1、官方 DSH Host 或产品化通过。

DSHM 1.1.0 / Mate 60 的终端实测为 FAIL：busybox spawn EACCES，ash/bash/rg denied，PTY probe forkpty(3) failed。Node/UI ready 不代表 Shell 成功。准确制品、日志摘要与上游对照见 dshm-deployment.md。

2026-11-07 后续进程边界专项：Mate 60 普通 Debug HAP / Node 24.14.1 已完整到达 JS ready/done；ArkTS/Native 子进程能力查询 false；ptmx open EACCES；system sh stat/access/spawn EACCES；zsh ENOENT；**无 Shell 的系统 toybox echo 直接 spawn 退出 0**。这不是通用 Shell 成功，但也否定“所有系统工具 spawn 都失败”的过度概括。详细证据和后续路线见 shell-breakthrough-research.md。其他旧表格未测项保持未测。

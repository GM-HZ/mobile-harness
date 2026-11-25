# AGENTS.md — HarmonyOS App 宿主（`apps/harmonyos`）

ArkTS 层负责生命周期、rawfile 装配、模式/开关、把 Host 拉起来。**不要在这里写业务逻辑。**

## 规则

1. **DshEngine 只做装配**：解包层、复制 host 脚本、启动/重启 Host、故障恢复、模式文件
   （`proot-seccomp-*`、`legacy-proot.enabled`）。新功能应进 packages/runtime，而不是 ArkTS。
2. **rawfile 清单与 stage 对齐**：新增 rawfile 资产必须同步 `scripts/build/stage-harmonyos.py`；
   `DshEngine.ets` 只复制 stage 产出的文件。AppGallery 以 `appgallery.patch.yml` 为标记，使用原生归档并在用户同意隐私说明后启动。
3. **失败要可恢复**：启动失败要有 fallback（fast→compat）与用户可见错误；不要 silent catch。
4. **插件回滚**：只在正常 Host 就绪后保存配置快照。安全模式保留上一份快照，并在恢复页提供回滚和返回会话入口。
5. **安全**：不落盘凭据；不把 token/Account 信息写 hilog；权限申请最小化。后台常驻默认关闭，用户开启开关后再请求通知权限。远程连接入口只在 self/lab 开放。
6. **UI/客户端**：优先官方 DSH client plugin/bundle 扩展点；本目录只保留手机壳能力。
7. **验证**：改变启动流程必须跑真机 G3（verify/exec/overlay）+ 模拟器 nightly；证据落盘。
8. **运行时策略**：嵌入式 Node 的启动参数由原生层统一设置。ArkTS 的分块解包状态只用于装配、进度和启动计时。

## 检查清单

- [ ] `./build.sh --package` 成功、`variant_check` 通过；
- [ ] 真机可启动且 `mobile-harness-boot.json` 变 `pending:false`；
- [ ] 新 rawfile 已在 stage 与 DshEngine 两边登记。

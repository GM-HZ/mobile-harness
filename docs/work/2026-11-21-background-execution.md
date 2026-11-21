# 后台持续运行（HarmonyOS）实现记录

日期：2026-11-21
分支：`codex/harmonyos-experience`

## 1. dsh-Go 的做法（参考）

Android 端在 `app/android/.../runtime/DshService.kt` 使用**前台 Service**：
- `startForegroundService` + `startForeground(...)`，`foregroundServiceType="specialUse"`；
- `PARTIAL_WAKE_LOCK`、`ConnectivityManager` 网络回调、`START_STICKY` + `RuntimeServiceRecovery`；
- 常驻通知（低重要性、ongoing、带停止 action），安装/解包时显示进度；
- UI 与 runtime 解耦，Service 持有本地 DSH 进程。
iOS 端不是常驻 daemon，而是基于 audio/PiP/`BGContinuedProcessingTask` 的有边界保活，
只在系统实际接受时报告 `keepingAlive`。

## 2. HarmonyOS 限制与我们的实现

普通应用没有 Android `specialUse` 前台 Service：
- `taskKeeping` / `MODE_SPECIAL_SCENARIO_PROCESSING` 需要系统级 ACL 权限，普通应用不可用；
- 可用长时任务类型必须匹配声明的场景；`dataTransfer` 是普通应用可申请、最接近"后台运行本地服务"的类型；
- `KEEP_BACKGROUND_RUNNING` 是 normal 级 system_grant 权限。

实现（`apps/harmonyos/entry`）：
- `module.json5`：
  - `requestPermissions` 增加 `ohos.permission.KEEP_BACKGROUND_RUNNING`；
  - `EntryAbility` 增加 `backgroundModes: ["dataTransfer"]`；
- 新增 `runtime/BackgroundKeeper.ets`：
  - Host ready 后通过 `backgroundTaskManager.startBackgroundRunning(context, DATA_TRANSFER, wantAgent)` 申请长时任务；
  - 每 60s 调用 `updateBackgroundRunning(context, ['dataTransfer'])` 尝试续期；
  - 每 5s 写 `files/background-heartbeat.json`，用于验证后台进程是否仍在运行；
  - 提供 `stop()`，后续可接入 UI 的"停止后台运行"。
- `DshEngine.runNative` 在 loopback ready 后启动 keeper。

## 3. 验证

- 申请后系统日志：`CONTINUOUS_TASK ... background task mode: 1`（dataTransfer），heartbeat 文件生成；
- 按 Home 退后台 + Power 锁屏后：进程 pid 保持，heartbeat 持续更新（短时验证）；
- 10 分钟级后台持久性验证在长跑任务中记录；
- 证据/截图待补：后台 heartbeat、通知栏截图。

## 4. 已知限制

1. `dataTransfer` 是"数据传输"语义，系统对 10 分钟无进度会取消；当前用 60s 续期尝试规避，
   需要 10min 真机验证确认；
2. 通知由系统长时任务通知提供，尚未做自定义"停止任务"action；
3. 设备省电策略/厂商电池优化仍可能压制；后续加设置引导；
4. store 上架合规风险（当前阶段不考虑上架）；
5. 若要真正无限制常驻，需要 `KEEP_BACKGROUND_RUNNING_SYSTEM`/special scenario ACL 或云端执行。

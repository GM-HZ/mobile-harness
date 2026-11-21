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

## 3. 验证（真机 Mate 60）

- 申请后系统日志：`CONTINUOUS_TASK ... background task mode: 1`（dataTransfer），heartbeat 文件生成；
- 仅长时任务时：后台 heartbeat 到第 9 分钟正常，第 10 分钟进程被系统回收（dataTransfer 无进度取消规则），
  随后被系统重新拉起（新 pid，Host 会重建）；
- 增加 **`BACKGROUND_USER_IDLE` running lock** 后（`ohos.permission.RUNNING_LOCK` + `hold(-1)`）：
  - Home 退后台连续 **14 分钟** pid 不变、heartbeat 每 5s 持续更新；
  - Power 锁屏 60s 后 heartbeat 仍更新，pid 不变；
  - 回前台后 boot 仍为 normal、同一 pid，Host 可继续服务；
- 证据：`background-heartbeat.json` 时间序列（见提交记录/设备文件）。

## 4. 已知限制

1. `dataTransfer` 是"数据传输"语义，10 分钟无进度会被取消；当前用 **running lock + cancel/suspend 事件重试**
   保持进程存活（实测 14 分钟）。更长时间（小时级）仍需持续验证；
2. 进程存活依赖 running lock；设备厂商省电策略仍可能干预；
3. 通知由系统长时任务通知提供，尚未做自定义"停止任务"action；
4. store 上架合规风险（当前阶段不考虑上架）；
5. 真正"系统保证永久常驻"仍需 `KEEP_BACKGROUND_RUNNING_SYSTEM`/special scenario ACL 或云端执行。


## 5. 自定义通知、后台开关与长时 soak

- BackgroundKeeper 发布常驻通知（`SERVICE_INFORMATION` slot、`isOngoing`），带
  **"停止后台"** action；action 的 WantAgent 回到 EntryAbility，`onCreate/onNewWant` 识别
  `stopBackground` 参数并释放 running lock/长时任务；
- 发布前调用 `notificationManager.requestEnableNotification(context)`，首次使用会请求通知授权；
- 恢复页新增 **"后台常驻"** Toggle：状态持久化到 `files/background-enabled.json`，
  关闭时释放 running lock + 长时任务，下次启动按设置决定是否恢复；
- 真机 soak：开启 running lock 后连续 **35 分钟**后台运行，pid 不变、heartbeat 每 5s 更新；
  回前台 boot normal；
- 通知与停止 action 的端到端点击验证受设备锁屏限制，尚未完成（代码已构建通过）。

证据/限制：dataTransfer 仍需 running lock 兜底；厂商省电策略、通知授权、上架合规另算。

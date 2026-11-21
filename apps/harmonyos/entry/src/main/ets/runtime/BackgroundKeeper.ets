import { common, wantAgent, WantAgent } from '@kit.AbilityKit';
import { backgroundTaskManager } from '@kit.BackgroundTasksKit';
import { runningLock } from '@kit.BasicServicesKit';
import { fileIo } from '@kit.CoreFileKit';
import { util } from '@kit.ArkTS';
import { hilog } from '@kit.PerformanceAnalysisKit';

type CancelHandler = (info: backgroundTaskManager.ContinuousTaskCancelInfo) => void;
type SuspendHandler = (info: backgroundTaskManager.ContinuousTaskSuspendInfo) => void;
type ActiveHandler = (info: backgroundTaskManager.ContinuousTaskActiveInfo) => void;

/**
 * Keeps the local Harness process alive while the app is in the background.
 *
 * HarmonyOS has no arbitrary "specialUse" foreground service for normal apps.
 * The closest capability is a continuous task; this uses the dataTransfer mode
 * (available to normal apps with KEEP_BACKGROUND_RUNNING) and records a
 * heartbeat so background execution can be verified on device.
 */
export class BackgroundKeeper {
  private started: boolean = false;
  private refreshTimer: number = -1;
  private heartbeatTimer: number = -1;
  private retryTimer: number = -1;
  private userStopped: boolean = false;
  private context?: common.UIAbilityContext;
  private cancelHandler?: CancelHandler;
  private suspendHandler?: SuspendHandler;
  private activeHandler?: ActiveHandler;
  private powerLock?: runningLock.RunningLock;

  async start(context: common.UIAbilityContext): Promise<boolean> {
    if (this.started) return true;
    this.userStopped = false;
    this.context = context;
    try {
      const info: wantAgent.WantAgentInfo = {
        wants: [{ bundleName: context.abilityInfo.bundleName, abilityName: context.abilityInfo.name }],
        actionType: wantAgent.OperationType.START_ABILITY,
        requestCode: 0,
      };
      const agent: WantAgent = await wantAgent.getWantAgent(info);
      await backgroundTaskManager.startBackgroundRunning(
        context, backgroundTaskManager.BackgroundMode.DATA_TRANSFER, agent);
      this.started = true;
      await this.acquirePowerLock();
      this.startHeartbeat(context);
      this.registerEvents();
      this.refreshTimer = setInterval(() => { this.refresh(context); }, 60000);
      hilog.info(0xD005, 'DSHClient', 'background continuous task started');
      return true;
    } catch (error) {
      hilog.warn(0xD005, 'DSHClient', 'background continuous task unavailable: %{public}s', String(error));
      return false;
    }
  }

  async stop(context: common.UIAbilityContext): Promise<void> {
    this.userStopped = true;
    if (!this.started) return;
    this.started = false;
    this.unregisterEvents();
    if (this.retryTimer >= 0) {
      clearTimeout(this.retryTimer);
      this.retryTimer = -1;
    }
    if (this.refreshTimer >= 0) {
      clearInterval(this.refreshTimer);
      this.refreshTimer = -1;
    }
    if (this.heartbeatTimer >= 0) {
      clearInterval(this.heartbeatTimer);
      this.heartbeatTimer = -1;
    }
    try {
      await this.releasePowerLock();
      await backgroundTaskManager.stopBackgroundRunning(context);
    } catch (error) {
      hilog.warn(0xD005, 'DSHClient', 'background continuous task stop failed: %{public}s', String(error));
    }
  }

  private async acquirePowerLock(): Promise<void> {
    try {
      if (!runningLock.isSupported(runningLock.RunningLockType.BACKGROUND_USER_IDLE)) {
        hilog.warn(0xD005, 'DSHClient', 'background running lock not supported');
        return;
      }
      this.powerLock = await runningLock.create('dsh-background-runtime',
        runningLock.RunningLockType.BACKGROUND_USER_IDLE);
      this.powerLock.hold(-1);
      hilog.info(0xD005, 'DSHClient', 'background running lock acquired');
    } catch (error) {
      hilog.warn(0xD005, 'DSHClient', 'background running lock unavailable: %{public}s', String(error));
    }
  }

  private async releasePowerLock(): Promise<void> {
    try {
      this.powerLock?.unhold();
    } catch (error) {
      hilog.warn(0xD005, 'DSHClient', 'background running lock release failed');
    }
    this.powerLock = undefined;
  }

  private refresh(context: common.UIAbilityContext): void {
    backgroundTaskManager.updateBackgroundRunning(context, ['dataTransfer']).catch((error: Error) => {
      hilog.warn(0xD005, 'DSHClient', 'background task refresh failed: %{public}s', String(error));
    });
  }

  private registerEvents(): void {
    this.cancelHandler = (info) => {
      hilog.warn(0xD005, 'DSHClient', 'background task cancelled reason=%{public}d detail=%{public}d',
        info.reason, info.detailedReason ?? -1);
      this.scheduleRetry();
    };
    this.suspendHandler = (info) => {
      hilog.warn(0xD005, 'DSHClient', 'background task suspended reason=%{public}d', info.suspendReason);
    };
    this.activeHandler = () => {
      hilog.info(0xD005, 'DSHClient', 'background task active');
    };
    backgroundTaskManager.on('continuousTaskCancel', this.cancelHandler);
    backgroundTaskManager.on('continuousTaskSuspend', this.suspendHandler);
    backgroundTaskManager.on('continuousTaskActive', this.activeHandler);
  }

  private unregisterEvents(): void {
    if (this.cancelHandler) backgroundTaskManager.off('continuousTaskCancel', this.cancelHandler);
    if (this.suspendHandler) backgroundTaskManager.off('continuousTaskSuspend', this.suspendHandler);
    if (this.activeHandler) backgroundTaskManager.off('continuousTaskActive', this.activeHandler);
    this.cancelHandler = undefined;
    this.suspendHandler = undefined;
    this.activeHandler = undefined;
  }

  private scheduleRetry(): void {
    if (this.retryTimer >= 0 || this.userStopped || !this.context) return;
    this.retryTimer = setTimeout(() => {
      this.retryTimer = -1;
      const context = this.context;
      if (!context || this.userStopped) return;
      hilog.info(0xD005, 'DSHClient', 'background task retry');
      this.started = false;
      this.start(context);
    }, 3000);
  }

  private startHeartbeat(context: common.UIAbilityContext): void {
    const write = () => {
      try {
        const path = context.filesDir + '/background-heartbeat.json';
        const body = JSON.stringify({ at: Date.now(), pid: 0 }) + '\n';
        const file = fileIo.openSync(path,
          fileIo.OpenMode.WRITE_ONLY | fileIo.OpenMode.CREATE | fileIo.OpenMode.TRUNC);
        const payload = new util.TextEncoder().encodeInto(body);
        try { fileIo.writeSync(file.fd, payload.buffer as ArrayBuffer); } finally { fileIo.closeSync(file); }
      } catch (error) {
        hilog.warn(0xD005, 'DSHClient', 'background heartbeat failed');
      }
    };
    write();
    this.heartbeatTimer = setInterval(write, 5000);
  }
}

export const backgroundKeeper = new BackgroundKeeper();

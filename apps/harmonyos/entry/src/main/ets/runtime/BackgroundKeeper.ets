import { common, wantAgent, WantAgent } from '@kit.AbilityKit';
import { backgroundTaskManager } from '@kit.BackgroundTasksKit';
import { fileIo } from '@kit.CoreFileKit';
import { util } from '@kit.ArkTS';
import { hilog } from '@kit.PerformanceAnalysisKit';

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

  async start(context: common.UIAbilityContext): Promise<boolean> {
    if (this.started) return true;
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
      this.startHeartbeat(context);
      this.refreshTimer = setInterval(() => { this.refresh(context); }, 60000);
      hilog.info(0xD005, 'DSHClient', 'background continuous task started');
      return true;
    } catch (error) {
      hilog.warn(0xD005, 'DSHClient', 'background continuous task unavailable: %{public}s', String(error));
      return false;
    }
  }

  async stop(context: common.UIAbilityContext): Promise<void> {
    if (!this.started) return;
    this.started = false;
    if (this.refreshTimer >= 0) {
      clearInterval(this.refreshTimer);
      this.refreshTimer = -1;
    }
    if (this.heartbeatTimer >= 0) {
      clearInterval(this.heartbeatTimer);
      this.heartbeatTimer = -1;
    }
    try {
      await backgroundTaskManager.stopBackgroundRunning(context);
    } catch (error) {
      hilog.warn(0xD005, 'DSHClient', 'background continuous task stop failed: %{public}s', String(error));
    }
  }

  private refresh(context: common.UIAbilityContext): void {
    backgroundTaskManager.updateBackgroundRunning(context, ['dataTransfer']).catch((error: Error) => {
      hilog.warn(0xD005, 'DSHClient', 'background task refresh failed: %{public}s', String(error));
    });
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

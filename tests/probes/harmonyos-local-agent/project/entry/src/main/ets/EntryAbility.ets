import { UIAbility, Want } from '@kit.AbilityKit';
import { window } from '@kit.ArkUI';
import { hilog } from '@kit.PerformanceAnalysisKit';
import probe from 'libmhllamaprobe.so';

export default class EntryAbility extends UIAbility {
  onCreate(want: Want): void {
    this.handleRequest(want);
  }

  onNewWant(want: Want): void {
    this.handleRequest(want);
  }

  onWindowStageCreate(stage: window.WindowStage): void {
    stage.loadContent('pages/Index');
  }

  private handleRequest(want: Want): void {
    const operation = want.parameters?.['operation'];
    if (operation === 'start') {
      hilog.info(0xD005, 'MhLlamaProbe', 'Process start: %{public}d', probe.start(this.context.filesDir));
    } else if (operation === 'status') {
      hilog.info(0xD005, 'MhLlamaProbe', 'Process status: %{public}d', probe.status());
    }
  }
}

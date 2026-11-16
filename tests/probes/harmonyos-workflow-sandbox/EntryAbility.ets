import { UIAbility } from '@kit.AbilityKit';
import { window } from '@kit.ArkUI';
import { hilog } from '@kit.PerformanceAnalysisKit';
import probe from 'libworkflowprobe.so';

export default class EntryAbility extends UIAbility {
  onCreate(): void {
    hilog.info(0xD005, 'WorkflowSandboxProbe', '%{public}s', probe.run());
  }
  onWindowStageCreate(stage: window.WindowStage): void {
    stage.loadContent('pages/Index');
  }
}

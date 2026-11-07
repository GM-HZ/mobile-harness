import { UIAbility } from '@kit.AbilityKit';
import { window } from '@kit.ArkUI';
import { hilog } from '@kit.PerformanceAnalysisKit';

export default class EntryAbility extends UIAbility {
  onForeground(): void {
    hilog.info(0xD005, 'DSHClient', 'ability foreground');
  }
  onBackground(): void {
    hilog.info(0xD005, 'DSHClient', 'ability background');
  }
  onWindowStageCreate(stage: window.WindowStage): void {
    stage.loadContent('pages/Index');
  }
}

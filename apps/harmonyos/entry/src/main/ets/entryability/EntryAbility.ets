import { AbilityConstant, UIAbility, Want } from '@kit.AbilityKit';
import { backgroundKeeper } from '../runtime/BackgroundKeeper';
import { window } from '@kit.ArkUI';
import { hilog } from '@kit.PerformanceAnalysisKit';

export default class EntryAbility extends UIAbility {
  onCreate(want: Want, launchParam: AbilityConstant.LaunchParam): void {
    this.handleStop(want?.parameters?.stopBackground === true);
  }

  onNewWant(want: Want): void {
    this.handleStop(want?.parameters?.stopBackground === true);
  }

  private handleStop(stop: boolean): void {
    if (stop) {
      hilog.info(0xD005, 'DSHClient', 'background stop action requested');
      void backgroundKeeper.stop(this.context);
    }
  }

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

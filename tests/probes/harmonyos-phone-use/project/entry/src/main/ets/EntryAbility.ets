import { UIAbility } from '@kit.AbilityKit';
import { window } from '@kit.ArkUI';
import { BusinessError } from '@kit.BasicServicesKit';
import { hilog } from '@kit.PerformanceAnalysisKit';

export default class EntryAbility extends UIAbility {
  onForeground(): void {
    hilog.info(0xD005, 'PhoneUseProbe', 'probe in foreground');
  }

  onBackground(): void {
    hilog.info(0xD005, 'PhoneUseProbe', 'probe in background');
  }

  onWindowStageCreate(stage: window.WindowStage): void {
    try {
      stage.loadContent('pages/Index').catch((err: BusinessError) => {
        hilog.error(0xD005, 'PhoneUseProbe', 'loadContent failed: %{public}d', err.code);
      });
    } catch (err) {
      hilog.error(0xD005, 'PhoneUseProbe', 'loadContent failed: %{public}d', (err as BusinessError).code);
    }
  }
}

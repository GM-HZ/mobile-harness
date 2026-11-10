import { abilityAccessCtrl, common } from '@kit.AbilityKit';
import { accessibility } from '@kit.AccessibilityKit';
import { screenshot } from '@kit.ArkUI';
import { BusinessError } from '@kit.BasicServicesKit';
import { inputEventClient } from '@kit.InputKit';
import { hilog } from '@kit.PerformanceAnalysisKit';

@Entry
@Component
struct Index {
  @State extensionStatus: string = 'Extension status pending';
  @State captureStatus: string = 'Capture requires user approval';
  @State capturing: boolean = false;
  @State opening: boolean = false;
  @State launchStatus: string = 'Test page has not been opened';

  aboutToAppear(): void {
    this.checkExtension();
    this.checkTouchController();
  }

  private async checkTouchController(): Promise<void> {
    try {
      await inputEventClient.createTouchController();
      hilog.info(0xD005, 'PhoneUseProbe', 'touch controller created');
    } catch (err) {
      const code = (err as BusinessError).code;
      hilog.info(0xD005, 'PhoneUseProbe', 'touch controller error %{public}s', String(code));
    }
  }

  private checkExtension(): void {
    try {
      const bundleName = (this.getUIContext().getHostContext() as common.UIAbilityContext).abilityInfo.bundleName;
      const installed = accessibility.getAccessibilityExtensionListSync('all', 'install')
        .find(info => info.bundleName === bundleName && info.name === 'ProbeAccessibility');
      const enabled = accessibility.getAccessibilityExtensionListSync('all', 'enable')
        .some(info => info.bundleName === bundleName && info.name === 'ProbeAccessibility');
      const capabilities = installed?.capabilities.join(',') ?? '';
      this.extensionStatus = `Accessibility installed=${installed !== undefined}, enabled=${enabled}, caps=${capabilities}`;
    } catch (err) {
      this.extensionStatus = `Accessibility query error ${(err as BusinessError).code}`;
    }
    hilog.info(0xD005, 'PhoneUseProbe', '%{public}s', this.extensionStatus);
  }

  private async capture(): Promise<void> {
    this.capturing = true;
    try {
      const context = this.getUIContext().getHostContext() as common.UIAbilityContext;
      const permission = await abilityAccessCtrl.createAtManager()
        .requestPermissionsFromUser(context, ['ohos.permission.CUSTOM_SCREEN_CAPTURE']);
      if (permission.authResults[0] !== 0) {
        this.captureStatus = `Capture permission result ${permission.authResults[0]}`;
        return;
      }
      const frame = await screenshot.capture({ displayId: 0 });
      try {
        this.captureStatus = `Capture succeeded: ${frame.getPixelBytesNumber()} pixel bytes`;
      } finally {
        await frame.release();
      }
    } catch (err) {
      this.captureStatus = `Capture error ${(err as BusinessError).code}`;
    } finally {
      hilog.info(0xD005, 'PhoneUseProbe', '%{public}s', this.captureStatus);
      this.capturing = false;
    }
  }

  private async openTestPage(): Promise<void> {
    this.opening = true;
    try {
      const context = this.getUIContext().getHostContext() as common.UIAbilityContext;
      await context.startAbility({
        bundleName: 'com.huawei.hmos.settings',
        abilityName: 'com.huawei.hmos.settings.MainAbility'
      });
      this.launchStatus = 'Settings launch accepted';
    } catch (err) {
      this.launchStatus = `Settings launch error ${(err as BusinessError).code}`;
    } finally {
      hilog.info(0xD005, 'PhoneUseProbe', '%{public}s', this.launchStatus);
      this.opening = false;
    }
  }

  build() {
    Column({ space: 16 }) {
      Text('Phone Use Probe').fontSize(24)
      Text(this.extensionStatus)
      Button('Refresh accessibility status').onClick(() => this.checkExtension())
      Text(this.captureStatus)
      Button('Check screen capture').enabled(!this.capturing && !this.opening).onClick(() => this.capture())
      Text(this.launchStatus)
      Button('Open Settings test page').enabled(!this.capturing && !this.opening).onClick(() => this.openTestPage())
    }
    .width('100%')
    .padding(24)
  }
}

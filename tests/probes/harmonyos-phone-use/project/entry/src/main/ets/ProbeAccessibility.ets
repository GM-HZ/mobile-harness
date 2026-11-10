import { AccessibilityExtensionAbility } from '@kit.AccessibilityKit';
import { hilog } from '@kit.PerformanceAnalysisKit';

export default class ProbeAccessibility extends AccessibilityExtensionAbility {
  onConnect(): void {
    hilog.info(0xD005, 'PhoneUseProbe', 'accessibility connected');
  }

  onDisconnect(): void {
    hilog.info(0xD005, 'PhoneUseProbe', 'accessibility disconnected');
  }
}

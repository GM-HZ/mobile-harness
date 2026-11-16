import { UIAbility } from '@kit.AbilityKit';
import { window } from '@kit.ArkUI';
import { hilog } from '@kit.PerformanceAnalysisKit';
import { fileIo } from '@kit.CoreFileKit';
import probe from 'libworkflowprobe.so';

export default class EntryAbility extends UIAbility {
  onCreate(): void {
    hilog.info(0xD005, 'WorkflowSandboxProbe', '%{public}s', probe.run());
    const entry = this.context.filesDir + '/workflow-worker.cjs';
    const content = this.context.resourceManager.getRawFileContentSync('workflow-worker.cjs');
    const file = fileIo.openSync(entry, fileIo.OpenMode.CREATE | fileIo.OpenMode.WRITE_ONLY | fileIo.OpenMode.TRUNC);
    try {
      fileIo.writeSync(file.fd, content.buffer);
    } finally {
      fileIo.closeSync(file.fd);
    }
    hilog.info(0xD005, 'WorkflowNodeProbe', '%{public}s', probe.runNode(entry));
  }
  onWindowStageCreate(stage: window.WindowStage): void {
    stage.loadContent('pages/Index');
  }
}

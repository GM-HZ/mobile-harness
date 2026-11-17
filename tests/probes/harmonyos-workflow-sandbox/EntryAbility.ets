import { UIAbility } from '@kit.AbilityKit';
import { window } from '@kit.ArkUI';
import { hilog } from '@kit.PerformanceAnalysisKit';
import { fileIo } from '@kit.CoreFileKit';
import probe from 'libworkflowprobe.so';

export default class EntryAbility extends UIAbility {
  onCreate(): void {
    hilog.info(0xD005, 'WorkflowSandboxProbe', '%{public}s', probe.run());
    hilog.info(0xD005, 'PtcFilesProbe', '%{public}s', probe.runFiles(this.context.filesDir));
    const amaro = this.context.resourceManager.getRawFileContentSync('amaro-probe-enabled');
    if (amaro[0] === 49) {
      for (const name of ['amaro.cjs', 'instantiate.cjs', 'reference.json', 'verify.cjs']) {
        this.copyAsset(name);
      }
    }
    hilog.info(0xD005, 'WorkflowNodeProbe', '%{public}s', probe.runNode(this.copyAsset('workflow-worker.cjs')));
  }
  private copyAsset(name: string): string {
    const destination = this.context.filesDir + '/' + name;
    const content = this.context.resourceManager.getRawFileContentSync(name);
    const file = fileIo.openSync(destination, fileIo.OpenMode.CREATE | fileIo.OpenMode.WRITE_ONLY | fileIo.OpenMode.TRUNC);
    try {
      fileIo.writeSync(file.fd, content.buffer);
    } finally {
      fileIo.closeSync(file.fd);
    }
    return destination;
  }
  onWindowStageCreate(stage: window.WindowStage): void {
    stage.loadContent('pages/Index');
  }
}

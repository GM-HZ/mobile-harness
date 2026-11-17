import { UIAbility } from '@kit.AbilityKit';
import { window } from '@kit.ArkUI';
import { hilog } from '@kit.PerformanceAnalysisKit';
import { fileIo } from '@kit.CoreFileKit';
import probe from 'libpoc.so';
export default class EntryAbility extends UIAbility {
  onCreate(): void {
    const path = this.context.filesDir + '/native-wasm.cjs';
    const content = this.context.resourceManager.getRawFileContentSync('native-wasm.cjs');
    const file = fileIo.openSync(path, fileIo.OpenMode.CREATE | fileIo.OpenMode.WRITE_ONLY | fileIo.OpenMode.TRUNC);
    try { fileIo.writeSync(file.fd, content.buffer); } finally { fileIo.closeSync(file.fd); }
    const report = probe.run(path);
    hilog.info(0xD005, 'NativeWasmProbe', '%{public}s', report);
    const result = fileIo.openSync(this.context.filesDir + '/result.json', fileIo.OpenMode.CREATE | fileIo.OpenMode.WRITE_ONLY | fileIo.OpenMode.TRUNC);
    try { fileIo.writeSync(result.fd, report); } finally { fileIo.closeSync(result.fd); }
  }
  onWindowStageCreate(stage: window.WindowStage): void { stage.loadContent('pages/Index'); }
}

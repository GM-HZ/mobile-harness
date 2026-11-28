import { common } from '@kit.AbilityKit';
import { localInference, LocalInferenceState } from '../runtime/LocalInference';
import { LOCAL_MODELS, LocalModelDownloadState, LocalModelSpec, LocalModelStore } from '../runtime/LocalModelStore';

@Component
export struct LocalInferencePage {
  onClose: () => void = () => {};
  @State inference: LocalInferenceState = { activeModel: '', preferLocal: false, busy: false, message: '' };
  @State installed: string[] = [];
  @State download: LocalModelDownloadState = {
    modelId: '', phase: 'starting', receivedBytes: 0, totalBytes: 0, message: ''
  };
  @State downloading: string = '';
  @State error: string = '';
  private store?: LocalModelStore;
  private models: LocalModelSpec[] = Array.from(LOCAL_MODELS);

  aboutToAppear(): void {
    this.store = new LocalModelStore(this.getUIContext().getHostContext() as common.UIAbilityContext);
    this.refresh();
  }

  private refresh(): void {
    this.inference = localInference.snapshot();
    this.installed = LOCAL_MODELS.filter(model => !!this.store?.installedPath(model.id)).map(model => model.id);
  }

  private async run(action: () => Promise<void>): Promise<void> {
    this.error = '';
    try {
      const operation = action();
      this.refresh();
      await operation;
    } catch (error) {
      this.error = error instanceof Error ? error.message : '无法应用本地推理设置';
    } finally {
      this.refresh();
    }
  }

  private async fetch(modelId: string): Promise<void> {
    if (!this.store || this.downloading || this.inference.busy) return;
    this.error = '';
    this.downloading = modelId;
    this.download = { modelId, phase: 'starting', receivedBytes: 0, totalBytes: 0, message: '' };
    try {
      await this.store.download(modelId, state => { this.download = state; });
    } catch (error) {
      if (this.download?.phase !== 'cancelled') {
        this.error = error instanceof Error ? error.message : '下载失败，请重试';
      }
    } finally {
      this.downloading = '';
      this.refresh();
    }
  }

  private progressPercent(): number {
    const state = this.download;
    if (!state || !state.totalBytes) return 0;
    return Math.min(100, Math.round(100 * state.receivedBytes / state.totalBytes));
  }

  @Builder
  private modelRow(model: LocalModelSpec) {
    Column({ space: 8 }) {
      Row({ space: 12 }) {
        Column({ space: 4 }) {
          Text(model.label).fontSize(16).fontWeight(FontWeight.Medium).fontColor('#132841')
          Text((model.bytes / 1000000000).toFixed(2) + ' GB  ·  ' +
            (this.inference.activeModel === model.id ? '当前模型' : (this.installed.includes(model.id) ? '已下载' : '未下载')))
            .fontSize(13).fontColor('#4D6279')
        }.alignItems(HorizontalAlign.Start).layoutWeight(1)
        if (this.downloading === model.id) {
          Button('取消').onClick(() => { void this.store?.cancel(); })
        } else if (this.installed.includes(model.id)) {
          Button(this.inference.activeModel === model.id ? '运行中' : '使用此模型')
            .enabled(!this.inference.busy && !this.downloading && this.inference.activeModel !== model.id)
            .onClick(() => { void this.run(() => localInference.activate(model.id)); })
        } else {
          Button('下载').enabled(!this.inference.busy && !this.downloading)
            .onClick(() => { void this.fetch(model.id); })
        }
      }.width('100%')
      if (this.downloading === model.id && this.download?.modelId === model.id) {
        Progress({ value: this.progressPercent(), total: 100, type: ProgressType.Linear }).width('100%')
        Text(this.download?.phase === 'verifying' ? '正在校验模型…' : this.progressPercent() + '%')
          .fontSize(13).fontColor('#4D6279').width('100%')
      }
    }.padding(14).width('100%').alignItems(HorizontalAlign.Start)
      .border({ width: 1, color: '#D6E3F1', radius: 14 })
  }

  build() {
    Scroll() {
      Column({ space: 14 }) {
        Button('返回会话').enabled(!this.inference.busy && !this.downloading).onClick(this.onClose)
        Text('本地推理').fontSize(27).fontWeight(FontWeight.Bold).fontColor('#132841')
        Text('模型通过网络下载，校验后可在本机运行。一次加载一个模型。')
          .fontSize(14).fontColor('#4D6279')
        Row({ space: 12 }) {
          Column({ space: 5 }) {
            Text('优先使用本地推理').fontSize(16).fontWeight(FontWeight.Medium).fontColor('#132841')
            Text('为新会话设置已启动的本地模型。').fontSize(13).fontColor('#4D6279')
          }.alignItems(HorizontalAlign.Start).layoutWeight(1)
          Toggle({ type: ToggleType.Switch, isOn: this.inference.preferLocal })
            .accessibilityText('优先使用本地推理')
            .enabled(!this.inference.busy && !this.downloading &&
              (!!this.inference.activeModel || this.inference.preferLocal))
            .onChange((prefer: boolean) => { void this.run(() => localInference.preferLocal(prefer)); })
        }.width('100%').padding(14).backgroundColor('#EDF5FF').borderRadius(14)
        ForEach(this.models, (model: LocalModelSpec) => { this.modelRow(model) }, (model: LocalModelSpec) => model.id)
        if (this.inference.busy) Text('正在更新本地推理…').fontSize(14).fontColor('#4D6279')
        if (this.error || this.inference.message) {
          Text(this.error || this.inference.message).fontSize(14).fontColor('#B42318')
        }
        if (this.inference.activeModel) {
          Button('停止本地推理').enabled(!this.inference.busy && !this.downloading)
            .onClick(() => { void this.run(() => localInference.stop()); })
        }
      }.width('100%').constraintSize({ maxWidth: 460 }).alignItems(HorizontalAlign.Start).padding(22)
    }.width('100%').height('100%').backgroundColor(Color.White).align(Alignment.Top)
  }
}

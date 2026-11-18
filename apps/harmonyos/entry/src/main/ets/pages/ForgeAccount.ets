import { common } from '@kit.AbilityKit';
import { fileIo } from '@kit.CoreFileKit';

const DEVICE_URL = 'https://github.com/login/device';

interface AccountStatus {
  id: string;
  phase: string;
  code?: string;
  account?: string;
}

interface AccountRequest {
  id: string;
  action: string;
}

@Component
export struct ForgeAccount {
  onClose: () => void = () => {};
  @State phase: string = 'working';
  @State code: string = '';
  @State account: string = '';
  @State linkError: boolean = false;
  private requestId: string = '';
  private serial: number = 0;
  private timer: number = -1;
  private submittedAt: number = 0;

  private context(): common.UIAbilityContext {
    return this.getUIContext().getHostContext() as common.UIAbilityContext;
  }

  private directory(): string {
    return this.context().filesDir + '/alpine/tmp/github-account/';
  }

  aboutToAppear(): void {
    this.submit('status');
    this.timer = setInterval(() => this.readStatus(), 300);
  }

  aboutToDisappear(): void {
    if (this.timer >= 0) clearInterval(this.timer);
    this.timer = -1;
  }

  private submit(action: string): void {
    if (action !== 'cancel') {
      this.serial += 1;
      this.requestId = 'mh-' + Date.now() + '-' + this.serial;
      this.phase = 'working';
      this.code = '';
      this.account = '';
      this.linkError = false;
      this.submittedAt = Date.now();
    }
    const info: AccountRequest = { id: this.requestId, action: action };
    const request = this.directory() + 'request.json';
    try {
      const file = fileIo.openSync(request + '.new',
        fileIo.OpenMode.CREATE | fileIo.OpenMode.WRITE_ONLY | fileIo.OpenMode.TRUNC);
      try {
        const content = JSON.stringify(info);
        if (fileIo.writeSync(file.fd, content) !== content.length) throw new Error('Incomplete request');
      } finally { fileIo.closeSync(file); }
      fileIo.renameSync(request + '.new', request);
    } catch {
      this.phase = 'failed';
    }
  }

  private readStatus(): void {
    try {
      const status = JSON.parse(fileIo.readTextSync(this.directory() + 'status.json')) as AccountStatus;
      if (status.id === this.requestId) {
        this.phase = status.phase;
        this.code = status.code ?? '';
        this.account = status.account ?? '';
        return;
      }
    } catch {
      // The Host may not have handled the request yet.
    }
    if (this.phase === 'working' && Date.now() - this.submittedAt > 16000) this.phase = 'failed';
  }

  private async openAuthorization(): Promise<void> {
    try {
      await this.context().openLink(DEVICE_URL, { appLinkingOnly: false });
    } catch {
      this.linkError = true;
    }
  }

  build() {
    Column({ space: 12 }) {
      Text('Forge GitHub 账号').fontSize(22).fontWeight(FontWeight.Medium)
      if (this.phase === 'authorize') {
        Text('复制一次性代码，然后在 GitHub 页面授权。')
        Text(this.code).fontSize(25).fontWeight(FontWeight.Medium).copyOption(CopyOptions.LocalDevice)
        Button('打开 GitHub 授权页').onClick(() => { void this.openAuthorization(); })
        if (this.linkError) Text(DEVICE_URL).copyOption(CopyOptions.LocalDevice)
        Button('取消登录').onClick(() => { this.submit('cancel'); })
      } else if (this.phase === 'signed-in') {
        Text(this.account ? '已登录 ' + this.account : '已登录 GitHub')
        Button('退出 GitHub 登录').onClick(() => { this.submit('logout'); })
      } else if (this.phase === 'working') {
        Text('正在联系 GitHub CLI…')
        Button('取消').onClick(() => { this.submit('cancel'); })
      } else {
        Text(this.phase === 'failed' ? '操作未完成，可以刷新状态或重新登录。' : '此设备未登录 GitHub。')
        Button('登录 GitHub').onClick(() => { this.submit('login'); })
        if (this.phase === 'failed') Button('刷新状态').onClick(() => { this.submit('status'); })
      }
      Button('返回会话').onClick(() => {
        if (this.phase === 'authorize' || this.phase === 'working') this.submit('cancel');
        this.onClose();
      })
    }.padding(24).width('100%').alignItems(HorizontalAlign.Start)
  }
}

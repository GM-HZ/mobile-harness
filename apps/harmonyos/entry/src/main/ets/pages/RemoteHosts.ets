import { common } from '@kit.AbilityKit';
import { dshEngine } from '../runtime/DshEngine';
import { RemoteHost } from '../runtime/RemoteHosts';

@Component
export struct RemoteHostsPage {
  onClose: () => void = () => {};
  @State hosts: RemoteHost[] = [];
  @State name: string = '';
  @State url: string = '';
  @State token: string = '';
  @State error: string = '';
  @State busy: boolean = false;
  @State kind: string = 'direct';
  @State sshHost: string = '';
  @State sshPort: string = '22';
  @State sshUser: string = '';
  @State sshPassword: string = '';
  @State sshKey: string = '';
  @State sshPassphrase: string = '';
  @State fingerprint: string = '';

  private context(): common.UIAbilityContext {
    return this.getUIContext().getHostContext() as common.UIAbilityContext;
  }

  aboutToAppear(): void {
    this.refresh();
  }

  private refresh(): void {
    this.hosts = dshEngine.remoteHosts(this.context());
  }

  private async use(id: string): Promise<void> {
    this.busy = true;
    this.error = '';
    try {
      await dshEngine.selectRemoteHost(this.context(), id);
    } catch (error) {
      this.error = '切换主机失败：' + String(error);
    }
    this.busy = false;
  }

  private async useLocal(): Promise<void> {
    this.busy = true;
    try {
      await dshEngine.selectRemoteHost(this.context(), '');
    } catch (error) {
      this.error = '切换本机失败：' + String(error);
    }
    this.busy = false;
  }

  private async remove(id: string): Promise<void> {
    await dshEngine.removeRemoteHost(this.context(), id);
    this.refresh();
  }

  private async save(): Promise<void> {
    const id = Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
    let host: RemoteHost;
    if (this.kind === 'ssh') {
      if (!this.sshHost.trim() || !this.sshUser.trim()) {
        this.error = 'SSH 主机和用户名不能为空';
        return;
      }
      host = {
        id,
        name: this.name.trim() || this.sshUser + '@' + this.sshHost,
        kind: 'ssh',
        url: '',
        token: this.token.trim(),
        sshHost: this.sshHost.trim(),
        sshPort: this.sshPort.trim() || '22',
        sshUser: this.sshUser.trim(),
        sshPassword: this.sshPassword,
        sshKey: this.sshKey,
        sshPassphrase: this.sshPassphrase,
        fingerprint: this.fingerprint.trim(),
      };
    } else {
      const target = this.url.trim();
      if (!/^https?:\/\//i.test(target)) {
        this.error = '地址需要以 http:// 或 https:// 开头';
        return;
      }
      host = {
        id,
        name: this.name.trim() || target,
        kind: 'direct',
        url: target,
        token: this.token.trim(),
      };
    }
    this.error = '';
    await dshEngine.addRemoteHost(this.context(), host);
    this.name = '';
    this.url = '';
    this.token = '';
    this.sshHost = '';
    this.sshUser = '';
    this.sshPassword = '';
    this.sshKey = '';
    this.sshPassphrase = '';
    this.fingerprint = '';
    this.refresh();
  }

  @Builder
  private hostButton(label: string, action: () => void, emphasized: boolean) {
    Button(label)
      .fontSize(13)
      .height(34)
      .padding({ left: 14, right: 14 })
      .backgroundColor(emphasized ? '#4D6BFE' : '#F2F3F7')
      .fontColor(emphasized ? '#FFFFFF' : '#303543')
      .enabled(!this.busy)
      .onClick(action)
  }

  build() {
    Column() {
      Row() {
        Text('远程主机').fontSize(22).fontWeight(FontWeight.Medium)
        Blank()
        Button('返回').fontSize(13).height(34).backgroundColor('#F2F3F7')
          .fontColor('#303543').onClick(() => this.onClose())
      }.width('100%').padding({ bottom: 12 })

      Text('连接服务器上的 DSH Web。填写服务器地址和登录 token；需要服务器已启动 DSH Web 并可被手机访问。')
        .fontSize(12).fontColor('#787E8C').width('100%').margin({ bottom: 12 })

      if (this.hosts.length > 0) {
        List({ space: 8 }) {
          ForEach(this.hosts, (host: RemoteHost) => {
            ListItem() {
              Column({ space: 6 }) {
                Text(host.name + (host.kind === 'ssh' ? '  ·  SSH' : '  ·  直连'))
                  .fontSize(16).fontWeight(FontWeight.Medium)
                Text(host.url).fontSize(12).fontColor('#787E8C').maxLines(1)
                  .textOverflow({ overflow: TextOverflow.Ellipsis })
                Row({ space: 8 }) {
                  this.hostButton('使用', () => { void this.use(host.id); }, true)
                  this.hostButton('删除', () => { void this.remove(host.id); }, false)
                }
              }.alignItems(HorizontalAlign.Start).width('100%')
                .padding(14).backgroundColor('#F7F8FA').borderRadius(14)
            }
          }, (host: RemoteHost) => host.id)
        }.width('100%').height(220).margin({ bottom: 12 })
      } else {
        Text('还没有远程主机').fontSize(14).fontColor('#8A8F9C').margin({ bottom: 12 })
      }

      Button('切回本机').height(38).fontSize(14).backgroundColor('#F2F3F7')
        .fontColor('#303543').enabled(!this.busy)
        .onClick(() => { void this.useLocal(); }).margin({ bottom: 16 })

      Divider().color('#E6E8EE').margin({ bottom: 12 })
      Text('添加远程 DSH Web').fontSize(16).fontWeight(FontWeight.Medium).margin({ bottom: 8 })
      Row({ space: 8 }) {
        this.hostButton('直连 URL', () => { this.kind = 'direct'; }, this.kind === 'direct')
        this.hostButton('SSH 隧道', () => { this.kind = 'ssh'; }, this.kind === 'ssh')
      }.margin({ bottom: 10 })
      TextInput({ placeholder: '名称（可选）', text: this.name })
        .onChange((value: string) => { this.name = value; }).margin({ bottom: 8 })
      if (this.kind === 'direct') {
        TextInput({ placeholder: '服务器地址，例如 https://server.example.com:19592', text: this.url })
          .onChange((value: string) => { this.url = value; }).margin({ bottom: 8 })
        TextInput({ placeholder: '登录 token（可选，也可包含在地址里）', text: this.token })
          .type(InputType.Password).onChange((value: string) => { this.token = value; }).margin({ bottom: 8 })
      } else {
        TextInput({ placeholder: 'SSH 主机，例如 192.168.1.4', text: this.sshHost })
          .onChange((value: string) => { this.sshHost = value; }).margin({ bottom: 8 })
        Row({ space: 8 }) {
          TextInput({ placeholder: 'SSH 端口', text: this.sshPort })
            .onChange((value: string) => { this.sshPort = value; }).layoutWeight(1)
          TextInput({ placeholder: '用户名', text: this.sshUser })
            .onChange((value: string) => { this.sshUser = value; }).layoutWeight(1)
        }.margin({ bottom: 8 })
        TextInput({ placeholder: 'SSH 密码（或下方私钥）', text: this.sshPassword })
          .type(InputType.Password).onChange((value: string) => { this.sshPassword = value; }).margin({ bottom: 8 })
        TextInput({ placeholder: '远端 DSH 端口（默认 19592）', text: this.sshPort })
          .onChange((value: string) => { this.sshPort = value; }).margin({ bottom: 8 })
        TextInput({ placeholder: '远端 DSH 登录 token', text: this.token })
          .type(InputType.Password).onChange((value: string) => { this.token = value; }).margin({ bottom: 8 })
        TextInput({ placeholder: '主机指纹（可选，SHA256:...）', text: this.fingerprint })
          .onChange((value: string) => { this.fingerprint = value; }).margin({ bottom: 8 })
        TextArea({ placeholder: 'SSH 私钥（可选，粘贴 OpenSSH 私钥）', text: this.sshKey })
          .height(90).onChange((value: string) => { this.sshKey = value; }).margin({ bottom: 8 })
        TextInput({ placeholder: '私钥口令（可选）', text: this.sshPassphrase })
          .type(InputType.Password).onChange((value: string) => { this.sshPassphrase = value; }).margin({ bottom: 8 })
      }
      if (this.error) Text(this.error).fontSize(12).fontColor('#D14343').margin({ bottom: 8 })
      Button('保存并使用').width('100%').height(42).backgroundColor('#4D6BFE')
        .fontColor('#FFFFFF').enabled(!this.busy)
        .onClick(() => { void this.save(); }).margin({ bottom: 8 })
      Button('保存').width('100%').height(38).backgroundColor('#F2F3F7')
        .fontColor('#303543').enabled(!this.busy)
        .onClick(() => { void this.save(); })
    }.width('100%').height('100%').padding(20).backgroundColor('#FFFFFF')
      .alignItems(HorizontalAlign.Start)
  }
}

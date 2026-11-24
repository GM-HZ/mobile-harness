import { common } from '@kit.AbilityKit';
import { webview } from '@kit.ArkWeb';
import { allowedRemoteRequest, exchangeRemoteToken, isRemoteHostsEnabled, RemoteHost,
  remoteHostOrigin, RemoteHostStore } from '../runtime/RemoteHosts';

@Component
export struct RemoteHostsPage {
  onClose: () => void = () => {};
  @State hosts: RemoteHost[] = [];
  @State address: string = '';
  @State name: string = '';
  @State token: string = '';
  @State origin: string = '';
  @State error: string = '';
  @State connecting: boolean = false;
  private requestId: number = 0;
  private cookieName: string = '';
  private controller: webview.WebviewController = new webview.WebviewController();

  private context(): common.UIAbilityContext {
    return this.getUIContext().getHostContext() as common.UIAbilityContext;
  }

  aboutToAppear(): void {
    this.hosts = RemoteHostStore.list(this.context());
  }

  aboutToDisappear(): void {
    this.disconnect();
  }

  private choose(host: RemoteHost): void {
    this.address = host.origin;
    this.name = host.name;
    this.token = '';
    this.error = '';
  }

  private remove(host: RemoteHost): void {
    try {
      RemoteHostStore.remove(this.context(), host.origin);
      this.hosts = RemoteHostStore.list(this.context());
    } catch (_) {
      this.error = '无法移除已保存的地址。';
    }
  }

  private async connect(): Promise<void> {
    const context = this.context();
    if (!isRemoteHostsEnabled(context) || this.connecting || this.origin) return;
    let origin: string;
    try {
      origin = remoteHostOrigin(this.address);
    } catch (_) {
      this.error = '请输入 HTTPS 主机地址，例如 https://host.example.com。';
      return;
    }
    const token = this.token.trim();
    if (!token) {
      this.error = '请输入服务器提供的 DSH 登录 token。';
      return;
    }
    this.token = '';
    this.error = '';
    this.connecting = true;
    const requestId = ++this.requestId;
    try {
      const cookie = await exchangeRemoteToken(origin, token);
      if (this.requestId !== requestId) return;
      RemoteHostStore.remember(context, { name: this.name, origin });
      this.hosts = RemoteHostStore.list(context);
      webview.WebviewController.initializeWebEngine();
      webview.WebCookieManager.configCookieSync(origin + '/',
        cookie + '; Path=/; HttpOnly; Secure; SameSite=Strict', true, true);
      this.cookieName = cookie.slice(0, cookie.indexOf('='));
      this.controller = new webview.WebviewController();
      this.origin = origin;
    } catch (_) {
      if (this.requestId === requestId) this.error = '连接失败。请检查服务器的 HTTPS 配置和 DSH 登录 token。';
    } finally {
      if (this.requestId === requestId) this.connecting = false;
    }
  }

  private disconnect(): void {
    ++this.requestId;
    if (this.origin && this.cookieName) {
      try {
        webview.WebCookieManager.configCookieSync(this.origin + '/',
          this.cookieName + '=; Max-Age=0; Path=/; HttpOnly; Secure; SameSite=Strict', true, true);
      } catch (_) {
        // Removing the incognito browser also clears its session storage.
      }
    }
    this.cookieName = '';
    this.origin = '';
    this.token = '';
    this.error = '';
    this.connecting = false;
  }

  private intercept(request: WebResourceRequest): WebResourceResponse {
    if (allowedRemoteRequest(this.origin, request.getRequestUrl())) return null!;
    const blocked = new WebResourceResponse();
    blocked.setResponseCode(403);
    blocked.setReasonMessage('Forbidden');
    blocked.setResponseMimeType('text/plain');
    blocked.setResponseData('This remote session is restricted to its configured HTTPS origin.');
    return blocked;
  }

  @Builder
  private hostForm() {
    Scroll() {
      Column({ space: 12 }) {
        Text('填写已启用 HTTPS 的 DSH Web 主机。地址会保存在此设备，登录 token 仅用于本次连接。')
          .fontSize(14).fontColor('#636978').width('100%')
        ForEach(this.hosts, (host: RemoteHost) => {
          Row({ space: 8 }) {
            Button(host.name).layoutWeight(1).enabled(!this.connecting).onClick(() => this.choose(host))
            Button('移除').enabled(!this.connecting).onClick(() => this.remove(host))
          }.width('100%')
        }, (host: RemoteHost) => host.origin)
        TextInput({ placeholder: 'HTTPS 地址', text: this.address })
          .enabled(!this.connecting).onChange((value: string) => { this.address = value; })
        TextInput({ placeholder: '名称（可选）', text: this.name })
          .enabled(!this.connecting).onChange((value: string) => { this.name = value; })
        TextInput({ placeholder: 'DSH 登录 token', text: this.token })
          .type(InputType.Password).enabled(!this.connecting).onChange((value: string) => { this.token = value; })
        Button(this.connecting ? '正在连接…' : '连接').width('100%').enabled(!this.connecting)
          .onClick(() => { void this.connect(); })
      }.width('100%').padding(16)
    }.layoutWeight(1).width('100%')
  }

  build() {
    Column() {
      Row() {
        Text(this.origin || '远程主机').fontSize(18).fontWeight(FontWeight.Medium)
          .maxLines(1).textOverflow({ overflow: TextOverflow.Ellipsis }).layoutWeight(1)
        Button(this.origin ? '断开' : '返回本机').onClick(() => {
          if (this.origin) this.disconnect();
          else this.onClose();
        })
      }.width('100%').padding(12)
      if (this.error) Text(this.error).fontSize(14).fontColor('#B42318').width('100%').padding(12)
      if (this.origin) {
        Web({ src: this.origin + '/', controller: this.controller, incognitoMode: true })
          .layoutWeight(1).width('100%')
          .javaScriptAccess(true)
          .domStorageAccess(true)
          .fileAccess(false)
          .mixedMode(MixedMode.None)
          .multiWindowAccess(false)
          .allowWindowOpenMethod(false)
          .onLoadIntercept(event => !event || !allowedRemoteRequest(this.origin, event.data.getRequestUrl()))
          .onInterceptRequest(event => event ? this.intercept(event.request) : null!)
          .onPermissionRequest(event => { event?.request.deny(); })
          .onShowFileSelector(event => {
            event?.result.handleFileList([]);
            return true;
          })
          .onHttpErrorReceive(event => {
            if (event?.request.isMainFrame()) this.error = '远程页面加载失败，可断开后重试。';
          })
          .onErrorReceive(event => {
            if (event?.request.isMainFrame()) this.error = '远程连接已中断，可断开后重试。';
          })
      } else {
        this.hostForm()
      }
    }.width('100%').height('100%').backgroundColor('#FFFFFF')
  }
}

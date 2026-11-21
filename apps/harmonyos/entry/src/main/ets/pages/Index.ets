import { abilityAccessCtrl, common } from '@kit.AbilityKit';
import { url } from '@kit.ArkTS';
import { webview } from '@kit.ArkWeb';
import { hilog } from '@kit.PerformanceAnalysisKit';
import { BrowserSession, EngineProgress, dshEngine } from '../runtime/DshEngine';
import { ForgeAccount } from './ForgeAccount';

const LOCAL_ORIGIN = 'http://127.0.0.1:19592';
const RECOVERY_URL = LOCAL_ORIGIN + '/.mobile-harness/recovery';
const GITHUB_URL = LOCAL_ORIGIN + '/.mobile-harness/github';
type LoginFlow = 'unbound' | 'deepseek' | 'liveshare';

@Entry
@Component
struct Index {
  @State status: string = '正在准备本机 DSH…';
  @State launchUrl: string = '';
  @State recoveryOpen: boolean = false;
  @State forgeAccountOpen: boolean = false;
  @State safe: boolean = false;
  @State webFailed: boolean = false;
  @State progressPercent: number = 0;
  @State progressPhase: string = '环境准备';
  @State splashVisible: boolean = true;
  @State splashOpacity: number = 1;
  @State restartError: string = '';
  @State restarting: boolean = false;
  private controller: webview.WebviewController = new webview.WebviewController();
  @State loginVisible: boolean = false;
  @State loginAddress: string = '正在连接 DeepSeek…';
  @State loginError: string = '';
  private loginController: webview.WebviewController = new webview.WebviewController();
  private loginFlow: LoginFlow = 'unbound';
  private relayOrigin: string = '';
  private detachEngine?: () => void;

  aboutToAppear(): void {
    const context = this.getUIContext().getHostContext() as common.UIAbilityContext;
    this.detachEngine = dshEngine.attach(context, (status: string, session?: BrowserSession,
      progress?: EngineProgress) => {
      this.status = status;
      if (progress) {
        this.progressPhase = progress.phase;
        this.progressPercent = Math.max(this.progressPercent, progress.percent);
      }
      this.safe = session?.safe === true;
      if (!session) {
        this.launchUrl = '';
        this.webFailed = false;
        this.forgeAccountOpen = false;
        this.closeLogin();
      } else if (!this.launchUrl) {
        try {
          webview.WebviewController.initializeWebEngine();
          webview.WebCookieManager.putAcceptCookieEnabled(true);
          if (session.cookie) webview.WebCookieManager.configCookieSync(session.url, session.cookie, false, true);
          const proxy = new webview.ProxyConfig();
          proxy.insertDirectRule(webview.ProxySchemeFilter.MATCH_HTTP);
          webview.ProxyController.applyProxyOverride(proxy, () => {
            if (this.detachEngine) this.launchUrl = session.url;
          });
        } catch (e) {
          this.status = '本机 DSH 页面初始化失败。';
          hilog.error(0xD005, 'DSHClient', 'browser session setup failed');
        }
      }
    });
  }

  aboutToDisappear(): void {
    this.detachEngine?.();
    this.detachEngine = undefined;
  }

  private finishSplash(): void {
    if (!this.splashVisible) return;
    this.progressPhase = '就绪';
    this.progressPercent = 100;
    animateTo({ duration: 320, curve: Curve.EaseOut }, () => { this.splashOpacity = 0; });
    setTimeout(() => { this.splashVisible = false; }, 340);
  }

  private async requestMicrophone(request: PermissionRequest): Promise<void> {
    const origin = request.getOrigin();
    const resources = request.getAccessibleResource();
    const session = this.launchUrl;
    if ((origin !== LOCAL_ORIGIN && origin !== LOCAL_ORIGIN + '/') ||
        resources.length !== 1 || resources[0] !== ProtectedResourceType.AUDIO_CAPTURE ||
        !session || this.safe || this.recoveryOpen || this.loginVisible || this.webFailed) {
      request.deny();
      return;
    }

    const context = this.getUIContext().getHostContext() as common.UIAbilityContext;
    const permission = 'ohos.permission.MICROPHONE';
    let granted = false;
    try {
      const result = await abilityAccessCtrl.createAtManager().requestPermissionsFromUser(context, [permission]);
      granted = result.authResults.length === 1 && result.authResults[0] === 0;
    } catch (e) {
      hilog.warn(0xD005, 'DSHClient', 'microphone permission request failed');
    }
    if (granted && this.detachEngine && this.launchUrl === session &&
        !this.safe && !this.recoveryOpen && !this.loginVisible && !this.webFailed) {
      request.grant(resources);
    } else {
      request.deny();
    }
  }

  private loginHost(url: string): string {
    const match = /^https:\/\/((?:[a-z0-9-]+\.)*deepseek\.com)(?::443)?(?:[/?#]|$)/i.exec(url);
    return match ? 'https://' + match[1] : '';
  }

  private isLoginCallback(url: string): boolean {
    return /^http:\/\/127\.0\.0\.1:19592\/oauth\/callback(?:[?#]|$)/.test(url);
  }

  private parseLoginAddress(address: string): url.URL | undefined {
    try {
      const parsed = url.URL.parseURL(address);
      return parsed.username || parsed.password ? undefined : parsed;
    } catch {
      return undefined;
    }
  }

  private liveShareAuthorization(address: url.URL): boolean {
    const secure = address.protocol === 'https:';
    const testRelay = address.protocol === 'http:' && address.hostname === '127.0.0.1' &&
      address.origin !== LOCAL_ORIGIN;
    const params = address.params;
    return (secure || testRelay) && address.pathname.endsWith('/__liveshare/owner-authorize') &&
      params.get('origin') === LOCAL_ORIGIN && /^[A-Za-z0-9_-]{22}$/.test(params.get('state') ?? '') &&
      /^[A-Za-z0-9_-]{43}$/.test(params.get('code_challenge') ?? '') && !!params.get('instance');
  }

  private allowPopupNavigation(address: string): boolean {
    if (address === 'about:blank') return true;
    const parsed = this.parseLoginAddress(address);
    if (!parsed) return false;
    if (this.loginFlow === 'liveshare') {
      // A deployed Relay may redirect to an HTTPS identity provider.
      return parsed.protocol === 'https:' || parsed.origin === this.relayOrigin;
    }
    if (this.loginFlow === 'unbound' && this.liveShareAuthorization(parsed)) {
      this.loginFlow = 'liveshare';
      this.relayOrigin = parsed.origin;
      return true;
    }
    if (this.loginHost(address) || this.isLoginCallback(address)) {
      this.loginFlow = 'deepseek';
      return true;
    }
    return false;
  }

  private openLogin(event: OnWindowNewEvent): void {
    const target = event.targetUrl;
    if (this.loginVisible || !event.isUserTrigger) {
      event.handler.setWebController(null!);
      return;
    }
    this.loginFlow = 'unbound';
    this.relayOrigin = '';
    if (target && !this.allowPopupNavigation(target)) {
      event.handler.setWebController(null!);
      return;
    }
    this.loginController = new webview.WebviewController();
    this.loginAddress = '正在连接 DeepSeek…';
    this.loginError = '';
    event.handler.setWebController(this.loginController);
    this.loginVisible = true;
    hilog.info(0xD005, 'DSHClient', 'account popup attached');
  }

  private closeLogin(): void {
    this.loginVisible = false;
    this.loginError = '';
    this.loginFlow = 'unbound';
    this.relayOrigin = '';
  }

  onBackPress(): boolean {
    if (this.recoveryOpen && this.launchUrl && !this.webFailed) {
      this.recoveryOpen = false;
      return true;
    }
    if (!this.loginVisible) return false;
    this.closeLogin();
    return true;
  }

  @Builder
  private loginPage() {
    Column() {
      Row({ space: 12 }) {
        Button('返回聊天').onClick(() => this.closeLogin())
        Text(this.loginAddress).fontSize(13).layoutWeight(1).maxLines(1)
      }.width('100%').padding(12)
      if (this.loginError) {
        Text(this.loginError).fontSize(14).padding(12)
      }
      Web({ src: 'about:blank', controller: this.loginController })
        .layoutWeight(1)
        .width('100%')
        .javaScriptAccess(true)
        .domStorageAccess(true)
        .fileAccess(false)
        .onLoadIntercept((event) => {
          if (!event || !event.data.isMainFrame()) return false;
          const url = event.data.getRequestUrl();
          if (this.allowPopupNavigation(url)) return false;
          this.loginError = '这个登录地址不受支持。返回聊天后可以重试。';
          return true;
        })
        .onPageBegin((event) => {
          const host = this.loginHost(event?.url ?? '');
          if (this.loginFlow === 'liveshare') {
            this.loginAddress = this.parseLoginAddress(event?.url ?? '')?.origin || '正在连接分享服务…';
            this.loginError = '';
          } else if (host) {
            this.loginAddress = host;
            this.loginError = '';
            hilog.info(0xD005, 'DSHClient', 'account popup opened %{public}s', host);
          } else if (this.isLoginCallback(event?.url ?? '')) {
            this.loginAddress = '正在确认登录…';
          }
        })
        .onPageEnd((event) => {
          const url = event?.url ?? '';
          const host = this.loginHost(url);
          if (host) {
            hilog.info(0xD005, 'DSHClient', 'account popup page ended %{public}s', host);
          }
          if (this.loginFlow === 'deepseek' && /^https:\/\/platform\.deepseek\.com\/dsh\/authorized(?:[/?#]|$)/.test(url)) {
            this.closeLogin();
          }
        })
        .onErrorReceive((event) => {
          if (!event?.request.isMainFrame()) return;
          this.loginError = '登录页加载失败。请返回聊天重试，或使用 API Key。';
          hilog.error(0xD005, 'DSHClient', 'account popup network error %{public}d', event.error.getErrorCode());
        })
        .onHttpErrorReceive((event) => {
          if (!event?.request.isMainFrame()) return;
          this.loginError = '登录服务返回错误。请返回聊天重试，或使用 API Key。';
          hilog.error(0xD005, 'DSHClient', 'account popup HTTP error %{public}d', event.response.getResponseCode());
        })
        .onWindowExit(() => this.closeLogin())
    }.layoutWeight(1).width('100%')
  }

  private async restart(mode: string): Promise<void> {
    const context = this.getUIContext().getHostContext() as common.UIAbilityContext;
    this.restarting = true;
    this.restartError = '';
    try {
      await dshEngine.restart(context, mode);
      this.recoveryOpen = false;
      this.restarting = false;
    } catch (_) {
      this.restartError = '无法自动重开。请退出应用后重新打开。';
      this.restarting = false;
    }
  }

  private async rollbackPlugins(): Promise<void> {
    const context = this.getUIContext().getHostContext() as common.UIAbilityContext;
    this.restarting = true;
    this.restartError = '';
    try {
      await dshEngine.restartWithPluginRollback(context);
      this.recoveryOpen = false;
    } catch (_) {
      this.restartError = '没有可用的插件快照，或无法自动重开。';
    }
    this.restarting = false;
  }

  @Builder
  private recoveryPage() {
    Column({ space: 12 }) {
      Text('运行时恢复').fontSize(22).fontWeight(FontWeight.Medium)
      Text(this.webFailed ? '本机 DSH 页面加载失败。' :
        (this.status || (this.safe ? '当前处于安全模式。' : '恢复操作会重开应用并保留会话与工作区。')))
        .fontSize(15)
      Button('以安全模式重开').enabled(!this.restarting).onClick(() => { this.restart('safe'); })
      Button('以正常模式重开').enabled(!this.restarting).onClick(() => { this.restart('normal'); })
      Button('回滚插件配置并正常重开').enabled(!this.restarting).onClick(() => { this.rollbackPlugins(); })
      if (this.restartError) Text(this.restartError).fontSize(14)
      if (this.launchUrl && !this.webFailed) Button('返回会话').onClick(() => { this.recoveryOpen = false; })
    }.padding(24).width('100%').alignItems(HorizontalAlign.Start)
  }

  @Builder
  private splashScreen() {
    Stack({ alignContent: Alignment.Bottom }) {
      Column() {
        Stack() {
          Text('DS').fontSize(30).fontWeight(FontWeight.Bold).fontColor('#FFFFFF')
            .letterSpacing(1)
        }.width(88).height(88).borderRadius(24)
          .linearGradient({ angle: 135, colors: [['#5B7CFF', 0], ['#2B3AA8', 1]] })
          .border({ width: 1, color: '#607BFF55' })
        Text('DeepSeek Harness').fontSize(25).fontWeight(FontWeight.Medium)
          .fontColor('#F5F6FA').margin({ top: 24 }).letterSpacing(0.4)
        Text('本机 AI 执行环境').fontSize(12).fontColor('#767B8A').margin({ top: 9 }).letterSpacing(0.6)
        Column() {
          Row() {
            Row().width(this.progressPercent + '%').height(4)
              .backgroundColor('#4D6BFE').borderRadius(2)
              .animation({ duration: 420, curve: Curve.EaseOut })
          }.width('100%').height(4).backgroundColor('#20232E').borderRadius(2)
          Row() {
            Text(this.progressPhase).fontSize(11).fontColor('#9499A6')
            Blank()
            Text(this.progressPercent + '%').fontSize(11).fontColor('#5C6273')
          }.width('100%').margin({ top: 12 })
          Row({ space: 18 }) {
            Text('环境').fontSize(10).fontColor(this.progressPercent >= 5 ? '#4D6BFE' : '#3A3F4E')
            Text('解包').fontSize(10).fontColor(this.progressPercent >= 8 ? '#4D6BFE' : '#3A3F4E')
            Text('服务').fontSize(10).fontColor(this.progressPercent >= 66 ? '#4D6BFE' : '#3A3F4E')
            Text('界面').fontSize(10).fontColor(this.progressPercent >= 90 ? '#4D6BFE' : '#3A3F4E')
          }.margin({ top: 12 })
          Text(this.status).fontSize(12).fontColor('#6B7080').margin({ top: 10 })
            .maxLines(2).textOverflow({ overflow: TextOverflow.Ellipsis })
        }.width(280).margin({ top: 42 })
      }.width('100%').height('100%').justifyContent(FlexAlign.Center)
        .alignItems(HorizontalAlign.Center)
      Text('恢复选项').fontSize(12).fontColor('#555B6A').padding(14)
        .margin({ bottom: 16 })
        .onClick(() => { this.splashVisible = false; this.recoveryOpen = true; })
    }.width('100%').height('100%').padding({ left: 32, right: 32 })
      .linearGradient({ angle: 180, colors: [['#090A0F', 0], ['#10121B', 0.55], ['#090A0F', 1]] })
      .opacity(this.splashOpacity)
  }

  build() {
    Stack({ alignContent: Alignment.Center }) {
      if (this.launchUrl) {
        Web({ src: this.launchUrl, controller: this.controller })
          .layoutWeight(1)
          .width('100%')
          .visibility(this.loginVisible || this.recoveryOpen || this.forgeAccountOpen || this.webFailed
            ? Visibility.None : Visibility.Visible)
          .javaScriptAccess(true)
          .domStorageAccess(true)
          .fileAccess(false)
          .multiWindowAccess(true)
          .allowWindowOpenMethod(true)
          .onWindowNew((event) => this.openLogin(event))
          .onPermissionRequest((event: OnPermissionRequestEvent) => {
            void this.requestMicrophone(event.request);
          })
          .onLoadIntercept((event) => {
            if (!event || !event.data.isMainFrame()) return false;
            const url = event.data.getRequestUrl();
            if (url === RECOVERY_URL) {
              this.splashVisible = false;
              this.recoveryOpen = true;
              return true;
            }
            if (url === GITHUB_URL) {
              if (!this.safe) this.forgeAccountOpen = true;
              return true;
            }
            return !url.startsWith(LOCAL_ORIGIN + '/') && url !== 'about:blank';
          })
          .onPageEnd(() => {
            setTimeout(() => {
              this.controller.runJavaScript(
                'JSON.stringify({ title: document.title, ready: document.readyState, atLoopback: location.hostname === "127.0.0.1", body: document.body?.innerText.length || 0 })'
              ).then((value: string) => {
                hilog.info(0xD005, 'DSHClient', 'ArkWeb loaded %{public}s', value);
                this.finishSplash();
                const host = this.getUIContext().getHostContext() as common.UIAbilityContext;
                // Optional feature payloads are large; keep the first seconds
                // after reveal free of extraction I/O so the client is responsive.
                setTimeout(() => { dshEngine.extractOptional(host); }, 8000);
              }).catch(() => { this.finishSplash(); });
            }, 1500);
          })
          .onErrorReceive((event) => {
            if (event?.request.isMainFrame() && event.error.getErrorCode() !== -3 &&
                event.request.getRequestUrl() !== RECOVERY_URL && event.request.getRequestUrl() !== GITHUB_URL) {
              this.webFailed = true;
              this.splashVisible = false;
              hilog.error(0xD005, 'DSHClient', 'ArkWeb main error %{public}d', event.error.getErrorCode());
            }
          })
          .onHttpErrorReceive((event) => {
            if (event?.request.isMainFrame()) {
              this.webFailed = true;
              this.splashVisible = false;
              hilog.error(0xD005, 'DSHClient', 'ArkWeb HTTP %{public}d', event.response.getResponseCode());
            }
          })
          .onRenderExited(() => { this.webFailed = true; this.splashVisible = false; })
      }
      if (this.webFailed || this.recoveryOpen) {
        this.recoveryPage()
      } else if (this.forgeAccountOpen) {
        ForgeAccount({ onClose: () => { this.forgeAccountOpen = false; } })
      } else if (this.loginVisible) {
        this.loginPage()
      }
      if (this.splashVisible && !this.recoveryOpen && !this.loginVisible &&
          !this.forgeAccountOpen && !this.webFailed) {
        this.splashScreen()
      }
    }.height('100%').width('100%')
  }
}

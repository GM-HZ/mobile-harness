import { abilityAccessCtrl, common } from '@kit.AbilityKit';
import { webview } from '@kit.ArkWeb';
import { hilog } from '@kit.PerformanceAnalysisKit';
import { BrowserSession, dshEngine } from '../runtime/DshEngine';

const LOCAL_ORIGIN = 'http://127.0.0.1:19592';
const RECOVERY_URL = LOCAL_ORIGIN + '/.mobile-harness/recovery';

@Entry
@Component
struct Index {
  @State status: string = '正在准备本机 DSH…';
  @State launchUrl: string = '';
  @State recoveryOpen: boolean = false;
  @State safe: boolean = false;
  @State webFailed: boolean = false;
  @State restartError: string = '';
  @State restarting: boolean = false;
  private controller: webview.WebviewController = new webview.WebviewController();
  @State loginVisible: boolean = false;
  @State loginAddress: string = '正在连接 DeepSeek…';
  @State loginError: string = '';
  private loginController: webview.WebviewController = new webview.WebviewController();
  private detachEngine?: () => void;

  aboutToAppear(): void {
    const context = this.getUIContext().getHostContext() as common.UIAbilityContext;
    this.detachEngine = dshEngine.attach(context, (status: string, session?: BrowserSession) => {
      this.status = status;
      this.safe = session?.safe === true;
      if (!session) {
        this.launchUrl = '';
        this.webFailed = false;
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

  private openLogin(event: OnWindowNewEvent): void {
    const target = event.targetUrl;
    if (this.loginVisible || !event.isUserTrigger ||
        (target && target !== 'about:blank' && !this.loginHost(target))) {
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
          if (url === 'about:blank' || this.loginHost(url) || this.isLoginCallback(url)) return false;
          this.loginError = '这个登录地址不受支持。返回聊天后可以重试，或使用 API Key。';
          return true;
        })
        .onPageBegin((event) => {
          const host = this.loginHost(event?.url ?? '');
          if (host) {
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
          if (/^https:\/\/platform\.deepseek\.com\/dsh\/authorized(?:[/?#]|$)/.test(url)) {
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

  @Builder
  private recoveryPage() {
    Column({ space: 12 }) {
      Text('运行时恢复').fontSize(22).fontWeight(FontWeight.Medium)
      Text(this.webFailed ? '本机 DSH 页面加载失败。' :
        (this.status || (this.safe ? '当前处于安全模式。' : '恢复操作会重开应用并保留会话与工作区。')))
        .fontSize(15)
      Button('以安全模式重开').enabled(!this.restarting).onClick(() => { this.restart('safe'); })
      Button('以正常模式重开').enabled(!this.restarting).onClick(() => { this.restart('normal'); })
      if (this.restartError) Text(this.restartError).fontSize(14)
      if (this.launchUrl && !this.webFailed) Button('返回会话').onClick(() => { this.recoveryOpen = false; })
    }.padding(24).width('100%').alignItems(HorizontalAlign.Start)
  }

  build() {
    Column() {
      if (this.launchUrl) {
        Web({ src: this.launchUrl, controller: this.controller })
          .layoutWeight(1)
          .width('100%')
          .visibility(this.loginVisible || this.recoveryOpen || this.webFailed ? Visibility.None : Visibility.Visible)
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
              this.recoveryOpen = true;
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
              }).catch(() => {});
            }, 1500);
          })
          .onErrorReceive((event) => {
            if (event?.request.isMainFrame() && event.error.getErrorCode() !== -3 &&
                event.request.getRequestUrl() !== RECOVERY_URL) {
              this.webFailed = true;
              hilog.error(0xD005, 'DSHClient', 'ArkWeb main error %{public}d', event.error.getErrorCode());
            }
          })
          .onHttpErrorReceive((event) => {
            if (event?.request.isMainFrame()) {
              this.webFailed = true;
              hilog.error(0xD005, 'DSHClient', 'ArkWeb HTTP %{public}d', event.response.getResponseCode());
            }
          })
          .onRenderExited(() => { this.webFailed = true; })
        if (this.webFailed || this.recoveryOpen) {
          this.recoveryPage()
        } else if (this.loginVisible) {
          this.loginPage()
        }
      } else {
        Text('Mobile Harness').fontSize(26).fontWeight(FontWeight.Medium)
        if (this.recoveryOpen) {
          this.recoveryPage()
        } else {
          Text(this.status).fontSize(15).margin({ top: 12 })
          Button('恢复选项').margin({ top: 12 }).onClick(() => { this.recoveryOpen = true; })
        }
      }
    }.height('100%').width('100%').padding(this.launchUrl ? 0 : 24)
  }
}

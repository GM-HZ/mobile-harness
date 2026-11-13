import { common } from '@kit.AbilityKit';
import { webview } from '@kit.ArkWeb';
import { hilog } from '@kit.PerformanceAnalysisKit';
import { BrowserSession, dshEngine } from '../runtime/DshEngine';
import { getPrivacyPolicyUrl, hasPrivacyConsent, isAppGalleryBuild, savePrivacyConsent } from '../runtime/PrivacyConsent';

const RECOVERY_URL = 'http://127.0.0.1:19592/.mobile-harness/recovery';
const PRIVACY_URL = 'http://127.0.0.1:19592/.mobile-harness/privacy';

@Entry
@Component
struct Index {
  @State status: string = '正在准备本机 DSH…';
  @State startupFailed: boolean = false;
  @State consentRequired: boolean = false;
  @State appGallery: boolean = false;
  @State privacyDetails: boolean = false;
  @State decliningPrivacy: boolean = false;
  @State consentError: string = '';
  @State privacyPolicyUrl: string = '';
  @State privacyLinkError: boolean = false;
  @State launchUrl: string = '';
  @State recoveryOpen: boolean = false;
  @State safe: boolean = false;
  @State webFailed: boolean = false;
  @State restartError: string = '';
  @State restarting: boolean = false;
  private controller: webview.WebviewController = new webview.WebviewController();
  @State loginVisible: boolean = false;
  @State loginLoading: boolean = false;
  @State loginAddress: string = '正在连接 DeepSeek…';
  @State loginError: string = '';
  private loginController: webview.WebviewController = new webview.WebviewController();
  private detachEngine?: () => void;

  aboutToAppear(): void {
    const context = this.getUIContext().getHostContext() as common.UIAbilityContext;
    this.appGallery = isAppGalleryBuild(context);
    if (this.appGallery) this.privacyPolicyUrl = getPrivacyPolicyUrl(context);
    if (this.appGallery && !hasPrivacyConsent(context, this.privacyPolicyUrl)) {
      this.consentRequired = true;
      return;
    }
    this.attachEngine(context);
  }

  private attachEngine(context: common.UIAbilityContext): void {
    setTimeout(() => {
      try {
        webview.WebviewController.initializeWebEngine();
      } catch (_) {
        // Retry when the Host publishes its authenticated session.
      }
    }, 0);
    this.detachEngine = dshEngine.attach(context, (status: string, session?: BrowserSession, failed?: boolean) => {
      this.status = status;
      this.startupFailed = failed === true;
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
          this.startupFailed = true;
          hilog.error(0xD005, 'DSHClient', 'browser session setup failed');
        }
      }
    });
  }

  aboutToDisappear(): void {
    this.detachEngine?.();
    this.detachEngine = undefined;
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
    this.loginLoading = true;
    event.handler.setWebController(this.loginController);
    this.loginVisible = true;
    hilog.info(0xD005, 'DSHClient', 'account popup attached');
  }

  private closeLogin(): void {
    this.loginVisible = false;
    this.loginLoading = false;
    this.loginError = '';
  }

  @Builder
  private loadingPage(message: string, failed: boolean = false) {
    Column({ space: 16 }) {
      Image($r('app.media.dsh_mh_whale')).width(56).height(56).borderRadius(14)
      Text(message).fontSize(15).fontWeight(FontWeight.Medium)
        .fontColor($r('sys.color.font_primary')).textAlign(TextAlign.Center)
      if (failed) {
        Button('恢复选项', { type: ButtonType.Normal })
          .fontSize(14).fontColor($r('sys.color.font_primary')).backgroundColor(Color.Transparent)
          .onClick(() => { this.recoveryOpen = true; })
      } else {
        LoadingProgress().width(22).height(22).color('#4D6BFE')
      }
    }.width('100%').height('100%').padding(24).justifyContent(FlexAlign.Center)
      .backgroundColor($r('sys.color.background_primary'))
  }

  onBackPress(): boolean {
    if (this.privacyDetails) {
      this.privacyDetails = false;
      return true;
    }
    if (this.recoveryOpen && this.launchUrl && !this.webFailed) {
      this.recoveryOpen = false;
      return true;
    }
    if (!this.loginVisible) return false;
    this.closeLogin();
    return true;
  }

  private acceptPrivacy(): void {
    const context = this.getUIContext().getHostContext() as common.UIAbilityContext;
    try {
      savePrivacyConsent(context, this.privacyPolicyUrl);
      this.consentRequired = false;
      this.attachEngine(context);
    } catch (_) {
      this.consentError = '无法保存同意状态，请重试。';
    }
  }

  private declinePrivacy(): void {
    const context = this.getUIContext().getHostContext() as common.UIAbilityContext;
    this.decliningPrivacy = true;
    context.terminateSelf().catch(() => {
      this.decliningPrivacy = false;
      this.consentError = '无法退出，请使用系统返回键。';
    });
  }

  private openPrivacyPolicy(): void {
    const context = this.getUIContext().getHostContext() as common.UIAbilityContext;
    this.privacyLinkError = false;
    context.openLink(this.privacyPolicyUrl, { appLinkingOnly: false }).catch(() => {
      this.privacyLinkError = true;
    });
  }

  @Builder
  private privacyPage() {
    Scroll() {
      Column({ space: 16 }) {
        Text(this.privacyDetails ? '个人信息处理说明' : '隐私提示')
          .fontSize(24).fontWeight(FontWeight.Medium)
        if (this.privacyDetails) {
          Text('工作区和会话保存在本应用的私有目录，用于继续编辑文件和恢复会话。清除应用数据或卸载应用可删除本机存储。')
          Text('使用联网模型时，应用会向所选模型服务发送请求。请求可能包含输入的提示词、会话上下文、附件，以及任务使用的工作区内容或工具结果。')
          Text('选择 DeepSeek 账号登录时，应用打开 DeepSeek 登录页面。选择 API Key 时，应用使用你配置的凭据向对应服务发起请求。模型服务按其自身政策处理收到的数据。')
          Text('联网及网络状态权限用于连接模型服务和配置网络连接。应用市场版本关闭外部插件安装及远程接入。')
          if (this.privacyPolicyUrl) {
            Button('打开完整隐私政策').onClick(() => this.openPrivacyPolicy())
            if (this.privacyLinkError) Text('无法打开链接。可在浏览器中访问：' + this.privacyPolicyUrl)
          }
          Button('返回').onClick(() => { this.privacyDetails = false; })
        } else {
          Text('会话和工作区保存在本机。使用联网模型时，所选模型服务会收到请求所需的提示词、上下文和附件。请阅读个人信息处理说明后再继续。')
          Button('查看个人信息处理说明').onClick(() => { this.privacyDetails = true; })
          Row({ space: 12 }) {
            Button('不同意并退出').enabled(!this.decliningPrivacy).onClick(() => this.declinePrivacy())
            Button('同意并继续').enabled(!this.decliningPrivacy).onClick(() => this.acceptPrivacy())
          }
          if (this.consentError) Text(this.consentError)
        }
      }.padding(24).width('100%').alignItems(HorizontalAlign.Start)
    }.width('100%')
  }

  @Builder
  private loginPage() {
    Column() {
      Row({ space: 12 }) {
        Button('返回聊天', { type: ButtonType.Normal })
          .fontSize(14).fontColor($r('sys.color.font_primary')).backgroundColor(Color.Transparent)
          .onClick(() => this.closeLogin())
        Text(this.loginAddress).fontSize(13).layoutWeight(1).maxLines(1)
      }.width('100%').padding(12)
      if (this.loginError) {
        Text(this.loginError).fontSize(14).padding(12)
      }
      Stack() {
        Web({ src: 'about:blank', controller: this.loginController })
          .height('100%')
          .width('100%')
          .javaScriptAccess(true)
          .domStorageAccess(true)
          .fileAccess(false)
          .onLoadIntercept((event) => {
            if (!event || !event.data.isMainFrame()) return false;
            const url = event.data.getRequestUrl();
            if (url === 'about:blank' || this.loginHost(url) || this.isLoginCallback(url)) return false;
            this.loginLoading = false;
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
              this.loginLoading = true;
            }
          })
          .onPageEnd((event) => {
            const url = event?.url ?? '';
            const host = this.loginHost(url);
            if (host) {
              this.loginLoading = false;
              hilog.info(0xD005, 'DSHClient', 'account popup page ended %{public}s', host);
            }
            if (/^https:\/\/platform\.deepseek\.com\/dsh\/authorized(?:[/?#]|$)/.test(url)) {
              this.closeLogin();
            }
          })
          .onErrorReceive((event) => {
            if (!event?.request.isMainFrame() || event.error.getErrorCode() === -3) return;
            this.loginLoading = false;
            this.loginError = '登录页加载失败。请返回聊天重试，或使用 API Key。';
            hilog.error(0xD005, 'DSHClient', 'account popup network error %{public}d', event.error.getErrorCode());
          })
          .onHttpErrorReceive((event) => {
            if (!event?.request.isMainFrame()) return;
            this.loginLoading = false;
            this.loginError = '登录服务返回错误。请返回聊天重试，或使用 API Key。';
            hilog.error(0xD005, 'DSHClient', 'account popup HTTP error %{public}d', event.response.getResponseCode());
          })
          .onWindowExit(() => this.closeLogin())
        if (this.loginLoading) {
          this.loadingPage(this.loginAddress)
        }
      }.layoutWeight(1).width('100%')
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
      if (this.consentRequired) {
        this.privacyPage()
      } else if (this.launchUrl) {
        Web({ src: this.launchUrl, controller: this.controller })
          .layoutWeight(1)
          .width('100%')
          .visibility(this.loginVisible || this.recoveryOpen || this.privacyDetails || this.webFailed ? Visibility.None : Visibility.Visible)
          .javaScriptAccess(true)
          .domStorageAccess(true)
          .fileAccess(false)
          .multiWindowAccess(true)
          .allowWindowOpenMethod(true)
          .onWindowNew((event) => this.openLogin(event))
          .onLoadIntercept((event) => {
            if (!event || !event.data.isMainFrame()) return false;
            const url = event.data.getRequestUrl();
            if (url === RECOVERY_URL) {
              this.recoveryOpen = true;
              return true;
            }
            if (this.appGallery && url === PRIVACY_URL) {
              this.privacyDetails = true;
              return true;
            }
            return !url.startsWith('http://127.0.0.1:19592/') && url !== 'about:blank';
          })
          .onPageEnd(() => {
            hilog.info(0xD005, 'DSHClient', 'ArkWeb main page finished');
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
                ![RECOVERY_URL, PRIVACY_URL].includes(event.request.getRequestUrl())) {
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
        } else if (this.privacyDetails) {
          this.privacyPage()
        } else if (this.loginVisible) {
          this.loginPage()
        }
      } else {
        if (this.recoveryOpen) {
          this.recoveryPage()
        } else {
          this.loadingPage(this.status || '正在打开工作区…', this.startupFailed)
        }
      }
    }.height('100%').width('100%')
  }
}

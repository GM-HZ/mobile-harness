import { abilityAccessCtrl, common } from '@kit.AbilityKit';
import { url, util } from '@kit.ArkTS';
import { webview } from '@kit.ArkWeb';
import { hilog } from '@kit.PerformanceAnalysisKit';
import { BrowserSession, EngineProgress, dshEngine } from '../runtime/DshEngine';
import { ForgeAccount } from './ForgeAccount';
import { RemoteHostsPage } from './RemoteHosts';
import { isRemoteHostsEnabled } from '../runtime/RemoteHosts';
import { hasPrivacyConsent, isAppGalleryBuild, readAppGalleryLink, savePrivacyConsent } from '../runtime/PrivacyConsent';

const LOCAL_ORIGIN = 'http://127.0.0.1:19592';
const RECOVERY_URL = LOCAL_ORIGIN + '/.mobile-harness/recovery';
const GITHUB_URL = LOCAL_ORIGIN + '/.mobile-harness/github';
const PRIVACY_URL = LOCAL_ORIGIN + '/.mobile-harness/privacy';
const NOTICES_URL = LOCAL_ORIGIN + '/.mobile-harness/notices';
const SHELL_INK = '#132841';
const SHELL_SECONDARY = '#4D6279';
const SHELL_BLUE = '#1559C8';
const SHELL_BLUE_TINT = '#EDF5FF';
const SHELL_BORDER = '#D6E3F1';
type LoginFlow = 'unbound' | 'deepseek' | 'liveshare';

@Entry
@Component
struct Index {
  @State status: string = '正在准备本机 DSH…';
  @State consentRequired: boolean = false;
  @State appGallery: boolean = false;
  @State privacyDetails: boolean = false;
  @State noticesOpen: boolean = false;
  @State noticeTitle: string = '';
  @State noticeText: string = '';
  @State decliningPrivacy: boolean = false;
  @State consentError: string = '';
  @State privacyPolicyUrl: string = '';
  @State sourceDeliveryUrl: string = '';
  @State sourceLinkError: boolean = false;
  @State privacyLinkError: boolean = false;
  @State remoteHostsEnabled: boolean = false;
  @State remoteHostsOpen: boolean = false;
  @State launchUrl: string = '';
  @State recoveryOpen: boolean = false;
  @State recoveryFromSplash: boolean = false;
  @State forgeAccountOpen: boolean = false;
  @State safe: boolean = false;
  @State webFailed: boolean = false;
  @State progressPercent: number = 0;
  @State progressPhase: string = '环境准备';
  @State splashVisible: boolean = true;
  @State splashOpacity: number = 1;
  @State backgroundEnabled: boolean = false;
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
    this.appGallery = isAppGalleryBuild(context);
    this.remoteHostsEnabled = !this.appGallery && isRemoteHostsEnabled(context);
    if (this.appGallery) {
      this.privacyPolicyUrl = readAppGalleryLink(context, 'appgallery-privacy-url');
      this.sourceDeliveryUrl = readAppGalleryLink(context, 'appgallery-source-url');
      this.consentRequired = !hasPrivacyConsent(context, this.privacyPolicyUrl);
    }
    if (!this.consentRequired) this.attachEngine(context);
  }

  private attachEngine(context: common.UIAbilityContext): void {
    this.detachEngine = dshEngine.attach(context, (status: string, session?: BrowserSession,
      progress?: EngineProgress, failed?: boolean) => {
      this.status = status;
      if (progress) {
        this.progressPhase = progress.phase;
        this.progressPercent = Math.max(this.progressPercent, progress.percent);
      }
      this.safe = session?.safe === true;
      if (failed || (this.safe && !this.launchUrl)) {
        this.recoveryFromSplash = false;
        this.recoveryOpen = true;
        this.splashVisible = false;
      }
      this.backgroundEnabled = dshEngine.isBackgroundEnabled();
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
    if (this.remoteHostsOpen) {
      this.remoteHostsOpen = false;
      return true;
    }
    if (this.noticesOpen) {
      this.backFromNotices();
      return true;
    }
    if (this.privacyDetails) {
      this.privacyDetails = false;
      return true;
    }
    if (this.recoveryOpen && !this.webFailed && (this.launchUrl || this.recoveryFromSplash)) {
      if (!this.restarting) this.returnFromRecovery();
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

  private openSourceDelivery(): void {
    const context = this.getUIContext().getHostContext() as common.UIAbilityContext;
    this.sourceLinkError = false;
    context.openLink(this.sourceDeliveryUrl, { appLinkingOnly: false }).catch(() => {
      this.sourceLinkError = true;
    });
  }

  private backFromNotices(): void {
    if (this.noticeTitle) this.noticeTitle = '';
    else this.noticesOpen = false;
  }

  private selectNotice(title: string, filename: string): void {
    const context = this.getUIContext().getHostContext() as common.UIAbilityContext;
    try {
      this.noticeText = util.TextDecoder.create('utf-8')
        .decodeToString(context.resourceManager.getRawFileContentSync(filename));
    } catch (_) {
      this.noticeText = '无法读取此声明。';
    }
    this.noticeTitle = title;
  }

  @Builder
  private noticesPage() {
    Scroll() {
      Column({ space: 12 }) {
        Button('返回').onClick(() => this.backFromNotices())
        Text(this.noticeTitle || '开源软件声明').fontSize(24).fontWeight(FontWeight.Medium)
        if (this.noticeTitle) {
          Text(this.noticeText).fontSize(14).copyOption(CopyOptions.LocalDevice)
        } else {
          if (this.sourceDeliveryUrl) {
            Button('获取对应源码').onClick(() => this.openSourceDelivery())
            if (this.sourceLinkError) {
              Text('无法打开链接。可在浏览器中访问：' + this.sourceDeliveryUrl)
                .copyOption(CopyOptions.LocalDevice)
            }
          }
          Button('DeepSeek Harness').onClick(() => this.selectNotice('DeepSeek Harness', 'LICENSE.dsh.txt'))
          Button('dshm').onClick(() => this.selectNotice('dshm', 'LICENSE.dshm.txt'))
          Button('Node.js').onClick(() => this.selectNotice('Node.js', 'LICENSE.node.txt'))
          Button('sharp').onClick(() => this.selectNotice('sharp', 'LICENSE.sharp.txt'))
          Button('工作区搜索').onClick(() => this.selectNotice('工作区搜索', 'NOTICE.workspace-search.txt'))
          Button('ripgrep').onClick(() => this.selectNotice('ripgrep', 'LICENSE.ripgrep.txt'))
          Button('Koffi').onClick(() => this.selectNotice('Koffi', 'LICENSE.koffi.txt'))
          Button('DSH System').onClick(() => this.selectNotice('DSH System', 'LICENSE.dsh-system.txt'))
          Button('Node.js require-builtin').onClick(() =>
            this.selectNotice('Node.js require-builtin', 'LICENSE.require-builtin.txt'))
        }
      }.padding(24).width('100%').alignItems(HorizontalAlign.Start)
    }.width('100%').layoutWeight(1)
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
      this.recoveryFromSplash = false;
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
      this.recoveryFromSplash = false;
      this.recoveryOpen = false;
    } catch (_) {
      this.restartError = '没有可用的插件快照，或无法自动重开。';
    }
    this.restarting = false;
  }

  private returnFromRecovery(): void {
    if (this.recoveryFromSplash && !this.launchUrl) {
      this.splashOpacity = 1;
      this.splashVisible = true;
    }
    this.recoveryFromSplash = false;
    this.recoveryOpen = false;
  }

  @Builder
  private restartButton(label: string, primary: boolean, mode: string) {
    Button(label, { type: ButtonType.Normal })
      .width('100%').constraintSize({ minHeight: 50 })
      .padding({ left: 16, right: 16, top: 10, bottom: 10 })
      .fontSize(16).fontWeight(FontWeight.Medium)
      .fontColor(primary ? Color.White : SHELL_BLUE)
      .backgroundColor(primary ? SHELL_BLUE : Color.White)
      .border({ width: 1, radius: 14, color: primary ? SHELL_BLUE : SHELL_BORDER })
      .enabled(!this.restarting).onClick(() => { this.restart(mode); })
  }

  @Builder
  private recoveryPage() {
    Scroll() {
      Column() {
        if (!this.webFailed && (this.launchUrl || this.recoveryFromSplash)) {
          Button(this.launchUrl ? '返回会话' : '返回启动页', { type: ButtonType.Normal })
            .constraintSize({ minHeight: 44 }).padding({ left: 14, right: 14 })
            .borderRadius(12).fontSize(14).fontWeight(FontWeight.Medium)
            .fontColor(SHELL_BLUE).backgroundColor(SHELL_BLUE_TINT)
            .enabled(!this.restarting).onClick(() => { this.returnFromRecovery(); })
            .margin({ bottom: 22 })
        }
        Row({ space: 16 }) {
          Column({ space: 7 }) {
            Text('运行时恢复').fontSize(30).fontWeight(FontWeight.Bold).fontColor(SHELL_INK)
            Text('重开应用会保留会话与工作区。').fontSize(14).fontColor(SHELL_SECONDARY)
          }.alignItems(HorizontalAlign.Start).layoutWeight(1)
          Image($r('app.media.dsh_mh_whale')).width(62).height(62)
            .objectFit(ImageFit.Contain).accessibilityLevel('no')
        }.width('100%')
        if (this.webFailed || this.safe || this.status) {
          Row({ space: 10 }) {
            Circle({ width: 8, height: 8 }).fill(this.webFailed ? '#A95516' : SHELL_BLUE)
            Text(this.webFailed ? '本机 DSH 页面加载失败。' :
              (this.safe ? '当前处于安全模式。' : this.status))
              .fontSize(14).fontColor(this.webFailed ? '#803C16' : SHELL_INK).layoutWeight(1)
          }.width('100%').padding(14).borderRadius(12).margin({ top: 20 })
            .backgroundColor(this.webFailed ? '#FFF2E6' : SHELL_BLUE_TINT)
        }
        Text('安全模式使用最小配置启动，便于排查启动问题。')
          .fontSize(14).fontColor(SHELL_SECONDARY).lineHeight(21).margin({ top: 20, bottom: 12 })
        Column({ space: 10 }) {
          if (this.safe) {
            this.restartButton('以正常模式重开', true, 'normal')
            this.restartButton('以安全模式重开', false, 'safe')
          } else {
            this.restartButton('以安全模式重开', true, 'safe')
            this.restartButton('以正常模式重开', false, 'normal')
          }
        }.width('100%')
        if (this.restarting || this.restartError) {
          Text(this.restartError || '正在重开应用…')
            .fontSize(14).fontColor(this.restartError ? '#803C16' : SHELL_SECONDARY)
            .margin({ top: 14 })
        }
        if (!this.appGallery) {
          Column() {
            Row({ space: 12 }) {
              Column({ space: 5 }) {
                Text('后台常驻').fontSize(15).fontWeight(FontWeight.Medium).fontColor(SHELL_INK)
                Text(this.backgroundEnabled ? '本机服务在后台保持运行' : '切到后台后，系统可能暂停任务')
                  .fontSize(13).fontColor(SHELL_SECONDARY)
              }.alignItems(HorizontalAlign.Start).layoutWeight(1)
              Toggle({ type: ToggleType.Switch, isOn: this.backgroundEnabled })
                .selectedColor(SHELL_BLUE).accessibilityText('后台常驻')
                .onChange((isOn: boolean) => {
                  this.backgroundEnabled = isOn;
                  const context = this.getUIContext().getHostContext() as common.UIAbilityContext;
                  dshEngine.setBackgroundEnabled(context, isOn);
                })
            }.width('100%').padding(14)
            Divider().color(SHELL_BORDER).margin({ left: 14, right: 14 })
            Button('回滚插件配置并正常重开', { type: ButtonType.Normal })
              .width('100%').constraintSize({ minHeight: 48 }).padding({ left: 14, right: 14 })
              .fontSize(14).fontWeight(FontWeight.Medium).fontColor(SHELL_BLUE)
              .backgroundColor(Color.Transparent)
              .enabled(!this.restarting).onClick(() => { this.rollbackPlugins(); })
          }.width('100%').backgroundColor('#F4F8FD').borderRadius(16).clip(true)
            .border({ width: 1, color: SHELL_BORDER }).margin({ top: 22 })
        }
        if (this.remoteHostsEnabled && !this.safe) {
          Button('远程主机（实验）', { type: ButtonType.Normal })
            .width('100%').constraintSize({ minHeight: 48 }).borderRadius(14)
            .fontSize(14).fontColor(SHELL_BLUE).backgroundColor(SHELL_BLUE_TINT)
            .margin({ top: 12 }).onClick(() => { this.remoteHostsOpen = true; })
        }
      }.width('100%').constraintSize({ maxWidth: 440 })
        .alignItems(HorizontalAlign.Start).padding({ top: 24, bottom: 28, left: 24, right: 24 })
    }.width('100%').height('100%').backgroundColor($r('app.color.start_window_background'))
      .align(Alignment.Top)
  }

  @Builder
  private splashScreen() {
    Column() {
      Stack({ alignContent: Alignment.Center }) {
        Scroll() {
          Column() {
            Image($r('app.media.dsh_mh_whale')).width(144).height(144)
              .objectFit(ImageFit.Contain).accessibilityLevel('no')
            Text('DeepSeek Harness').fontSize(28).fontWeight(FontWeight.Bold).fontColor(SHELL_INK)
              .textAlign(TextAlign.Center).margin({ top: 8 })
            Column({ space: 10 }) {
              Row({ space: 12 }) {
                Text(this.progressPhase).fontSize(14).fontWeight(FontWeight.Medium).fontColor(SHELL_INK)
                  .layoutWeight(1)
                Text(this.progressPercent + '%').fontSize(14).fontWeight(FontWeight.Medium).fontColor(SHELL_BLUE)
              }.width('100%')
              Progress({ value: this.progressPercent, total: 100, type: ProgressType.Linear })
                .width('100%').style({ strokeWidth: 6 }).color('#1886E6').backgroundColor('#D6E7F6')
              if (this.status) {
                Text(this.status).fontSize(13).fontColor(SHELL_SECONDARY).width('100%')
              }
            }.width('100%').padding(16).borderRadius(16).backgroundColor(SHELL_BLUE_TINT)
              .alignItems(HorizontalAlign.Start).margin({ top: 30 })
          }.width('100%').constraintSize({ maxWidth: 368 })
            .padding({ top: 16, bottom: 16, left: 24, right: 24 }).alignItems(HorizontalAlign.Center)
        }.width('100%').scrollBar(BarState.Off)
      }.width('100%').layoutWeight(1)
      Button('恢复选项', { type: ButtonType.Normal })
        .constraintSize({ minHeight: 44 }).padding({ left: 20, right: 20 })
        .fontSize(14).fontWeight(FontWeight.Medium).fontColor(SHELL_BLUE)
        .backgroundColor(Color.White).border({ width: 1, radius: 22, color: SHELL_BORDER })
        .margin({ top: 8, bottom: 20 })
        .onClick(() => {
          this.recoveryFromSplash = true;
          this.splashVisible = false;
          this.recoveryOpen = true;
        })
    }.width('100%').height('100%').backgroundColor($r('app.color.start_window_background'))
      .alignItems(HorizontalAlign.Center).opacity(this.splashOpacity)
  }

  build() {
    Stack({ alignContent: Alignment.Center }) {
      if (!this.consentRequired && this.launchUrl) {
        Web({ src: this.launchUrl, controller: this.controller })
          .layoutWeight(1)
          .width('100%')
          .visibility(this.loginVisible || this.recoveryOpen || this.forgeAccountOpen || this.webFailed ||
            this.privacyDetails || this.noticesOpen || this.remoteHostsOpen ? Visibility.None : Visibility.Visible)
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
              this.recoveryFromSplash = false;
              this.splashVisible = false;
              this.recoveryOpen = true;
              return true;
            }
            if (url === GITHUB_URL) {
              if (!this.safe && !this.appGallery) this.forgeAccountOpen = true;
              return true;
            }
            if (this.appGallery && url === PRIVACY_URL) {
              this.privacyDetails = true;
              return true;
            }
            if (this.appGallery && url === NOTICES_URL) {
              this.noticeTitle = '';
              this.sourceLinkError = false;
              this.noticesOpen = true;
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
                ![RECOVERY_URL, GITHUB_URL, PRIVACY_URL, NOTICES_URL].includes(event.request.getRequestUrl())) {
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
      if (this.consentRequired || this.privacyDetails) {
        this.privacyPage()
      } else if (this.noticesOpen) {
        this.noticesPage()
      } else if (this.remoteHostsOpen && this.remoteHostsEnabled) {
        RemoteHostsPage({ onClose: () => { this.remoteHostsOpen = false; } })
      } else if (this.webFailed || this.recoveryOpen) {
        this.recoveryPage()
      } else if (this.forgeAccountOpen) {
        ForgeAccount({ onClose: () => { this.forgeAccountOpen = false; } })
      } else if (this.loginVisible) {
        this.loginPage()
      }
      if (this.splashVisible && !this.consentRequired && !this.recoveryOpen && !this.loginVisible &&
          !this.forgeAccountOpen && !this.webFailed) {
        this.splashScreen()
      }
    }.height('100%').width('100%')
  }
}

import { common, childProcessManager } from '@kit.AbilityKit';
import { BusinessError } from '@kit.BasicServicesKit';
import { fileIo } from '@kit.CoreFileKit';
import fileIO from '@ohos.fileio';
import zlib from '@ohos.zlib';
import { connection } from '@kit.NetworkKit';
import { hilog } from '@kit.PerformanceAnalysisKit';
import { i18n } from '@kit.LocalizationKit';
import poc from 'libpoc.so';
import { BootRecovery } from './BootRecovery';
import { backgroundKeeper } from './BackgroundKeeper';
import { isAppGalleryBuild, readAppGalleryLink } from './PrivacyConsent';
import { migrateSignedJq } from './SignedJqMigration';

interface LayerChunk {
  file: string;
  sha256: string;
}

interface LayerManifest {
  chunks: LayerChunk[];
}

export interface EngineProgress {
  phase: string;
  percent: number;
}

export interface BrowserSession {
  url: string;
  cookie?: string;
  safe?: boolean;
}
type EngineListener = (status: string, session?: BrowserSession, progress?: EngineProgress,
  failed?: boolean) => void;

class DshEngine {
  private listeners: Set<EngineListener> = new Set<EngineListener>();
  private failed: boolean = false;
  private status: string = '正在准备本机 DSH…';
  private progress: EngineProgress = { phase: '环境准备', percent: 0 };
  private backgroundPreference: boolean = false;
  private session?: BrowserSession;
  private running: boolean = false;
  private nativePoll: number = -1;

  attach(context: common.UIAbilityContext, listener: EngineListener): () => void {
    this.listeners.add(listener);
    listener(this.status, this.session, this.progress, this.failed);
    if (!this.running) {
      this.running = true;
      this.start(context);
    } else {
      hilog.info(0xD005, 'DSHClient', 'engine subscriber joined ready=%{public}s', String(this.session !== undefined));
    }
    return () => { this.listeners.delete(listener); };
  }

  private publish(status: string, session?: BrowserSession, progress?: EngineProgress,
    failed: boolean = false): void {
    this.status = status;
    this.failed = failed;
    this.session = session;
    if (progress) this.progress = progress;
    this.listeners.forEach(listener => listener(status, session, progress ?? this.progress, failed));
  }

  private writeMode(path: string, mode: string): void {
    try {
      const file = fileIo.openSync(path, fileIo.OpenMode.WRITE_ONLY | fileIo.OpenMode.CREATE | fileIo.OpenMode.TRUNC);
      try { fileIo.writeSync(file.fd, mode); } finally { fileIo.closeSync(file.fd); }
    } catch (e) {
      hilog.warn(0xD005, 'DSHClient', 'could not save PRoot acceleration choice');
    }
  }

  private async acceleration(context: common.UIAbilityContext, modeFile: string): Promise<boolean> {
    if (fileIo.accessSync(modeFile)) {
      const prior = fileIo.readTextSync(modeFile);
      if (prior === 'fast' || prior === 'compat') {
        hilog.info(0xD005, 'DSHClient', 'seccomp cached mode=%{public}s', prior);
        return prior === 'fast';
      }
    }
    this.publish('正在检查本机运行环境…');
    const start = Date.now();
    const result = await poc.run('proot-embedded-packaged-node-jitless-secprobe', context.filesDir);
    const output = fileIo.readTextSync(context.filesDir + '/proot-seccomp-probe.txt');
    const enabled = output.includes('ptrace acceleration (seccomp mode 2,');
    const completed = result.startsWith('exit=0 signal=0 wait_errno=0') && output.includes('DSH_SECCOMP_PROBE_OK');
    const fast = enabled && completed;
    hilog.info(0xD005, 'DSHClient',
      'seccomp probe enabled=%{public}s passed=%{public}s mode=%{public}s ms=%{public}d',
      String(enabled), String(completed), fast ? 'fast' : 'compat', Date.now() - start);
    this.writeMode(modeFile, fast ? 'fast' : 'compat');
    return fast;
  }

  private async run(context: common.UIAbilityContext, launchFile: string, fast: boolean, started: number): Promise<boolean> {
    if (fileIo.accessSync(launchFile)) fileIo.unlinkSync(launchFile);
    this.publish('正在启动 DeepSeek Harness…');
    let ready = false;
    const poll = setInterval(() => {
      try {
        if (fileIo.accessSync(launchFile)) {
          const session = JSON.parse(fileIo.readTextSync(launchFile)) as BrowserSession;
          if (!/^http:\/\/127\.0\.0\.1:19592\/(?:\?token=[A-Za-z0-9_%-]+)?$/.test(session.url)) {
            throw new Error('Invalid local session');
          }
          ready = true;
          clearInterval(poll);
          this.publish('', session);
          hilog.info(0xD005, 'DSHClient', 'loopback session ready ms=%{public}d mode=%{public}s',
            Date.now() - started, fast ? 'fast' : 'compat');
        } else if (Date.now() - started > 90000) {
          this.publish('正在初始化本机 DSH…');
        }
      } catch (e) {
        clearInterval(poll);
        this.publish('本机 DSH 页面初始化失败。', undefined, undefined, true);
        hilog.error(0xD005, 'DSHClient', 'browser session setup failed');
      }
    }, 300);
    const stage = 'proot-embedded-packaged-dsh-jitless-shim-client' + (fast ? '-fast' : '');
    try {
      hilog.info(0xD005, 'DSHClient', 'starting PRoot ms=%{public}d mode=%{public}s',
        Date.now() - started, fast ? 'fast' : 'compat');
      await poc.run(stage, context.filesDir);
      return ready;
    } finally {
      clearInterval(poll);
      hilog.info(0xD005, 'DSHClient', 'engine process ended ready=%{public}s mode=%{public}s',
        String(ready), fast ? 'fast' : 'compat');
    }
  }

  private runNative(context: common.UIAbilityContext, root: string, started: number, mode: string): void {
    const launchFile = root + '/tmp/dsh-client-native-launch';
    if (fileIo.accessSync(launchFile)) fileIo.unlinkSync(launchFile);
    if (fileIo.accessSync(root + '/tmp/dsh-native-timeline.log')) fileIo.unlinkSync(root + '/tmp/dsh-native-timeline.log');
    const appGallery = isAppGalleryBuild(context);
    for (const name of ['dsh-native-web.cjs', 'dsh-harmony-http.cjs', 'dsh-harmony-llhttp.cjs']) {
      this.copyGuest(context, name, root + '/' + name);
    }
    if (appGallery) {
      for (const name of ['appgallery.patch.yml', 'dsh-native-image.cjs', 'dsh-native-search.cjs',
        'dsh-harmony-fs.mjs']) {
        this.copyGuest(context, name, root + '/' + name);
      }
    } else {
      const appGalleryPatch = root + '/appgallery.patch.yml';
      if (fileIo.accessSync(appGalleryPatch)) fileIo.unlinkSync(appGalleryPatch);
      this.copyGuest(context, 'dsh-harmony-subprocess.mjs', root + '/dsh-harmony-subprocess.mjs');
      this.copyGuest(context, 'dsh-harmony-bash-pipe.mjs', root + '/dsh-harmony-bash-pipe.mjs');
      this.copyGuest(context, 'dsh-harmony-fs.mjs', root + '/dsh-harmony-fs.mjs');
      this.copyGuest(context, 'dsh-harmony-signed-programs.json', root + '/dsh-harmony-signed-programs.json');
      this.copyGuest(context, 'dsh-harmony-sharp.cjs', root + '/dsh-harmony-sharp.cjs');
      this.copyGuest(context, 'dsh-harmony-package.cjs', root + '/dsh-harmony-package.cjs');
      this.copyGuest(context, 'dsh-harmony-forge.cjs', root + '/dsh-harmony-forge.cjs');
      this.copyGuest(context, 'dsh-harmony-inspector-worker.cjs', root + '/dsh-harmony-inspector-worker.cjs');
      this.copyGuest(context, 'dsh-harmony-liveshare.cjs', root + '/dsh-harmony-liveshare.cjs');
      this.copyGuest(context, 'dsh-harmony-speech.cjs', root + '/dsh-harmony-speech.cjs');
      this.copyGuest(context, 'dsh-harmony-pnpm-fetch.cjs', root + '/dsh-harmony-pnpm-fetch.cjs');
      this.copyGuest(context, 'dsh-harmony-workflow.cjs', root + '/dsh-harmony-workflow.cjs');
      this.copyGuest(context, 'dsh-harmony-workflow-wire.cjs', root + '/dsh-harmony-workflow-wire.cjs');
      this.copyGuest(context, 'dsh-harmony-workflow-worker.cjs', root + '/dsh-harmony-workflow-worker.cjs');
      for (const name of ['dsh-harmony-office.cjs', 'dsh-harmony-office-launch.cjs', 'dsh-harmony-office-entry.mjs', 'dsh-harmony-office-worker.mjs']) {
        this.copyGuest(context, name, root + '/' + name);
      }
      const ptc = context.resourceManager.getRawFileContentSync('dsh-harmony-ptc-enabled');
      this.copyGuest(context, 'dsh-harmony-ptc-enabled', root + '/dsh-harmony-ptc-enabled');
      if (ptc[0] === 49) {
        for (const name of ['amaro.cjs', 'instantiate.cjs', 'dsh-harmony-ptc.cjs', 'dsh-harmony-ptc-worker.mjs']) {
          this.copyGuest(context, name, root + '/' + name);
        }
      }
    }
    const recovery = new BootRecovery(context.filesDir);
    recovery.write(mode, true);
    this.publish(mode === 'safe' ? '正在启动安全模式…' : '正在启动本机 DeepSeek Harness…');
    hilog.info(0xD005, 'DSHClient', 'starting native Web ms=%{public}d', Date.now() - started);
    if (poc.usesHostProcess()) {
      hilog.info(0xD005, 'DSHClient', 'system child-process support native=%{public}s ark=%{public}s',
        String(childProcessManager.isNativeChildProcessSupported()), String(childProcessManager.isArkChildProcessSupported()));
    }
    const dshRelease = root + '/.dsh-0.2.2-rc.5';
    let optionalId = '';
    try {
      for (const byte of context.resourceManager.getRawFileContentSync('dsh-optional-runtime-id.txt')) {
        optionalId += String.fromCharCode(byte);
      }
    } catch (error) {
      optionalId = '';
    }
    this.publish('正在启动本机 Harness…', undefined, { phase: '启动服务', percent: 72 });
    const nativeStarted = Date.now();
    poc.startNative(root, mode === 'safe');
    let ready = false;
    this.nativePoll = setInterval(() => {
      try {
        const status = poc.nativeStatus();
        if (status < 0) {
          this.stopPolling();
          this.publish('本机 DSH 未运行。可在恢复选项中选择安全模式。', undefined, undefined, true);
          hilog.error(0xD005, 'DSHClient', 'native Host unavailable status=%{public}d', status);
        } else if (!ready && fileIo.accessSync(launchFile)) {
          const session = JSON.parse(fileIo.readTextSync(launchFile)) as BrowserSession;
          if (session.url !== 'http://127.0.0.1:19592/' || !session.cookie) {
            throw new Error('Invalid native browser session');
          }
          recovery.write(mode, false);
          if (mode === 'normal') this.savePluginSnapshot(context, root);
          ready = true;
          session.safe = mode === 'safe';
          this.publish('', session, { phase: '加载界面', percent: 90 });
          if (!appGallery && this.backgroundPreference) void backgroundKeeper.start(context);
          hilog.info(0xD005, 'DSHClient', 'native loopback ready ms=%{public}d mode=%{public}s',
            Date.now() - started, mode);
        } else if (!ready && Date.now() - nativeStarted > 60000) {
          this.stopPolling();
          this.publish('本机 DSH 启动超时。可在恢复选项中选择安全模式。', undefined, undefined, true);
          hilog.error(0xD005, 'DSHClient', 'native Host startup timed out status=%{public}d', status);
        }
      } catch (e) {
        this.stopPolling();
        this.publish('本机 DSH 页面初始化失败。可从恢复选项重试。', undefined, undefined, true);
        hilog.error(0xD005, 'DSHClient', 'native launch descriptor invalid');
      }
    }, 200);
  }

  private pluginProfileFiles(context: common.UIAbilityContext, root: string): string[] {
    const name = isAppGalleryBuild(context) ? 'mobile-appgallery' : 'web';
    const profile = root + '/native-benchmark-home/profiles/' + name;
    return [profile + '/cordis.patch.yml', profile + '/cordis.yml',
      profile + '/package.json', profile + '/pnpm-lock.yaml'];
  }

  private loadBackgroundPreference(context: common.UIAbilityContext): void {
    try {
      const path = context.filesDir + '/background-enabled.json';
      const text = fileIo.readTextSync(path);
      this.backgroundPreference = text.includes('"enabled":true');
    } catch (error) {
      this.backgroundPreference = false;
    }
  }

  isBackgroundEnabled(): boolean {
    return this.backgroundPreference;
  }

  async setBackgroundEnabled(context: common.UIAbilityContext, enabled: boolean): Promise<void> {
    this.backgroundPreference = enabled;
    try {
      const path = context.filesDir + '/background-enabled.json';
      const file = fileIo.openSync(path,
        fileIo.OpenMode.WRITE_ONLY | fileIo.OpenMode.CREATE | fileIo.OpenMode.TRUNC);
      try {
        fileIo.writeSync(file.fd, JSON.stringify({ enabled: enabled }) + '\n');
      } finally { fileIo.closeSync(file); }
    } catch (error) {
      hilog.warn(0xD005, 'DSHClient', 'background preference write failed');
    }
    if (enabled) {
      await backgroundKeeper.start(context);
    } else {
      await backgroundKeeper.stop(context);
    }
  }

  extractOptional(context: common.UIAbilityContext): void {
    const root = context.filesDir + '/alpine';
    if (isAppGalleryBuild(context)) return;
    const dshRelease = root + '/.dsh-0.2.2-rc.5';
    let identity = '';
    try {
      for (const byte of context.resourceManager.getRawFileContentSync('dsh-optional-runtime-id.txt')) {
        identity += String.fromCharCode(byte);
      }
    } catch (error) {
      identity = '';
    }
    if (/^[a-f0-9]{64}$/.test(identity)) {
      void this.prepareOptionalLayer(context, dshRelease, identity);
    }
  }

  private async prepareOptionalLayer(context: common.UIAbilityContext, dshRelease: string,
                                     identity: string): Promise<void> {
    const phase = Date.now();
    try {
      const extracted = await this.unpack(context, 'dsh-layer-optional.zip', dshRelease, identity);
      hilog.info(0xD005, 'DSHClient', 'optional layer extracted=%{public}s ms=%{public}d',
        String(extracted), Date.now() - phase);
    } catch (error) {
      hilog.warn(0xD005, 'DSHClient', 'optional layer unavailable: %{public}s', String(error));
    }
  }

  private savePluginSnapshot(context: common.UIAbilityContext, root: string): void {
    const snapshot = context.filesDir + '/plugin-snapshot';
    try {
      if (!fileIo.accessSync(snapshot)) fileIo.mkdirSync(snapshot, true);
      for (const source of this.pluginProfileFiles(context, root)) {
        if (!fileIo.accessSync(source)) continue;
        const name = source.substring(source.lastIndexOf('/') + 1);
        fileIo.copyFileSync(source, snapshot + '/' + name + '.tmp');
        fileIo.renameSync(snapshot + '/' + name + '.tmp', snapshot + '/' + name);
      }
      hilog.info(0xD005, 'DSHClient', 'plugin snapshot saved');
    } catch (e) {
      hilog.warn(0xD005, 'DSHClient', 'plugin snapshot unavailable');
    }
  }

  private restorePluginSnapshot(context: common.UIAbilityContext, root: string): boolean {
    const snapshot = context.filesDir + '/plugin-snapshot';
    let restored = false;
    try {
      for (const target of this.pluginProfileFiles(context, root)) {
        const name = target.substring(target.lastIndexOf('/') + 1);
        const source = snapshot + '/' + name;
        if (!fileIo.accessSync(source)) continue;
        fileIo.copyFileSync(source, target + '.restore');
        fileIo.renameSync(target + '.restore', target);
        restored = true;
      }
    } catch (e) {
      hilog.error(0xD005, 'DSHClient', 'plugin rollback failed');
      return false;
    }
    if (restored) hilog.info(0xD005, 'DSHClient', 'plugin snapshot restored');
    return restored;
  }

  async restartWithPluginRollback(context: common.UIAbilityContext): Promise<void> {
    const root = context.filesDir + '/alpine';
    if (!this.restorePluginSnapshot(context, root)) {
      throw new Error('No plugin snapshot available');
    }
    await this.restart(context, 'normal');
  }

  async restart(context: common.UIAbilityContext, mode: string): Promise<void> {
    const recovery = new BootRecovery(context.filesDir);
    recovery.write(mode, false);
    if (poc.usesHostProcess() && poc.nativeStatus() !== 0) {
      this.stopPolling();
      this.publish('正在重启本机 Host…');
      if (poc.nativeStatus() > 0) {
        poc.stopNative();
        for (let attempt = 0; attempt < 25 && poc.nativeStatus() > 0; attempt++) {
          await new Promise<void>((resolve) => { setTimeout(resolve, 100); });
          if (poc.nativeStatus() > 0) poc.stopNative();
        }
      }
      if (poc.nativeStatus() > 0) throw new Error('Host has not exited');
      await this.start(context);
      return;
    }
    await context.restartApp({ bundleName: context.abilityInfo.bundleName, abilityName: context.abilityInfo.name });
  }

  private stopPolling(): void {
    if (this.nativePoll < 0) return;
    clearInterval(this.nativePoll);
    this.nativePoll = -1;
  }

  private async start(context: common.UIAbilityContext): Promise<void> {
    const started = Date.now();
    const root = context.filesDir + '/alpine';
    const launchFile = root + '/tmp/dsh-client-launch';
    const modeFile = context.filesDir + '/proot-seccomp-0.4.4';
    let nativeStarted = false;
    try {
      const state = new BootRecovery(context.filesDir).read();
      if (state.pending && state.mode === 'safe') {
        this.publish('上次安全启动未完成。请选择恢复选项。', undefined, undefined, true);
        return;
      }
      const mode = state.pending ? 'safe' : state.mode;
      this.publish('正在准备运行环境…', undefined, { phase: '环境准备', percent: 5 });
      if (isAppGalleryBuild(context)) {
        await this.startAppGallery(context, root, started, mode);
        nativeStarted = true;
        return;
      }
      for (const name of ['bin', 'lib', 'etc', 'tmp', 'root', 'dsh']) {
        const path = root + '/' + name;
        if (!fileIo.accessSync(path)) fileIo.mkdirSync(path, true);
      }
      this.copyGuest(context, 'alpine-busybox', root + '/bin/busybox');
      this.copyGuest(context, 'alpine-busybox', root + '/bin/sh');
      this.copyGuest(context, 'alpine-ld-musl', root + '/lib/ld-musl-aarch64.so.1');
      this.copyGuest(context, 'alpine-release', root + '/etc/alpine-release');
      const dshRelease = root + '/.dsh-0.2.2-rc.5';
      if (!fileIo.accessSync(dshRelease)) fileIo.mkdirSync(dshRelease, true);
      // The layer is shipped as package-grouped chunks with a manifest. An
      // upgrade only re-extracts chunks whose identity changed; a first boot
      // extracts every chunk. This keeps upgrades fast without a custom zip
      // reader on device.
      let manifestText = '';
      for (const byte of context.resourceManager.getRawFileContentSync('dsh-chunks.json')) {
        manifestText += String.fromCharCode(byte);
      }
      const manifest = JSON.parse(manifestText) as LayerManifest;
      if (!Array.isArray(manifest.chunks) || manifest.chunks.length === 0) {
        throw new Error('Invalid packaged DSH chunk manifest');
      }
      const dshUnpackStarted = Date.now();
      let extractedChunks = 0;
      // Sequential extraction is faster on device: concurrent ArkTS zlib
      // decompression into the same tree serializes on I/O and delays startup.
      for (let chunkIndex = 0; chunkIndex < manifest.chunks.length; chunkIndex++) {
        const chunk = manifest.chunks[chunkIndex];
        if (!/^dsh-layer-[0-9]+\.zip$/.test(chunk.file) || !/^[a-f0-9]{64}$/.test(chunk.sha256)) {
          throw new Error('Invalid packaged DSH chunk entry');
        }
        this.publish('正在解包核心组件…', undefined,
          { phase: '解包核心组件', percent: 8 + Math.round(45 * (chunkIndex + 1) / manifest.chunks.length) });
        if (await this.unpack(context, chunk.file, dshRelease, chunk.sha256)) extractedChunks++;
      }
      await this.unpackAuxLayers(context, root, mode);
      this.publish('正在准备运行时…', undefined, { phase: '环境准备', percent: 56 });
      hilog.info(0xD005, 'DSHClient', 'startup chunks extracted=%{public}d/%{public}d ms=%{public}d',
        extractedChunks, manifest.chunks.length, Date.now() - dshUnpackStarted);
      this.publish('正在准备本地服务…', undefined, { phase: '启动服务', percent: 66 });
      this.prepareTimezone(root);

      for (const name of ['fetch-shim.cjs', 'fetch-shim-boot.cjs', 'dsh-client.cjs', 'dsh-boot-cache.cjs',
        'dsh-client.patch.yml', 'dsh-seccomp-probe.cjs']) {
        this.copyGuest(context, name, root + '/' + name);
      }
      this.prepareSelfBuildTools(context, root, mode !== 'safe');
      if (mode === 'safe' || !fileIo.accessSync(context.filesDir + '/legacy-proot.enabled')) {
        await this.prepareResolver(root);
        this.runNative(context, root, started, mode);
        nativeStarted = true;
        return;
      }
      this.copyGuest(context, 'dsh-startup-sources.gz', root + '/dsh-startup-sources.gz');
      await this.prepareResolver(root);
      const fast = await this.acceleration(context, modeFile);
      const ready = await this.run(context, launchFile, fast, started);
      if (fast && !ready) {
        hilog.warn(0xD005, 'DSHClient', 'accelerated launch failed before readiness; retrying compatibility mode');
        this.writeMode(modeFile, 'compat');
        await this.run(context, launchFile, false, started);
      }
      this.publish('本机 DSH 服务已退出。重新打开可重试。', undefined, undefined, true);
    } catch (e) {
      this.publish('本机 DSH 准备失败。重新打开可重试。', undefined, undefined, true);
      hilog.error(0xD005, 'DSHClient', 'setup error %{public}s', String(e));
    } finally {
      if (!nativeStarted) this.running = false;
    }
  }

  private async startAppGallery(context: common.UIAbilityContext, root: string,
                                started: number, mode: string): Promise<void> {
    const release = root + '/.dsh-0.2.2-rc.5';
    for (const directory of [release, root + '/tmp', root + '/etc']) {
      if (!fileIo.accessSync(directory)) fileIo.mkdirSync(directory, true);
    }
    const archive = 'dsh-appgallery-layer.zip';
    const identity = readAppGalleryLink(context, archive + '.sha256').trim();
    if (!/^[a-f0-9]{64}$/.test(identity)) throw new Error('Invalid AppGallery runtime identity');
    this.publish('正在解包核心组件…', undefined, { phase: '解包核心组件', percent: 20 });
    await this.unpack(context, archive, release, identity);
    for (const name of ['fetch-shim.cjs', 'dsh-client.patch.yml']) {
      this.copyGuest(context, name, root + '/' + name);
    }
    this.runNative(context, root, started, mode);
  }

  private async unpackAuxLayers(context: common.UIAbilityContext, root: string, mode: string): Promise<void> {
    for (const archive of ['node-layer.zip', 'shell-tools-layer.zip',
      'shell-extras-v4.zip', 'pnpm-layer-v2.zip']) {
      const phase = Date.now();
      const identity = archive === 'shell-extras-v4.zip' ? this.layerIdentity(context, 'shell-extras-v4-id.txt') : '';
      const extracted = await this.unpack(context, archive, root, identity);
      hilog.info(0xD005, 'DSHClient', 'startup archive %{public}s extracted=%{public}s ms=%{public}d',
        archive, String(extracted), Date.now() - phase);
    }
    if (mode !== 'safe') {
      const wheelId = this.layerIdentity(context, 'workspace-python-id.txt');
      const phase = Date.now();
      const extracted = await this.unpack(context, 'workspace-python-v1.zip', root, wheelId);
      hilog.info(0xD005, 'DSHClient', 'startup archive workspace-python-v1.zip extracted=%{public}s ms=%{public}d',
        String(extracted), Date.now() - phase);
      this.copyGuest(context, 'workspace-python.pth', root + '/usr/lib/python3.12/site-packages/mobile-harness-workspace.pth');
      this.copyGuest(context, 'dsh-harmony-workspace-deps.json', root + '/dsh-harmony-workspace-deps.json');
    }
  }

  private layerIdentity(context: common.UIAbilityContext, asset: string): string {
    let identity = '';
    for (const byte of context.resourceManager.getRawFileContentSync(asset)) identity += String.fromCharCode(byte);
    if (!/^[a-f0-9]{64}$/.test(identity)) throw new Error('Invalid packaged layer identity: ' + asset);
    return identity;
  }

  private prepareTimezone(root: string): void {
    try {
      const zone = i18n.getTimeZone().getID();
      if (!/^[A-Za-z0-9_+-]+(\/[A-Za-z0-9_+-]+)*$/.test(zone)) return;
      const source = root + '/usr/share/zoneinfo/' + zone;
      if (!fileIo.accessSync(source)) return;
      const target = root + '/etc/localtime';
      fileIo.copyFileSync(source, target + '.tmp');
      fileIo.renameSync(target + '.tmp', target);
    } catch (error) {
      hilog.warn(0xD005, 'DSHClient', 'could not copy device time zone %{public}s', String(error));
    }
  }

  private async prepareResolver(root: string): Promise<void> {
    try {
      const net = await connection.getDefaultNet();
      const info = await connection.getConnectionProperties(net);
      const dns = info.dnses.map(item => item.address)
        .filter(address => /^[0-9a-fA-F:.]+$/.test(address)).slice(0, 3);
      if (dns.length === 0) {
        hilog.warn(0xD005, 'DSHClient', 'system network has no DNS servers');
        return;
      }
      const file = fileIo.openSync(root + '/etc/resolv.conf',
        fileIo.OpenMode.WRITE_ONLY | fileIo.OpenMode.CREATE | fileIo.OpenMode.TRUNC);
      try {
        fileIo.writeSync(file.fd, dns.map(address => 'nameserver ' + address).join('\n') + '\n');
      } finally { fileIo.closeSync(file.fd); }
      hilog.info(0xD005, 'DSHClient', 'system DNS servers configured: %{public}d', dns.length);
    } catch (e) {
      hilog.warn(0xD005, 'DSHClient', 'failed to read system DNS configuration');
    }
  }

  private async unpack(context: common.UIAbilityContext, name: string, root: string, identity: string = ''): Promise<boolean> {
    const archive = context.filesDir + '/' + name;
    // One marker per archive stores the identity of the extracted layer. A
    // previous identity-suffixed marker accumulated forever, so switching back
    // to an older build skipped extraction and kept files from the newer layer.
    const marker = root + '/.validated-unpack-v2-' + name;
    if (fileIo.accessSync(marker)) {
      let previous = '';
      try { previous = fileIo.readTextSync(marker).trim(); } catch (error) { previous = ''; }
      if (previous === identity) return false;
    }
    const raw = context.resourceManager.getRawFdSync(name);
    const output = fileIo.openSync(archive,
      fileIo.OpenMode.WRITE_ONLY | fileIo.OpenMode.CREATE | fileIo.OpenMode.TRUNC);
    try {
      fileIo.lseek(raw.fd, raw.offset, fileIo.WhenceType.SEEK_SET);
      const buffer = new ArrayBuffer(1024 * 1024);
      let remaining = raw.length;
      while (remaining > 0) {
        const count = await fileIo.read(raw.fd, buffer, { length: Math.min(buffer.byteLength, remaining) });
        if (count <= 0) throw new Error('Unexpected end of raw resource ' + name);
        if (await fileIo.write(output.fd, buffer, { length: count }) !== count) {
          throw new Error('Incomplete write ' + name);
        }
        remaining -= count;
      }
    } finally {
      fileIo.closeSync(output.fd);
      context.resourceManager.closeRawFdSync(name);
    }
    try {
      await zlib.decompressFile(archive, root, {
        parallel: zlib.ParallelStrategy.PARALLEL_STRATEGY_PARALLEL_DECOMPRESSION,
      });
      const markerFile = fileIo.openSync(marker,
        fileIo.OpenMode.CREATE | fileIo.OpenMode.WRITE_ONLY | fileIo.OpenMode.TRUNC);
      try {
        if (identity) fileIo.writeSync(markerFile.fd, identity);
      } finally {
        fileIo.closeSync(markerFile);
      }
      hilog.info(0xD005, 'HarmonyPRoot', 'unpacked %{public}s', name);
      return true;
    } finally { fileIo.unlinkSync(archive); }
  }
  private removeRetiredDemoExtensionPlaceholder(root: string): void {
    const lib = root + '/usr/lib';
    // Older self builds could leave the PRoot bind target for the demo addon.
    const target = lib + '/mh-demo.node';
    try {
      const parent = fileIo.lstatSync(lib);
      if (!fileIo.lstatSync(root).isDirectory() || !fileIo.lstatSync(root + '/usr').isDirectory() ||
        !parent.isDirectory()) {
        hilog.warn(0xD005, 'DSHClient', 'could not verify the guest overlay directory');
        return;
      }
      const stat = fileIo.lstatSync(target);
      if (!stat.isFile() || stat.size !== 0 || (stat.mode & 0o7777) !== 0 || stat.uid !== parent.uid) {
        hilog.warn(0xD005, 'DSHClient', 'preserved an unrecognized demo extension file');
        return;
      }
      fileIo.unlinkSync(target);
      hilog.info(0xD005, 'DSHClient', 'removed retired demo extension placeholder');
    } catch (error) {
      if ((error as BusinessError).code !== 13900002) {
        hilog.warn(0xD005, 'DSHClient', 'could not remove the retired demo extension placeholder');
      }
    }
  }

  private prepareSelfBuildTools(context: common.UIAbilityContext, root: string, installForMode: boolean): void {
    try {
      let enabled = false;
      try {
        const raw = context.resourceManager.getRawFileContentSync('dsh-self-build.json');
        let text = '';
        for (const byte of raw) text += String.fromCharCode(byte);
        enabled = text.includes('"signedExecBypass": true');
      } catch (error) {
        enabled = false;
      }
      if (!enabled) {
        for (const stale of ['/usr/bin/mh-exec', '/usr/bin/mh-install']) {
          try {
            fileIo.unlinkSync(root + stale);
          } catch (error) {
            // Not present: nothing to clean up.
          }
        }
        this.removeRetiredDemoExtensionPlaceholder(root);
        hilog.info(0xD005, 'DSHClient', 'signed exec bypass disabled: store build');
        return;
      }
      if (!installForMode) return;
      const target = root + '/usr/bin/mh-exec';
      const bytes = context.resourceManager.getRawFileContentSync('mh-exec.py');
      // POSIX-style create with an executable mode: 0o755, O_WRONLY|O_CREAT|O_TRUNC.
      const fd = fileIO.openSync(target, 1 | 64 | 512, 0o755);
      try {
        fileIo.writeSync(fd, bytes.buffer);
      } finally {
        fileIo.closeSync(fd);
      }
      const installerTarget = root + '/usr/bin/mh-install';
      const installerBytes = context.resourceManager.getRawFileContentSync('mh-install.py');
      const installerFd = fileIO.openSync(installerTarget, 1 | 64 | 512, 0o755);
      try {
        fileIo.writeSync(installerFd, installerBytes.buffer);
      } finally {
        fileIo.closeSync(installerFd);
      }
      migrateSignedJq(context, root);
      hilog.info(0xD005, 'DSHClient', 'signed exec bypass enabled: /usr/bin/mh-exec /usr/bin/mh-install');
    } catch (error) {
      hilog.warn(0xD005, 'DSHClient', 'self-build tool setup failed: %{public}s', String(error));
    }
  }

  private copyGuest(context: common.UIAbilityContext, asset: string, path: string): void {
    const bytes = context.resourceManager.getRawFileContentSync(asset);
    try {
      if (fileIo.statSync(path).size === bytes.length) return;
    } catch (error) {
      // Missing target: write it below.
    }
    const file = fileIo.openSync(path, fileIo.OpenMode.WRITE_ONLY | fileIo.OpenMode.CREATE | fileIo.OpenMode.TRUNC);
    try { fileIo.writeSync(file.fd, bytes.buffer); }
    finally { fileIo.closeSync(file.fd); }
  }
}
export const dshEngine = new DshEngine();

import { common, childProcessManager } from '@kit.AbilityKit';
import { fileIo } from '@kit.CoreFileKit';
import zlib from '@ohos.zlib';
import { connection } from '@kit.NetworkKit';
import { hilog } from '@kit.PerformanceAnalysisKit';
import poc from 'libpoc.so';
import { BootRecovery } from './BootRecovery';

export interface BrowserSession {
  url: string;
  cookie?: string;
  safe?: boolean;
}
type EngineListener = (status: string, session?: BrowserSession) => void;

class DshEngine {
  private listeners: Set<EngineListener> = new Set<EngineListener>();
  private status: string = '正在准备本机 DSH…';
  private session?: BrowserSession;
  private running: boolean = false;
  private nativePoll: number = -1;

  attach(context: common.UIAbilityContext, listener: EngineListener): () => void {
    this.listeners.add(listener);
    listener(this.status, this.session);
    if (!this.running) {
      this.running = true;
      this.start(context);
    } else {
      hilog.info(0xD005, 'DSHClient', 'engine subscriber joined ready=%{public}s', String(this.session !== undefined));
    }
    return () => { this.listeners.delete(listener); };
  }

  private publish(status: string, session?: BrowserSession): void {
    this.status = status;
    this.session = session;
    this.listeners.forEach(listener => listener(status, session));
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
        this.publish('本机 DSH 页面初始化失败。');
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
    this.copyGuest(context, 'dsh-native-web.cjs', root + '/dsh-native-web.cjs');
    this.copyGuest(context, 'dsh-harmony-sharp.cjs', root + '/dsh-harmony-sharp.cjs');
    this.copyGuest(context, 'dsh-harmony-package.cjs', root + '/dsh-harmony-package.cjs');
    this.copyGuest(context, 'dsh-harmony-pnpm-fetch.cjs', root + '/dsh-harmony-pnpm-fetch.cjs');
    const recovery = new BootRecovery(context.filesDir);
    recovery.write(mode, true);
    this.publish(mode === 'safe' ? '正在启动安全模式…' : '正在启动本机 DeepSeek Harness…');
    hilog.info(0xD005, 'DSHClient', 'starting native Web ms=%{public}d', Date.now() - started);
    if (poc.usesHostProcess()) {
      hilog.info(0xD005, 'DSHClient', 'system child-process support native=%{public}s ark=%{public}s',
        String(childProcessManager.isNativeChildProcessSupported()), String(childProcessManager.isArkChildProcessSupported()));
    }
    poc.startNative(root, mode === 'safe');
    let ready = false;
    this.nativePoll = setInterval(() => {
      try {
        const status = poc.nativeStatus();
        if (status < 0 || (!ready && Date.now() - started > 60000)) {
          this.stopPolling();
          this.publish('本机 DSH 未运行。可在恢复选项中选择安全模式。');
          hilog.error(0xD005, 'DSHClient', 'native Host unavailable status=%{public}d', status);
        } else if (!ready && fileIo.accessSync(launchFile)) {
          const session = JSON.parse(fileIo.readTextSync(launchFile)) as BrowserSession;
          if (session.url !== 'http://127.0.0.1:19592/' || !session.cookie) {
            throw new Error('Invalid native browser session');
          }
          recovery.write(mode, false);
          ready = true;
          session.safe = mode === 'safe';
          this.publish('', session);
          hilog.info(0xD005, 'DSHClient', 'native loopback ready ms=%{public}d mode=%{public}s',
            Date.now() - started, mode);
        }
      } catch (e) {
        this.stopPolling();
        this.publish('本机 DSH 页面初始化失败。可从恢复选项重试。');
        hilog.error(0xD005, 'DSHClient', 'native launch descriptor invalid');
      }
    }, 200);
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
        this.publish('上次安全启动未完成。请选择恢复选项。');
        return;
      }
      const mode = state.pending ? 'safe' : state.mode;
      for (const name of ['bin', 'lib', 'etc', 'tmp', 'root']) {
        const path = root + '/' + name;
        if (!fileIo.accessSync(path)) fileIo.mkdirSync(path, true);
      }
      this.copyGuest(context, 'alpine-busybox', root + '/bin/busybox');
      this.copyGuest(context, 'alpine-busybox', root + '/bin/sh');
      this.copyGuest(context, 'alpine-ld-musl', root + '/lib/ld-musl-aarch64.so.1');
      this.copyGuest(context, 'alpine-release', root + '/etc/alpine-release');
      for (const archive of ['node-layer.zip', 'dsh-layer.zip', 'shell-tools-layer.zip', 'pnpm-layer-v2.zip']) {
        const phase = Date.now();
        const extracted = await this.unpack(context, archive, root);
        hilog.info(0xD005, 'DSHClient', 'startup archive %{public}s extracted=%{public}s ms=%{public}d',
          archive, String(extracted), Date.now() - phase);
      }
      const settingsClient = root + '/dsh/node_modules/@deepseek-ai/dsh-client-ui-settings-general/lib/client.js';
      this.copyGuest(context, 'dsh-settings-client.js', settingsClient + '.tmp');
      fileIo.renameSync(settingsClient + '.tmp', settingsClient);
      for (const name of ['fetch-shim.cjs', 'fetch-shim-boot.cjs', 'dsh-client.cjs', 'dsh-boot-cache.cjs',
        'dsh-client.patch.yml', 'dsh-seccomp-probe.cjs']) {
        this.copyGuest(context, name, root + '/' + name);
      }
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
      this.publish('本机 DSH 服务已退出。重新打开可重试。');
    } catch (e) {
      this.publish('本机 DSH 准备失败。重新打开可重试。');
      hilog.error(0xD005, 'DSHClient', 'setup error %{public}s', String(e));
    } finally {
      if (!nativeStarted) this.running = false;
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

  private async unpack(context: common.UIAbilityContext, name: string, root: string): Promise<boolean> {
    const archive = context.filesDir + '/' + name;
    const marker = root + '/.validated-unpack-v2-' + name;
    if (fileIo.accessSync(marker)) return false;
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
      await zlib.decompressFile(archive, root);
      fileIo.closeSync(fileIo.openSync(marker, fileIo.OpenMode.CREATE | fileIo.OpenMode.WRITE_ONLY).fd);
      hilog.info(0xD005, 'HarmonyPRoot', 'unpacked %{public}s', name);
      return true;
    } finally { fileIo.unlinkSync(archive); }
  }
  private copyGuest(context: common.UIAbilityContext, asset: string, path: string): void {
    const bytes = context.resourceManager.getRawFileContentSync(asset);
    const file = fileIo.openSync(path, fileIo.OpenMode.WRITE_ONLY | fileIo.OpenMode.CREATE | fileIo.OpenMode.TRUNC);
    try { fileIo.writeSync(file.fd, bytes.buffer); }
    finally { fileIo.closeSync(file.fd); }
  }
}
export const dshEngine = new DshEngine();

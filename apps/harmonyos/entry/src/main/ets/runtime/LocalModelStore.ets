import { common } from '@kit.AbilityKit';
import { util } from '@kit.ArkTS';
import { request } from '@kit.BasicServicesKit';
import { fileIo, hash, statfs } from '@kit.CoreFileKit';
import { hilog } from '@kit.PerformanceAnalysisKit';

const MODEL_DIR = '/local-models';
const DOWNLOAD_SUFFIX = '.download';

export interface LocalModelSpec {
  readonly id: string;
  readonly label: string;
  readonly bytes: number;
  readonly sha256: string;
  readonly revision: string;
  readonly url: string;
  readonly fileName: string;
  readonly contextWindow: number;
  readonly maxTokens: number;
}

export const LOCAL_MODELS: ReadonlyArray<LocalModelSpec> = [
  {
    id: 'lfm3-1.7b-q4',
    label: 'LFM3-1.7B Q4',
    bytes: 1099627808,
    sha256: '3793e1e6e2266919d6e015287221b41100175a98eddaba92e111aed3b05c93c4',
    revision: 'cd0c74c',
    url: 'https://huggingface.co/LiquidAI/LFM3-1.7B-GGUF/resolve/cd0c74c/LFM3-1.7B-Q4_K_M.gguf?download=true',
    fileName: 'LFM3-1.7B-Q4_K_M.gguf',
    contextWindow: 8192,
    maxTokens: 1024,
  },
  {
    id: 'qwen3.5-2b-q4',
    label: 'Qwen3.5-2B Q4',
    bytes: 1280835840,
    sha256: 'aaf42c8b7c3cab2bf3d69c355048d4a0ee9973d48f16c731c0520ee914699223',
    revision: 'f6d5376',
    url: 'https://huggingface.co/unsloth/Qwen3.5-2B-GGUF/resolve/f6d5376/Qwen3.5-2B-Q4_K_M.gguf?download=true',
    fileName: 'Qwen3.5-2B-Q4_K_M.gguf',
    contextWindow: 8192,
    maxTokens: 1024,
  },
];

export function findLocalModel(modelId: string): LocalModelSpec | undefined {
  return LOCAL_MODELS.find(model => model.id === modelId);
}

export type LocalModelDownloadPhase = 'starting' | 'downloading' | 'verifying' | 'ready' | 'cancelled' | 'error';

export interface LocalModelDownloadState {
  modelId: string;
  phase: LocalModelDownloadPhase;
  receivedBytes: number;
  totalBytes: number;
  message: string;
}

class ActiveDownload {
  cancelled: boolean = false;
  receivedBytes: number = 0;
  interrupt?: () => void;
  settled?: Promise<void>;
}

const activeDownloads = new Map<string, ActiveDownload>();
const invalidModelPaths = new Set<string>();

function checkCancelled(active: ActiveDownload): void {
  if (active.cancelled) throw new Error('已取消下载');
}

function hasSize(path: string, bytes: number): boolean {
  try {
    const stat = fileIo.lstatSync(path);
    return stat.isFile() && stat.size === bytes;
  } catch (_) {
    return false;
  }
}

function discardTemporary(path: string): void {
  try {
    if (fileIo.accessSync(path)) fileIo.unlinkSync(path);
  } catch (_) {
    hilog.warn(0xD005, 'DSHLocalModels', 'could not remove temporary model download');
  }
}

export class LocalModelStore {
  private readonly context: common.UIAbilityContext;
  private readonly directory: string;

  constructor(context: common.UIAbilityContext) {
    this.context = context;
    this.directory = context.filesDir + MODEL_DIR;
  }

  installedPath(modelId: string): string | undefined {
    const model = findLocalModel(modelId);
    if (!model) return undefined;
    const path = this.modelPath(model);
    return !invalidModelPaths.has(path) && hasSize(path, model.bytes) ? path : undefined;
  }

  async verifyForUse(modelId: string): Promise<string | undefined> {
    const path = this.installedPath(modelId);
    const model = findLocalModel(modelId);
    if (!path || !model) return undefined;
    if ((await hash.hash(path, 'sha256')).toLowerCase() === model.sha256 && hasSize(path, model.bytes)) return path;
    invalidModelPaths.add(path);
    return undefined;
  }

  async download(modelId: string, observe: (state: LocalModelDownloadState) => void): Promise<string> {
    const model = findLocalModel(modelId);
    if (!model) throw new Error('未知的本地模型');
    if (activeDownloads.has(this.directory)) throw new Error('已有模型正在下载');
    const active = new ActiveDownload();
    activeDownloads.set(this.directory, active);
    const notify = (phase: LocalModelDownloadPhase, message: string = ''): void => {
      observe({ modelId: model.id, phase, receivedBytes: active.receivedBytes, totalBytes: model.bytes, message });
    };
    const result = Promise.resolve().then(() => this.runDownload(model, active, notify)).then(path => {
      active.receivedBytes = model.bytes;
      notify('ready');
      return path;
    }, (error: Error) => {
      const message = active.cancelled ? '已取消下载' : error?.message || '下载模型失败';
      notify(active.cancelled ? 'cancelled' : 'error', message);
      throw new Error(message);
    });
    active.settled = result.then(() => {}, () => {});
    return result;
  }

  async cancel(): Promise<void> {
    const active = activeDownloads.get(this.directory);
    if (!active) return;
    active.cancelled = true;
    active.interrupt?.();
    await active.settled;
  }

  private modelPath(model: LocalModelSpec): string {
    return `${this.directory}/${model.id}-${model.sha256}.gguf`;
  }

  private async runDownload(model: LocalModelSpec, active: ActiveDownload,
    notify: (phase: LocalModelDownloadPhase, message?: string) => void): Promise<string> {
    const target = this.modelPath(model);
    const temporary = `${this.directory}/${model.id}-${util.generateRandomUUID()}${DOWNLOAD_SUFFIX}`;
    let task: request.agent.Task | undefined;
    try {
      notify('starting');
      const installed = await this.verifyForUse(model.id);
      checkCancelled(active);
      if (installed) return installed;
      if (!fileIo.accessSync(this.directory)) fileIo.mkdirSync(this.directory, true);
      for (const name of fileIo.listFileSync(this.directory)) {
        if (name.endsWith(DOWNLOAD_SUFFIX)) discardTemporary(this.directory + '/' + name);
      }
      if (fileIo.accessSync(target)) fileIo.unlinkSync(target);
      if (await statfs.getFreeSize(this.directory) < model.bytes) throw new Error('可用存储空间不足');
      checkCancelled(active);
      task = await request.agent.create(this.context, {
        action: request.agent.Action.DOWNLOAD,
        url: model.url,
        saveas: temporary,
        title: model.label,
        mode: request.agent.Mode.FOREGROUND,
        metered: true,
        roaming: false,
      });
      checkCancelled(active);
      notify('downloading');
      await this.transfer(task, active, model.bytes, notify);
      checkCancelled(active);
      if (!hasSize(temporary, model.bytes)) throw new Error('文件大小与模型目录不符');
      active.receivedBytes = model.bytes;
      notify('verifying');
      const digest = await hash.hash(temporary, 'sha256');
      checkCancelled(active);
      if (digest.toLowerCase() !== model.sha256) throw new Error('模型文件 SHA-256 校验失败');
      fileIo.renameSync(temporary, target);
      invalidModelPaths.delete(target);
      return target;
    } finally {
      active.interrupt = undefined;
      if (task) {
        try { await request.agent.remove(task.tid); }
        catch (_) { hilog.warn(0xD005, 'DSHLocalModels', 'could not remove model download task'); }
      }
      discardTemporary(temporary);
      activeDownloads.delete(this.directory);
    }
  }

  private transfer(task: request.agent.Task, active: ActiveDownload, bytes: number,
    notify: (phase: LocalModelDownloadPhase, message?: string) => void): Promise<void> {
    return new Promise<void>((resolve, reject) => {
      let finished = false;
      const finish = (error?: Error): void => {
        if (finished) return;
        finished = true;
        if (error) reject(error);
        else resolve();
      };
      active.interrupt = () => finish(new Error('已取消下载'));
      task.on('progress', progress => {
        if (finished || active.cancelled) return;
        active.receivedBytes = Math.min(bytes, progress.processed);
        if (progress.processed > bytes) finish(new Error('下载内容超过模型目录声明的大小'));
        else notify('downloading');
      });
      task.on('completed', () => finish());
      task.on('failed', () => {
        request.agent.show(task.tid).then(info => {
          finish(new Error(`系统下载失败（类别 ${info.faults}），可再次尝试`));
        }, () => finish(new Error('系统下载失败，可再次尝试')));
      });
      task.on('pause', () => finish(new Error('下载已暂停，可再次尝试')));
      task.on('remove', () => finish(new Error('下载任务已移除')));
      task.start().catch((error: Error) => finish(error));
    });
  }
}

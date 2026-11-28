import { common } from '@kit.AbilityKit';
import { util } from '@kit.ArkTS';
import { fileIo } from '@kit.CoreFileKit';
import { http } from '@kit.NetworkKit';
import poc from 'libpoc.so';
import { BrowserSession } from './DshEngine';
import { LOCAL_MODEL_PROVIDER, LocalModelRoute, LocalModelRouteModel, LocalModelSelection } from './LocalModelRoute';
import { findLocalModel, LocalModelSpec, LocalModelStore } from './LocalModelStore';

const SERVICE_URL = 'http://127.0.0.1:39765/v1/models';
const SETTINGS_FILE = '/local-inference.json';

interface InferencePreferences {
  modelId: string;
  preferLocal: boolean;
  previous?: LocalModelSelection;
}

interface ServedModel {
  id: string;
}

interface ServedModels {
  data: ServedModel[];
}

export interface LocalInferenceState {
  activeModel: string;
  preferLocal: boolean;
  busy: boolean;
  message: string;
}

export function hasLocalInference(): boolean {
  return poc.localInferenceAvailable();
}

function delay(milliseconds: number): Promise<void> {
  return new Promise<void>(resolve => { setTimeout(resolve, milliseconds); });
}

class LocalInference {
  private directory: string = '';
  private preferences: InferencePreferences = { modelId: '', preferLocal: false };
  private store?: LocalModelStore;
  private route?: LocalModelRoute;
  private activeModel: string = '';
  private busy: boolean = false;
  private message: string = '';

  snapshot(): LocalInferenceState {
    return { activeModel: this.activeModel, preferLocal: this.preferences.preferLocal, busy: this.busy,
      message: this.message };
  }

  async connect(context: common.UIAbilityContext, session: BrowserSession, available: boolean): Promise<void> {
    this.directory = context.filesDir;
    this.preferences = this.load();
    if (!available && !this.preferences.modelId) return;
    this.store = new LocalModelStore(context);
    this.route = new LocalModelRoute(session);
    if (!available) {
      if (await this.recoverRoute(this.route)) this.save({ modelId: '', preferLocal: false });
      return;
    }
    if (!this.preferences.modelId) return;
    try {
      await this.activate(this.preferences.modelId);
    } catch (_) {
      // activate reports the failure and restores the prior default when possible.
    }
  }

  async activate(modelId: string): Promise<void> {
    const route = this.requireRoute();
    const model = findLocalModel(modelId);
    if (!model || !this.store) throw new Error('未知的本地模型');
    this.busy = true;
    this.message = '';
    try {
      const modelPath = await this.store.verifyForUse(modelId);
      if (!modelPath) throw new Error('请先下载并校验模型');
      if (this.activeModel === modelId && poc.localInferenceState() === 1) return;
      await this.stopEngine();
      const key = util.generateRandomUUID(false).replace(/-/g, '') + util.generateRandomUUID(false).replace(/-/g, '');
      if (poc.localInferenceStart(modelPath, modelId, key) < 0) throw new Error('无法启动本地推理');
      await this.waitUntilReady(modelId, key);
      const routeModel = this.modelRoute(model);
      await route.register(routeModel, key);
      if (this.preferences.preferLocal) await this.setDefault(route, routeModel);
      else this.save({ modelId, preferLocal: false });
      this.activeModel = modelId;
    } catch (error) {
      // A failed verification leaves the active model running. After a failed switch, release the stale route.
      this.message = error instanceof Error ? error.message : '本地模型启动失败';
      if (!this.activeModel || poc.localInferenceState() !== 1) await this.recoverRoute(route);
      throw new Error(this.message);
    } finally {
      this.busy = false;
    }
  }

  async preferLocal(prefer: boolean): Promise<void> {
    const route = this.requireRoute();
    this.busy = true;
    this.message = '';
    try {
      if (prefer) {
        const model = findLocalModel(this.activeModel);
        if (!model || poc.localInferenceState() !== 1) throw new Error('请先启用一个本地模型');
        await this.setDefault(route, this.modelRoute(model));
      } else {
        await route.restore(this.preferences.previous);
        this.save({ modelId: this.preferences.modelId, preferLocal: false });
      }
    } catch (error) {
      this.message = error instanceof Error ? error.message : '无法更新默认模型';
      throw new Error(this.message);
    } finally {
      this.busy = false;
    }
  }

  async stop(): Promise<void> {
    const route = this.requireRoute();
    this.busy = true;
    this.message = '';
    try {
      await route.restore(this.preferences.previous);
      await route.unregister();
      await this.stopEngine();
      this.save({ modelId: '', preferLocal: false });
    } catch (error) {
      this.message = error instanceof Error ? error.message : '停止本地推理失败';
      throw new Error(this.message);
    } finally {
      this.busy = false;
    }
  }

  private requireRoute(): LocalModelRoute {
    if (!this.route || this.busy) throw new Error('本地推理设置暂不可用');
    return this.route;
  }

  private modelRoute(model: LocalModelSpec): LocalModelRouteModel {
    return { id: model.id, name: model.label, contextWindow: model.contextWindow, maxTokens: model.maxTokens };
  }

  private async setDefault(route: LocalModelRoute, model: LocalModelRouteModel): Promise<void> {
    const before = this.preferences;
    const current = await route.readDefault();
    const previous = current?.provider === LOCAL_MODEL_PROVIDER ? before.previous : current;
    this.save({ modelId: model.id, preferLocal: true, previous });
    let replaced: LocalModelSelection | undefined;
    try {
      replaced = await route.prefer(model);
    } catch (error) {
      this.save(before);
      throw new Error(error instanceof Error ? error.message : '无法设置本地默认模型');
    }
    if (replaced && (replaced.provider !== previous?.provider || replaced.model !== previous?.model ||
        replaced.reasoningEffort !== previous?.reasoningEffort)) {
      this.save({ modelId: model.id, preferLocal: true, previous: replaced });
    }
  }

  private async recoverRoute(route: LocalModelRoute): Promise<boolean> {
    try {
      await route.restore(this.preferences.previous);
      await route.unregister();
      return true;
    } catch (_) {
      this.message = '本地模型不可用，请在 DSH 设置中检查默认模型';
      return false;
    } finally {
      await this.stopEngine().catch(() => {});
    }
  }

  private async stopEngine(): Promise<void> {
    if (poc.localInferenceState() > 0) {
      if (poc.localInferenceStop() < 0) throw new Error('无法停止本地推理');
      const deadline = Date.now() + 12000;
      while (poc.localInferenceState() > 0 && Date.now() < deadline) await delay(250);
      if (poc.localInferenceState() > 0) throw new Error('本地推理尚未停止，请稍后重试');
    }
    this.activeModel = '';
  }

  private async waitUntilReady(modelId: string, key: string): Promise<void> {
    const deadline = Date.now() + 45000;
    while (poc.localInferenceState() > 0 && Date.now() < deadline) {
      if (poc.localInferenceState() !== 1) {
        await delay(350);
        continue;
      }
      const request = http.createHttp();
      try {
        const response = await request.request(SERVICE_URL, {
          method: http.RequestMethod.GET, usingProxy: false, usingCache: false,
          connectTimeout: 750, readTimeout: 1000, expectDataType: http.HttpDataType.STRING,
          header: { Authorization: 'Bearer ' + key }
        });
        if (response.responseCode === 200 && typeof response.result === 'string') {
          const models = JSON.parse(response.result) as ServedModels;
          if (models.data.some(model => model.id === modelId)) return;
        }
      } catch (_) {
        // The engine binds its port asynchronously while loading weights.
      } finally {
        request.destroy();
      }
      await delay(350);
    }
    throw new Error('本地模型未能就绪，请检查设备可用内存后重试');
  }

  private load(): InferencePreferences {
    try {
      const path = this.directory + SETTINGS_FILE;
      if (fileIo.accessSync(path)) {
        const saved = JSON.parse(fileIo.readTextSync(path)) as InferencePreferences;
        if (findLocalModel(saved.modelId)) {
          return { modelId: saved.modelId, preferLocal: saved.preferLocal === true, previous: saved.previous };
        }
      }
    } catch (_) {
      this.message = '无法读取已保存的本地推理设置';
    }
    return { modelId: '', preferLocal: false };
  }

  private save(preferences: InferencePreferences): void {
    const path = this.directory + SETTINGS_FILE;
    const file = fileIo.openSync(path + '.tmp', fileIo.OpenMode.CREATE | fileIo.OpenMode.WRITE_ONLY | fileIo.OpenMode.TRUNC);
    try { fileIo.writeSync(file.fd, JSON.stringify(preferences)); } finally { fileIo.closeSync(file.fd); }
    fileIo.renameSync(path + '.tmp', path);
    this.preferences = preferences;
  }
}

export const localInference = new LocalInference();

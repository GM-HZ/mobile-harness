import { http } from '@kit.NetworkKit';
import { BrowserSession } from './DshEngine';

export const LOCAL_MODEL_PROVIDER: string = 'mobile-harness-local';
const DSH_ORIGIN: string = 'http://127.0.0.1:19592/';
const INFERENCE_URL: string = 'http://127.0.0.1:39765/v1';
const KEY_REF: string = 'MOBILE_HARNESS_LOCAL_INFERENCE_KEY';
const PROVIDERS: string = 'llm-pi-ai';
const DEFAULT: string = 'agent-default-model';
const LOCAL_STREAM_IDLE_TIMEOUT_MS: number = 480000;

export interface LocalModelRouteModel {
  id: string;
  name: string;
  contextWindow: number;
  maxTokens: number;
}

export interface LocalModelSelection {
  provider: string;
  model: string;
  reasoningEffort?: string;
}

interface SettingsNamespace {
  ns: string;
  revision: number;
  value: Object;
  base?: Object;
}

interface SettingsDescription {
  writable: boolean;
  namespaces: SettingsNamespace[];
}

interface ProviderEntry {
  api?: string;
  apiKeyEnv?: string;
  baseURL?: string;
  models?: LocalModelRouteModel[];
}

interface ProviderSettings {
  providers?: Record<string, ProviderEntry>;
}

interface SettingOperation {
  op: string;
  path: string[];
  value?: Object;
}

interface SettingsPatch {
  ns: string;
  ops: SettingOperation[];
  expectedRevision: number;
}

interface DefaultPatch {
  ns: string;
  section: LocalModelSelection;
  expectedRevision: number;
}

interface CredentialPatch {
  ref: string;
  value?: string;
}

interface LocalCompatibility {
  supportsDeveloperRole: boolean;
  supportsReasoningEffort: boolean;
  supportsStore: boolean;
  supportsStrictMode: boolean;
  maxTokensField: string;
}

interface LocalModelProfile extends LocalModelRouteModel {
  input: string[];
  reasoningEfforts: boolean;
}

interface LocalProviderProfile extends ProviderEntry {
  displayName: string;
  cacheRetention: string;
  streamIdleTimeoutMs: number;
  compat: LocalCompatibility;
  models: LocalModelProfile[];
  retryPolicy: LocalRetryPolicy;
}

interface LocalRetryPolicy {
  mode: string;
  maxRetries: number;
}

interface RpcPayload {
  args: Object;
}

class EmptyArgs {}

interface RpcRequest {
  type: string;
  rpcId: string;
  method: string;
  payload: RpcPayload;
}

interface RpcFailure {
  code: string;
}

interface RpcResult<T> {
  ok: boolean;
  value?: T;
  error?: RpcFailure;
}

interface RpcResponse<T> {
  type: string;
  rpcId: string;
  result: RpcResult<T>;
}

class RouteError extends Error {
  readonly code: string;

  constructor(code: string, message: string) {
    super(message);
    this.code = code;
  }
}

class StopLocalRedirect implements http.HttpInterceptor {
  interceptorType: http.InterceptorType = http.InterceptorType.REDIRECTION;

  interceptorHandle(_request: http.HttpRequestContext, _response: http.HttpResponse): Promise<http.ChainContinue> {
    return Promise.resolve(false);
  }
}

function routeError(error: Object): Error {
  return error instanceof RouteError ? new RouteError(error.code, error.message) :
    new Error(error instanceof Error ? error.message : '本机 DSH 模型设置更新失败。');
}

function selectionFrom(value: Object | undefined): LocalModelSelection | undefined {
  if (!value) return undefined;
  const selection = value as LocalModelSelection;
  if (typeof selection.provider !== 'string' || selection.provider.length === 0 ||
      typeof selection.model !== 'string' || selection.model.length === 0) return undefined;
  return {
    provider: selection.provider,
    model: selection.model,
    reasoningEffort: typeof selection.reasoningEffort === 'string' ? selection.reasoningEffort : undefined
  };
}

function ownedProvider(section: SettingsNamespace): ProviderEntry | undefined {
  const configuration = section.value as ProviderSettings;
  const provider = configuration.providers?.[LOCAL_MODEL_PROVIDER];
  if (provider !== undefined && (provider.api !== 'openai-completions' ||
      provider.apiKeyEnv !== KEY_REF || provider.baseURL !== INFERENCE_URL)) {
    throw new Error('本地推理的模型提供方名称已被其他配置使用。');
  }
  return provider;
}

function profileFor(model: LocalModelRouteModel): LocalProviderProfile {
  const entry: LocalModelProfile = {
    id: model.id,
    name: model.name,
    contextWindow: model.contextWindow,
    maxTokens: model.maxTokens,
    input: ['text'],
    reasoningEfforts: false
  };
  return {
    api: 'openai-completions',
    apiKeyEnv: KEY_REF,
    baseURL: INFERENCE_URL,
    displayName: 'Mobile Harness 本地推理',
    cacheRetention: 'none',
    streamIdleTimeoutMs: LOCAL_STREAM_IDLE_TIMEOUT_MS,
    compat: {
      supportsDeveloperRole: false,
      supportsReasoningEffort: false,
      supportsStore: false,
      supportsStrictMode: false,
      maxTokensField: 'max_tokens'
    },
    models: [entry],
    retryPolicy: { mode: 'normal', maxRetries: 0 }
  };
}

/** Uses the existing authenticated DSH Settings API without editing profile files. */
export class LocalModelRoute {
  private readonly cookie: string;
  private serial: number = 0;

  constructor(session: BrowserSession) {
    const cookie = session.cookie?.split(';', 1)[0].trim() ?? '';
    if (session.url !== DSH_ORIGIN || session.safe === true ||
        !/^dsh-auth-[A-Za-z0-9_-]+=v1\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/.test(cookie)) {
      throw new Error('本机 DSH 设置尚未就绪。');
    }
    this.cookie = cookie;
  }

  async register(model: LocalModelRouteModel, apiKey: string): Promise<void> {
    if (!/^[A-Za-z0-9_.-]{1,128}$/.test(model.id) || model.name.length === 0 ||
        !Number.isSafeInteger(model.contextWindow) || !Number.isSafeInteger(model.maxTokens) ||
        model.maxTokens <= 0 || model.maxTokens >= model.contextWindow ||
        !/^[A-Za-z0-9_-]{32,256}$/.test(apiKey)) {
      throw new Error('本地推理模型的连接配置无效。');
    }
    const provider = ownedProvider(await this.settings(PROVIDERS));
    const credential: CredentialPatch = { ref: KEY_REF, value: apiKey };
    await this.rpc<Object>('credentials/set', credential);
    try {
      await this.retryAfterConflict(async (): Promise<void> => {
        const section = await this.settings(PROVIDERS);
        ownedProvider(section);
        const ops: SettingOperation[] = [{ op: 'set', path: ['providers', LOCAL_MODEL_PROVIDER], value: profileFor(model) }];
        const patch: SettingsPatch = { ns: PROVIDERS, ops, expectedRevision: section.revision };
        await this.rpc<Object>('settings/mutate', patch);
      });
    } catch (error) {
      // If the new provider never became visible, discard its credential too.
      if (!provider) {
        try {
          if (!ownedProvider(await this.settings(PROVIDERS))) await this.removeCredential();
        } catch (_) {
          throw new Error('本地模型注册失败，DSH 凭据将在下次启动时重新同步。');
        }
      }
      throw routeError(error as Object);
    }
  }

  async readDefault(): Promise<LocalModelSelection | undefined> {
    return selectionFrom((await this.settings(DEFAULT)).value);
  }

  async prefer(model: LocalModelRouteModel): Promise<LocalModelSelection | undefined> {
    return this.retryAfterConflict(async (): Promise<LocalModelSelection | undefined> => {
      const provider = ownedProvider(await this.settings(PROVIDERS));
      if (!provider?.models?.some((entry: LocalModelRouteModel) => entry.id === model.id)) {
        throw new Error('请先启动所选本地模型。');
      }
      const section = await this.settings(DEFAULT);
      const previous = selectionFrom(section.value);
      if (previous?.provider !== LOCAL_MODEL_PROVIDER || previous.model !== model.id || previous.reasoningEffort) {
        await this.replaceDefault(section, { provider: LOCAL_MODEL_PROVIDER, model: model.id });
      }
      return previous?.provider === LOCAL_MODEL_PROVIDER ? undefined : previous;
    });
  }

  async restore(previous: LocalModelSelection | undefined): Promise<void> {
    await this.retryAfterConflict(async (): Promise<void> => {
      const section = await this.settings(DEFAULT);
      if (selectionFrom(section.value)?.provider !== LOCAL_MODEL_PROVIDER) return;
      ownedProvider(await this.settings(PROVIDERS));
      const selection = selectionFrom(previous) ?? selectionFrom(section.base);
      if (!selection || selection.provider === LOCAL_MODEL_PROVIDER) {
        throw new Error('找不到可恢复的 DSH 默认模型。');
      }
      await this.replaceDefault(section, selection);
    });
  }

  async unregister(): Promise<void> {
    await this.retryAfterConflict(async (): Promise<void> => {
      if ((await this.readDefault())?.provider === LOCAL_MODEL_PROVIDER) {
        throw new Error('请先恢复非本地默认模型。');
      }
      const section = await this.settings(PROVIDERS);
      if (ownedProvider(section)) {
        const ops: SettingOperation[] = [{ op: 'unset', path: ['providers', LOCAL_MODEL_PROVIDER] }];
        const patch: SettingsPatch = { ns: PROVIDERS, ops, expectedRevision: section.revision };
        await this.rpc<Object>('settings/mutate', patch);
      }
      await this.removeCredential();
    });
  }

  private async removeCredential(): Promise<void> {
    const patch: CredentialPatch = { ref: KEY_REF };
    await this.rpc<Object>('credentials/unset', patch);
  }

  private async settings(ns: string): Promise<SettingsNamespace> {
    const result = await this.rpc<SettingsDescription>('settings/describe', new EmptyArgs());
    const section = result?.namespaces?.find((entry: SettingsNamespace) => entry.ns === ns);
    if (!result?.writable || !section || !Number.isSafeInteger(section.revision)) {
      throw new Error('本机 DSH 模型设置当前不可写。');
    }
    return section;
  }

  private async replaceDefault(current: SettingsNamespace, selection: LocalModelSelection): Promise<void> {
    const patch: DefaultPatch = { ns: DEFAULT, section: selection, expectedRevision: current.revision };
    await this.rpc<Object>('settings/replace', patch);
  }

  private async retryAfterConflict<T>(action: () => Promise<T>): Promise<T> {
    for (let attempt = 0; attempt < 3; attempt++) {
      try {
        return await action();
      } catch (error) {
        if (!(error instanceof RouteError) || error.code !== 'settings/conflict' || attempt === 2) {
          throw routeError(error as Object);
        }
      }
    }
    throw new Error('本机 DSH 设置正在修改，请重试。');
  }

  private async rpc<T>(method: string, args: Object): Promise<T | undefined> {
    const request = http.createHttp();
    const rpcId = 'mh-local-' + Date.now() + '-' + (++this.serial);
    const body: RpcRequest = { type: 'client-request', rpcId, method, payload: { args } };
    try {
      const redirects = new http.HttpInterceptorChain();
      if (!redirects.addChain([new StopLocalRedirect()]) || !redirects.apply(request)) {
        throw new Error('本机设置的跳转保护无法启用。');
      }
      const response = await request.request(DSH_ORIGIN + 'api/' + method, {
        method: http.RequestMethod.POST,
        header: { 'Content-Type': 'application/json', 'Cookie': this.cookie },
        extraData: JSON.stringify(body),
        usingProxy: false,
        usingCache: false,
        connectTimeout: 4000,
        readTimeout: 8000,
        expectDataType: http.HttpDataType.STRING
      });
      if (response.responseCode !== 200 || typeof response.result !== 'string') {
        throw new Error('本机 DSH 设置请求失败。');
      }
      const envelope = JSON.parse(response.result) as RpcResponse<T>;
      if (envelope?.type !== 'server-response' || envelope.rpcId !== rpcId || !envelope.result) {
        throw new Error('本机 DSH 设置响应无效。');
      }
      if (envelope.result.ok !== true) {
        const errorCode = envelope.result.error?.code ?? '';
        const code = /^[a-z0-9/_-]{1,64}$/.test(errorCode) ? errorCode : 'invalid-result';
        throw new RouteError(code, code === 'settings/conflict' ? '本机 DSH 设置已被其他操作更新。' :
          '本机 DSH 拒绝更新模型设置（' + code + '）。');
      }
      return envelope.result.value;
    } finally {
      request.destroy();
    }
  }
}

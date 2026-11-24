import { common } from '@kit.AbilityKit';
import { url, util } from '@kit.ArkTS';
import { fileIo } from '@kit.CoreFileKit';
import { http } from '@kit.NetworkKit';

const HOSTS_FILE = '/remote-host-https.json';

interface SelfBuild {
  selfBuild: boolean;
}

export interface RemoteHost {
  name: string;
  origin: string;
}

export function isRemoteHostsEnabled(context: common.UIAbilityContext): boolean {
  try {
    const resources = context.resourceManager;
    if (resources.getRawFileListSync('').includes('appgallery.patch.yml')) return false;
    const marker = resources.getRawFileContentSync('dsh-self-build.json');
    return (JSON.parse(util.TextDecoder.create('utf-8').decodeToString(marker)) as SelfBuild).selfBuild === true;
  } catch (_) {
    return false;
  }
}

export function remoteHostOrigin(address: string): string {
  const parsed = url.URL.parseURL(address.trim());
  if (parsed.protocol !== 'https:' || parsed.username || parsed.password ||
      parsed.pathname !== '/' || parsed.search || parsed.hash) {
    throw new Error('Expected a bare HTTPS origin');
  }
  return parsed.origin;
}

export function allowedRemoteRequest(origin: string, target: string): boolean {
  try {
    const parsed = url.URL.parseURL(target);
    return parsed.protocol === 'https:' && parsed.origin === origin && !parsed.username && !parsed.password;
  } catch (_) {
    return false;
  }
}

export class RemoteHostStore {
  static list(context: common.UIAbilityContext): RemoteHost[] {
    try {
      const stored = JSON.parse(fileIo.readTextSync(context.filesDir + HOSTS_FILE)) as RemoteHost[];
      if (!Array.isArray(stored)) return [];
      const hosts: RemoteHost[] = [];
      for (const entry of stored) {
        if (!entry || typeof entry.name !== 'string' || typeof entry.origin !== 'string') continue;
        try {
          hosts.push({ name: entry.name, origin: remoteHostOrigin(entry.origin) });
        } catch (_) {
          continue;
        }
      }
      return hosts;
    } catch (_) {
      return [];
    }
  }

  private static write(context: common.UIAbilityContext, hosts: RemoteHost[]): void {
    const path = context.filesDir + HOSTS_FILE;
    const data = new util.TextEncoder().encodeInto(JSON.stringify(hosts) + '\n');
    const file = fileIo.openSync(path + '.new',
      fileIo.OpenMode.WRITE_ONLY | fileIo.OpenMode.CREATE | fileIo.OpenMode.TRUNC);
    try {
      if (fileIo.writeSync(file.fd, data.buffer) !== data.byteLength) {
        throw new Error('Incomplete remote host settings write');
      }
      fileIo.fsyncSync(file.fd);
    } finally {
      fileIo.closeSync(file.fd);
    }
    fileIo.renameSync(path + '.new', path);
  }

  static remember(context: common.UIAbilityContext, host: RemoteHost): void {
    const origin = remoteHostOrigin(host.origin);
    const hosts = RemoteHostStore.list(context).filter(entry => entry.origin !== origin);
    hosts.unshift({ name: host.name.trim().slice(0, 80) || origin, origin });
    RemoteHostStore.write(context, hosts);
  }

  static remove(context: common.UIAbilityContext, origin: string): void {
    RemoteHostStore.write(context, RemoteHostStore.list(context).filter(entry => entry.origin !== origin));
  }
}

class StopRedirect implements http.HttpInterceptor {
  interceptorType: http.InterceptorType = http.InterceptorType.REDIRECTION;

  interceptorHandle(_request: http.HttpRequestContext, _response: http.HttpResponse): Promise<http.ChainContinue> {
    return Promise.resolve(false);
  }
}

export async function exchangeRemoteToken(address: string, token: string): Promise<string> {
  const origin = remoteHostOrigin(address);
  if (!/^[A-Za-z0-9_-]{1,512}$/.test(token)) throw new Error('Invalid DSH launch token');
  const request = http.createHttp();
  try {
    const interceptors = new http.HttpInterceptorChain();
    if (!interceptors.addChain([new StopRedirect()]) || !interceptors.apply(request)) {
      throw new Error('Remote request interceptor unavailable');
    }
    const response = await request.request(origin + '/?token=' + encodeURIComponent(token), {
      method: http.RequestMethod.GET,
      usingCache: false,
      connectTimeout: 8000,
      readTimeout: 8000,
      header: { 'Cache-Control': 'no-store' }
    });
    const headers = response.header as Record<string, string | string[]>;
    const location = headers['location'];
    if (response.responseCode !== 303 || typeof location !== 'string' ||
        url.URL.parseURL(location, origin + '/').href !== origin + '/') {
      throw new Error('Expected the DSH same-origin login redirect');
    }
    const rawCookie = headers['set-cookie'];
    const cookies = typeof rawCookie === 'string' ? [rawCookie] : rawCookie ?? [];
    for (const value of cookies) {
      const pair = value.split(';')[0].trim();
      if (/^dsh-auth-[A-Za-z0-9_-]+=v1\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/.test(pair)) {
        return pair;
      }
    }
    throw new Error('Missing DSH browser session cookie');
  } finally {
    request.destroy();
  }
}

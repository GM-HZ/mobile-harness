import { common } from '@kit.AbilityKit';
import { fileIo } from '@kit.CoreFileKit';

export interface RemoteHost {
  id: string;
  name: string;
  kind: string;
  url: string;
  token: string;
  sshHost?: string;
  sshPort?: string;
  sshUser?: string;
  sshPassword?: string;
  sshKey?: string;
  sshPassphrase?: string;
  fingerprint?: string;
}

interface RemoteHostFile {
  selected: string;
  hosts: RemoteHost[];
}

const FILE = '/remote-hosts.json';

export class RemoteHostStore {
  private static path(context: common.UIAbilityContext): string {
    return context.filesDir + FILE;
  }

  private static read(context: common.UIAbilityContext): RemoteHostFile {
    try {
      const text = fileIo.readTextSync(RemoteHostStore.path(context));
      const parsed = JSON.parse(text) as RemoteHostFile;
      if (Array.isArray(parsed.hosts)) {
        return {
          selected: typeof parsed.selected === 'string' ? parsed.selected : '',
          hosts: parsed.hosts.filter(host => typeof host?.url === 'string' && typeof host?.id === 'string'),
        };
      }
    } catch (error) {
      // Missing or invalid file means no remote hosts configured.
    }
    return { selected: '', hosts: [] };
  }

  private static write(context: common.UIAbilityContext, data: RemoteHostFile): void {
    const file = fileIo.openSync(RemoteHostStore.path(context),
      fileIo.OpenMode.WRITE_ONLY | fileIo.OpenMode.CREATE | fileIo.OpenMode.TRUNC);
    try {
      fileIo.writeSync(file.fd, JSON.stringify(data) + '\n');
    } finally {
      fileIo.closeSync(file);
    }
  }

  static list(context: common.UIAbilityContext): RemoteHost[] {
    return RemoteHostStore.read(context).hosts;
  }

  static selected(context: common.UIAbilityContext): RemoteHost | undefined {
    const data = RemoteHostStore.read(context);
    return data.hosts.find(host => host.id === data.selected);
  }

  static select(context: common.UIAbilityContext, id: string): void {
    const data = RemoteHostStore.read(context);
    RemoteHostStore.write(context, { selected: id, hosts: data.hosts });
  }

  static add(context: common.UIAbilityContext, host: RemoteHost): void {
    const data = RemoteHostStore.read(context);
    data.hosts = data.hosts.filter(item => item.id !== host.id);
    data.hosts.push(host);
    RemoteHostStore.write(context, data);
  }

  static remove(context: common.UIAbilityContext, id: string): void {
    const data = RemoteHostStore.read(context);
    data.hosts = data.hosts.filter(host => host.id !== id);
    if (data.selected === id) data.selected = '';
    RemoteHostStore.write(context, data);
  }
}

import { fileIo } from '@kit.CoreFileKit';

export interface BootState {
  mode: string;
  pending: boolean;
}

export class BootRecovery {
  private readonly path: string;

  constructor(filesDir: string) {
    this.path = filesDir + '/mobile-harness-boot.json';
  }

  read(): BootState {
    if (!fileIo.accessSync(this.path)) return { mode: 'normal', pending: false };
    try {
      const state = JSON.parse(fileIo.readTextSync(this.path)) as BootState;
      if ((state.mode === 'normal' || state.mode === 'safe') && typeof state.pending === 'boolean') {
        return state;
      }
    } catch (_) {
      // An unreadable marker is treated as an interrupted boot.
    }
    return { mode: 'normal', pending: true };
  }

  write(mode: string, pending: boolean): void {
    const temp = this.path + '.new';
    const file = fileIo.openSync(temp,
      fileIo.OpenMode.WRITE_ONLY | fileIo.OpenMode.CREATE | fileIo.OpenMode.TRUNC);
    try {
      const contents = JSON.stringify({ mode: mode, pending: pending });
      if (fileIo.writeSync(file.fd, contents) !== contents.length) {
        throw new Error('Incomplete boot state write');
      }
      fileIo.fsyncSync(file.fd);
    } finally {
      fileIo.closeSync(file.fd);
    }
    fileIo.renameSync(temp, this.path);
  }
}

// Keep upstream file policy, version guards, staging, sync and commit handling.
// HarmonyOS disallows hard links; use the shipped atomic no-replace rename
// only at LocalFileSystem's public publication boundary.
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
const root = path.dirname(fileURLToPath(import.meta.url));
const entry = path.join(root, '.dsh-0.2.2-rc.4/dsh/node_modules/@deepseek-ai/dsh-fs-sandbox/lib/index.js');
const { SandboxedFileSystem } = await import(pathToFileURL(entry).href);

export default class HarmonyFileSystem extends SandboxedFileSystem {
  constructor(ctx, config) {
    super(ctx, config);
    const publish = globalThis.__harmonyPublishNoReplace;
    if (typeof publish !== 'function') throw new Error('Harmony atomic no-replace publication is unavailable');
    this.internals = { ...this.internals, linkFile: async (source, target) => { publish(source, target); } };
  }
}

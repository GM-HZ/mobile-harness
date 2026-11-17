// Provider replacement through the public subprocess service. Upstream owns
// output collection/spill, cancellation, process-group tracking and disposal.
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
const root = path.dirname(fileURLToPath(import.meta.url));
const packages = path.join(root, '.dsh-0.2.2-rc.4/dsh/node_modules/@deepseek-ai');
const { LocalSubprocessRuntime } = await import(pathToFileURL(path.join(packages, 'dsh-subprocess-local/lib/index.js')).href);
const { SubprocessExecutableNotFoundError, SubprocessError } = await import(pathToFileURL(path.join(packages, 'dsh-subprocess/lib/index.js')).href);

export default class HarmonySubprocessRuntime extends LocalSubprocessRuntime {
  constructor(ctx) {
    super(ctx);
    // Public, version-pinned Local provider injection hook, not a core edit.
    this.internals = { spawn: globalThis.__harmonyHostSpawn };
  }

  spawn(spec) {
    return super.spawn({ ...spec, env: {
      PATH: ['home/dsh/.local/bin', 'opt/tools/bin', 'usr/local/bin', 'usr/bin', 'bin'].map(p => path.join(root, p)).join(':'),
      HOME: path.join(root, 'home/dsh'), TMPDIR: path.join(root, 'tmp'),
      NODE_OPTIONS: '--jitless --require=/fetch-shim-boot.cjs',
      ...spec.env,
    } });
  }

  async resolveExecutable(command, env, signal) {
    signal?.throwIfAborted();
    if (typeof command !== 'string' || !command || command.includes('\0')) throw new TypeError('Expected a non-empty executable');
    if (!path.isAbsolute(command) && command.includes('/')) throw new Error('Use an absolute executable path or a bare PATH name');
    // Resolve inside the actual execution world, including signed executable
    // overlays which are intentionally zero-byte/non-executable in the Host fs.
    const child = this.spawn({
      argv: [path.join(root, 'bin/bash'), '-c',
        'p=$(command -v -- "$1") && test -f "$p" && test -x "$p" && printf "%s" "$p"', 'mh-resolve', command],
      cwd: path.join(root, 'workspace-native'), env, signal, graceMs: 1000,
      stdio: { stdin: 'ignore', stdout: { maxBytes: 4096 }, stderr: { maxBytes: 4096 } },
    });
    try {
      const result = await child.done;
      signal?.throwIfAborted();
      const resolved = child.stdout.readFrom(0).text;
      if (result.exitCode !== 0 || !path.isAbsolute(resolved) || resolved.includes('\n')) {
        throw new SubprocessExecutableNotFoundError('Harmony subprocess: command ' + JSON.stringify(command) + ' was not found as an executable');
      }
      return resolved;
    } finally {
      child.terminate();
      await child.waitForExit();
    }
  }

  async spawnTerminal() {
    throw new SubprocessError('HarmonyOS system PTY is unavailable; use non-interactive Bash', 'SUBPROCESS_PTY_UNAVAILABLE');
  }
}

'use strict';
const fs = require('node:fs');
const path = require('node:path');
const { finished, pipeline } = require('node:stream/promises');

const quote = value => "'" + value.replaceAll("'", "'\\''") + "'";

function createPackageRunner(root, home, launch) {
  function inside(directory, target) {
    const rel = path.relative(directory, target);
    if (rel === '..' || rel.startsWith('../') || path.isAbsolute(rel)) {
      throw new Error('DSH package operation requires an application-private path');
    }
    return rel;
  }
  function guestPath(target) {
    return '/' + inside(root, target);
  }
  return (command, args, options = {}) => {
    if (!['pnpm', 'git'].includes(command) || options.stdin !== 'ignore' ||
        options.stdout === 'inherit' || options.stderr === 'inherit') {
      throw new Error('Unsupported Harmony profile package operation');
    }
    const cwd = fs.realpathSync(options.cwd);
    inside(home, cwd);
    options.cancelSignal?.throwIfAborted();
    const profileHome = guestPath(home);
    const prefix = command === 'pnpm' ? [
      '/bin/node', '/pnpm-harmony/bin/pnpm.mjs',
    ] : ['/usr/bin/git'];
    const remapped = args.map(arg => {
      const match = /^(file:|link:)?(\/.*)$/.exec(arg);
      if (!match) return arg;
      return (match[1] || '') + guestPath(fs.realpathSync(match[2]));
    });
    if (command === 'pnpm') {
      remapped.push('--config.node-linker=hoisted', '--config.package-import-method=copy',
        '--store-dir=' + profileHome + '/package-store', '--ignore-scripts');
    }
    const child = launch(guestPath(cwd),
      'export HOME=' + quote(profileHome) + ' GIT_TERMINAL_PROMPT=0; exec ' +
      [...prefix, ...remapped].map(quote).join(' '));
    let timedOut = false;
    let killTimer;
    const kill = () => {
      if (child.exitCode !== null || child.signalCode !== null) return;
      try { child.kill('SIGTERM'); } catch {}
      if (!killTimer) killTimer = setTimeout(() => {
        if (child.exitCode === null && child.signalCode === null) {
          try { child.kill('SIGKILL'); } catch {}
        }
      }, 1000);
    };
    options.cancelSignal?.addEventListener('abort', kill, { once: true });
    const timeout = options.timeout ? setTimeout(() => { timedOut = true; kill(); }, options.timeout) : undefined;
    const output = { stdout: '', stderr: '' };
    function stream(name) {
      const mode = options[name] ?? 'pipe';
      const readable = child[name];
      if (mode && typeof mode === 'object' && typeof mode.file === 'string') {
        inside(home, path.resolve(mode.file));
        return { exposed: null, done: pipeline(readable, fs.createWriteStream(mode.file, {
          flags: mode.append ? 'a' : 'w', mode: 0o600,
        })) };
      }
      if (mode === 'ignore') {
        readable.resume();
        return { exposed: null };
      }
      if (options.buffer === false) return { exposed: readable };
      readable.setEncoding('utf8');
      readable.on('data', chunk => { output[name] = (output[name] + chunk).slice(-1_048_576); });
      return { exposed: readable, done: finished(readable) };
    }
    const stdout = stream('stdout');
    const stderr = stream('stderr');
    const exit = new Promise((resolve, reject) => {
      child.once('error', reject);
      child.once('exit', (exitCode, signal) => resolve({ exitCode, signal }));
    });
    const result = Promise.all([exit, stdout.done, stderr.done]).then(([status]) => ({
      ...status, ...output, failed: status.exitCode !== 0,
      timedOut, isCanceled: options.cancelSignal?.aborted ?? false,
      shortMessage: output.stderr.trim(),
    })).finally(() => {
      clearTimeout(timeout);
      clearTimeout(killTimer);
      options.cancelSignal?.removeEventListener('abort', kill);
    });
    return Object.assign(result, { pid: child.pid, kill, nodeChildProcess: child, stdout: stdout.exposed, stderr: stderr.exposed });
  };
}
module.exports = { createPackageRunner };

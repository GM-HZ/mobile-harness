'use strict';
const fs = require('node:fs');
const path = require('node:path');
const { createHash, randomUUID } = require('node:crypto');
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
    for (const name of ['stdout', 'stderr']) {
      const file = options[name]?.file;
      if (file) {
        inside(home, path.resolve(file));
        inside(home, fs.realpathSync(path.dirname(file)));
      }
    }
    options.cancelSignal?.throwIfAborted();
    const profileHome = guestPath(home);
    const prefix = command === 'pnpm' ? [
      '/bin/node', '--require', '/dsh-harmony-pnpm-fetch.cjs', '/pnpm-harmony-v2/bin/pnpm.mjs',
    ] : ['/usr/bin/git'];
    const actionIndex = args.findIndex(arg => !arg.startsWith('-'));
    const packageAction = args[actionIndex];
    const remapped = args.map((arg, index) => {
      const match = /^(file:|link:)?(\/.*)$/.exec(arg);
      if (!match) return arg;
      const local = fs.realpathSync(match[2]);
      const guest = guestPath(local);
      // pnpm links bare directory dependencies even with the hoisted linker.
      // HarmonyOS prohibits that symlink. file: copies the local package.
      const copyDirectory = command === 'pnpm' && packageAction === 'add' &&
        index === actionIndex + 1 && !match[1] && fs.statSync(local).isDirectory();
      return (copyDirectory ? 'file:' : match[1] || '') + guest;
    });
    if (command === 'pnpm' && ['add', 'install', 'remove', 'update'].includes(packageAction)) {
      remapped.push('--config.node-linker=hoisted', '--config.package-import-method=copy',
        '--store-dir=' + profileHome + '/package-store', '--config.ignore-scripts=true');
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
function createRegistryOrigins(home, mark) {
  function fileFor(profile, name, create = false) {
    const parent = fs.realpathSync(profile);
    const base = fs.realpathSync(home);
    if (!parent.startsWith(base + path.sep)) throw new Error('Registry provenance requires an application profile');
    const managerDir = path.join(parent, '.plugin-manager');
    const registryDir = path.join(managerDir, 'registry-origins');
    for (const folder of [managerDir, registryDir]) {
      if (create) {
        try { fs.mkdirSync(folder, { mode: 0o700 }); }
        catch (error) { if (error.code !== 'EEXIST') throw error; }
      }
      if (!fs.lstatSync(folder).isDirectory()) throw new Error('Registry provenance directory cannot be redirected');
    }
    return path.join(registryDir, createHash('sha256').update(name).digest('hex') + '.json');
  }

  function validRegistry(registry) {
    if (registry === null) return true;
    if (typeof registry !== 'string') return false;
    try {
      const url = new URL(registry);
      return ['http:', 'https:'].includes(url.protocol) && !url.username && !url.password && !url.search && !url.hash;
    } catch { return false; }
  }

  function warn(operation, error) {
    if (error?.code !== 'ENOENT') mark('package-registry-provenance-error', { operation, code: error?.code ?? 'unknown' });
  }

  return {
    read(profile, name, version) {
      if (typeof version !== 'string') return undefined;
      try {
        const file = fileFor(profile, name);
        if (!fs.lstatSync(file).isFile()) return undefined;
        const record = JSON.parse(fs.readFileSync(file, 'utf8'));
        if (record.name === name && record.version === version && validRegistry(record.registry)) return record.registry;
      } catch (error) { warn('read', error); }
      return undefined;
    },
    record(profile, name, version, registry) {
      if (typeof version !== 'string' || !validRegistry(registry)) return;
      let temporary;
      try {
        const file = fileFor(profile, name, true);
        temporary = file + '.' + randomUUID() + '.tmp';
        fs.writeFileSync(temporary, JSON.stringify({ name, version, registry }) + '\n', { flag: 'wx', mode: 0o600, flush: true });
        fs.renameSync(temporary, file);
      } catch (error) {
        warn('record', error);
      } finally {
        if (temporary) {
          try { fs.rmSync(temporary, { force: true }); } catch (error) { warn('clean', error); }
        }
      }
    },
    forget(profile, name) {
      try { fs.rmSync(fileFor(profile, name), { force: true }); }
      catch (error) { warn('forget', error); }
    },
  };
}

module.exports = { createPackageRunner, createRegistryOrigins };

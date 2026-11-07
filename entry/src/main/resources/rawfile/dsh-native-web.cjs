'use strict';
const fs = require('node:fs');
const http = require('node:http');
const { spawn } = require('node:child_process');
const { EventEmitter } = require('node:events');
const { constants } = require('node:os');
const { Module, registerHooks } = require('node:module');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { performance } = require('node:perf_hooks');
const started = performance.now();
const root = process.env.HARMONY_NATIVE_WEB_ROOT;
const dsh = path.join(root, 'dsh/node_modules');
const cli = path.join(dsh, '@deepseek-ai/dsh/lib/bin.js');
const home = path.join(root, 'native-benchmark-home');
const workspace = path.join(root, 'workspace-native');
const timeline = path.join(root, 'tmp/dsh-native-timeline.log');
const launchFile = path.join(root, 'tmp/dsh-client-native-launch');
const base = 'http://127.0.0.1:19592/';
const ms = () => Math.round(performance.now() - started);
function mark(event, details = {}) {
  fs.appendFileSync(timeline, JSON.stringify({ event, ms: ms(), ...details }) + '\n', { mode: 0o600 });
}
function fail(error) {
  mark('failed', { error: String(error?.stack ?? error)
    .replace(/token=[^\s"'&]+/g, 'token=[redacted]').replace(/sk-[a-z0-9]{32}/gi, '[redacted]').slice(0, 2500) });
}
function addon(name) {
  const module = { exports: {} };
  process.dlopen(module, name);
  return module.exports;
}
function installProotSpawn(workspace) {
  const bridge = addon('libdshshell.so');
  const allowedRoot = fs.realpathSync(workspace);
  const signals = new Map(Object.entries(constants.signals).map(([name, value]) => [value, name]));
  globalThis.__harmonyProotSpawn = (program, args, options) => {
    if (program !== 'bash') return spawn(program, args, options);
    if (args.length !== 2 || args[0] !== '-c' ||
        options.stdio.join(',') !== 'ignore,pipe,pipe') {
      throw new Error('Harmony Bash currently accepts one non-interactive command with captured output');
    }
    const cwd = fs.realpathSync(options.cwd);
    const relative = path.relative(allowedRoot, cwd);
    if (relative === '..' || relative.startsWith('../') || path.isAbsolute(relative)) {
      throw new Error('Harmony Bash requires a directory in the native DSH workspace');
    }
    const guest = path.posix.join('/workspace-native', relative);
    const launched = bridge.launch(path.dirname(root), guest, args[1]);
    const child = new EventEmitter();
    child.pid = launched.pid;
    child.exitCode = null;
    child.signalCode = null;
    child.stdin = null;
    child.stdout = fs.createReadStream(null, { fd: launched.stdoutFd });
    child.stderr = fs.createReadStream(null, { fd: launched.stderrFd });
    child.stdio = [child.stdin, child.stdout, child.stderr];
    child.kill = (signal = 'SIGTERM') => process.kill(-child.pid, signal);
    const timer = setInterval(() => {
      try {
        const result = bridge.pollExit(child.pid);
        if (!result) return;
        clearInterval(timer);
        child.exitCode = result.exitCode < 0 ? null : result.exitCode;
        child.signalCode = signals.get(result.signal) ?? null;
        child.emit('exit', child.exitCode, child.signalCode);
      } catch (error) {
        clearInterval(timer);
        child.emit('error', error);
      }
    }, 25);
    return child;
  };
}
function httpGet(url, headers = {}) {
  return new Promise((resolve, reject) => {
    const request = http.get(url, { headers, agent: false }, response => {
      response.resume();
      response.on('end', () => resolve(response));
      response.on('error', reject);
    });
    request.on('error', reject);
    request.setTimeout(3000, () => request.destroy(new Error('loopback timeout')));
  });
}
async function publish(url) {
  const exchange = await httpGet(url);
  const cookie = exchange.headers['set-cookie']?.[0];
  if (exchange.statusCode !== 303 || !cookie) throw new Error('DSH token exchange failed');
  const page = await httpGet(base, { Cookie: cookie.split(';', 1)[0] });
  if (page.statusCode !== 200) throw new Error('DSH local page returned HTTP ' + page.statusCode);
  fs.writeFileSync(launchFile + '.new', JSON.stringify({ url: base, cookie }), { mode: 0o600 });
  fs.renameSync(launchFile + '.new', launchFile);
  mark('loopback-ready', { exchange: 303, page: 200 });
}
async function main() {
  fs.writeFileSync(timeline, '', { mode: 0o600 });
  mark('node-js', { platform: process.platform, node: process.version });
  fs.mkdirSync(home, { recursive: true });
  fs.mkdirSync(workspace, { recursive: true });
  process.chdir(workspace);
  process.env.HOME = home;
  process.env.DSH_HOME = home;
  process.env.DSH_TELEMETRY_DISABLED = '1';
  process.env.DSH_PERMISSION_MODE = 'workspace-write';
  process.env.NO_COLOR = '1';
  require(path.join(root, 'fetch-shim.cjs')).installFetchShim();

  const realLoad = Module._load;
  Module._load = function (id, ...args) {
    if (id === 'node-addon-require-builtin') {
      return { requireBuiltin: name => require(name), isAllowedInternalId: name => name.startsWith('internal/') };
    }
    return realLoad.call(this, id, ...args);
  };
  const paths = name => pathToFileURL(path.join(dsh, '@deepseek-ai', name)).href;
  const flockUrl = paths('node-addon-system/lib/flock.js');
  const persistenceUrl = paths('dsh-session-persistence-jsonl/lib/index.js');
  const subprocessUrl = paths('dsh-subprocess-local/lib/index.js');
  installProotSpawn(workspace);
  const flock = addon('libdshflock.so').tryLock;
  const rename = addon('libdshpublish.so').renameNoReplace;
  globalThis.__harmonyWebFlock = flock;
  globalThis.__harmonyWebRename = (source, target) => {
    const errno = rename(source, target);
    if (errno) throw Object.assign(new Error('exclusive publish failed'), { errno, code: errno === 17 ? 'EEXIST' : 'EIO' });
  };
  let loadCount = 0;
  let loadMs = 0;
  let booting = true;
  registerHooks({
    load(url, context, nextLoad) {
      const start = performance.now();
      const result = nextLoad(url, context);
      if (booting) {
        loadCount++;
        loadMs += performance.now() - start;
      }
      if (url !== flockUrl && url !== persistenceUrl && url !== subprocessUrl) return result;
      const source = typeof result.source === 'string' ? result.source : Buffer.from(result.source).toString();
      if (url === subprocessUrl) {
        const point = 'internals = {};';
        if (source.split(point).length !== 2) throw new Error('Unexpected pinned subprocess spawn seam');
        return { ...result, source: source.replace(point, 'internals = { spawn: globalThis.__harmonyProotSpawn };') };
      }
      const point = url === flockUrl ? '    const { platform, arch } = process;' : 'await link(tmp, finalPath);';
      const replacement = url === flockUrl
        ? "    if (process.platform === 'openharmony') return { tryLock: globalThis.__harmonyWebFlock };\n" + point
        : "try { await link(tmp, finalPath); } catch (error) { if (error?.code !== 'EACCES') throw error; globalThis.__harmonyWebRename(tmp, finalPath); }";
      if (source.split(point).length !== 2) throw new Error('Unexpected pinned native integration source');
      return { ...result, source: source.replace(point, replacement) };
    }
  });
  const exit = process.exit;
  process.exit = function (code) {
    if (booting) throw new Error('DSH requested startup exit ' + code);
    return exit.call(this, code);
  };
  const print = console.log.bind(console);
  console.log = (...args) => {
    const text = args[0];
    if (typeof text === 'string' && text.startsWith('dsh web: ' + base + '?token=')) {
      booting = false;
      mark('web-announced', { loadCount, loadMs: Math.round(loadMs) });
      publish(text.slice('dsh web: '.length)).catch(fail);
      return;
    }
    print(...args);
  };
  const nativePatch = path.join(root, 'tmp/dsh-native.patch.yml');
  fs.writeFileSync(nativePatch, '- id: workspace-controller\n  config:\n    documentsDirectory: ' + JSON.stringify(workspace) + '\n', { mode: 0o600 });
  process.argv = ['node', cli, '--patch', path.join(root, 'dsh-client.patch.yml'), '--patch', nativePatch,
    '--profile', 'web', '--host', '127.0.0.1', '--port', '19592', '--no-open'];
  const { runCli } = await import(pathToFileURL(cli).href);
  mark('cli-imported');
  await runCli();
  mark('profile-mounted');
}
main().catch(fail);

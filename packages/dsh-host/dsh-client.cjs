const fs = require('node:fs');
const { spawn, spawnSync } = require('node:child_process');
const http = require('node:http');
const path = require('node:path');
const { registerHooks } = require('node:module');
const { performance } = require('node:perf_hooks');
const { installBootCache } = require('./dsh-boot-cache.cjs');

const bootStarted = performance.now();
const elapsed = () => Math.round(performance.now() - bootStarted);
const initialCpu = process.cpuUsage();
const moduleLoads = { count: 0, ms: 0, packed: 0 };
function openStartupSources() {
  if (fs.existsSync('/tmp/dsh-startup-no-sources')) return;
  try {
    const bytes = require('node:zlib').gunzipSync(fs.readFileSync('/dsh-startup-sources.gz'), { maxOutputLength: 128 * 1024 * 1024 });
    const begin = 4 + bytes.readUInt32LE();
    if (begin > bytes.length) throw new Error('Invalid packed source index');
    const index = JSON.parse(bytes.toString('ascii', 4, begin));
    return (url) => {
      if (!Object.hasOwn(index, url)) return;
      const [offset, length] = index[url];
      return bytes.subarray(begin + offset, begin + offset + length);
    };
  } catch (error) {
    console.warn('DSH_STARTUP_SOURCES_UNAVAILABLE', error.code ?? error.name);
  }
}
const listen = http.Server.prototype.listen;
http.Server.prototype.listen = function (...args) {
  this.once('listening', () => console.log('DSH_STARTUP_LISTEN', elapsed()));
  return Reflect.apply(listen, this, args);
};

const cli = '/dsh/node_modules/@deepseek-ai/dsh/lib/bin.js';
const launchFile = '/tmp/dsh-client-launch';
const packages = '/dsh/node_modules/@deepseek-ai';
const bashPath = '/bin/bash';
const landlockPath = packages + '/node-addon-system-linux-arm64/bin/landlock-run';
const sessionModule = 'file://' + packages + '/dsh-session-persistence-jsonl/lib/index.js';
const PATCHED_SESSION = 'globalThis.__dshClientRenameNoReplace(tmp, finalPath)';
const bashModules = new Set([
  'file://' + packages + '/dsh-bash-local/lib/index.js',
  'file://' + packages + '/dsh-bash-sandbox/lib/index.js',
]);

function replacePinned(source, original, replacement, url) {
  if (source.split(original).length !== 2) throw new Error('Unexpected pinned DSH implementation: ' + url);
  return source.replace(original, replacement);
}

function activateSelfBuildTools() {
  const target = '/usr/bin/mh-exec';
  try {
    if (!fs.existsSync(target)) return;
    const mode = fs.statSync(target).mode & 0o777;
    if ((mode & 0o111) === 0o111) {
      console.log('DSH_CLIENT_SELF_BUILD_TOOLS', JSON.stringify({ target, mode: mode.toString(8) }));
      return;
    }
    const result = spawnSync('/bin/chmod', ['0755', target], { encoding: 'utf8', timeout: 5000 });
    console.log('DSH_CLIENT_SELF_BUILD_TOOLS', JSON.stringify({
      target, status: result.status, error: result.error?.code ?? null,
      mode: (fs.statSync(target).mode & 0o777).toString(8),
    }));
  } catch (error) {
    console.log('DSH_CLIENT_SELF_BUILD_TOOLS', JSON.stringify({ target, error: error.code ?? error.name }));
  }
}

async function probeBash() {
  activateSelfBuildTools();
  const args = ['-c', 'printf DSH_BASH_SPAWN_OK'];
  const options = { cwd: '/workspace', encoding: 'utf8', timeout: 5000 };
  const synchronous = spawnSync(bashPath, args, options);
  const asynchronous = await new Promise(resolve => {
    let stdout = '';
    const child = spawn(bashPath, args, { cwd: options.cwd, detached: true, stdio: ['ignore', 'pipe', 'pipe'] });
    const timer = setTimeout(() => child.kill('SIGKILL'), 5000);
    child.stdout.on('data', chunk => { stdout += chunk; });
    child.on('error', error => resolve({ error: error.code }));
    child.on('close', (status, signal) => {
      clearTimeout(timer);
      resolve({ status, signal, ok: stdout === 'DSH_BASH_SPAWN_OK' });
    });
  });
  const sandbox = spawnSync(landlockPath, ['--probe'], { ...options, stdio: ['ignore', 'pipe', 'pipe'] });
  const applets = spawnSync(bashPath, ['-c', 'set -o pipefail; ls -d /workspace | grep -Fx /workspace'], options);
  const rg = spawnSync('/dsh/node_modules/@vscode/ripgrep-linux-arm64/bin/rg', ['--version'], options);
  console.log('DSH_CLIENT_BASH_PROBE', JSON.stringify({
    sync: { status: synchronous.status, signal: synchronous.signal, error: synchronous.error?.code,
      ok: synchronous.stdout === 'DSH_BASH_SPAWN_OK' },
    async: asynchronous,
    applets: { status: applets.status, ok: applets.stdout === '/workspace\n', error: applets.error?.code,
      details: (applets.stderr ?? '').trim().slice(0, 260) },
    ripgrep: { status: rg.status, ok: (rg.stdout ?? '').startsWith('ripgrep '), error: rg.error?.code },
    landlock: { status: sandbox.status, signal: sandbox.signal, error: sandbox.error?.code,
      details: (sandbox.stdout + sandbox.stderr).trim().slice(0, 260) },
  }));
}

function get(url, headers = {}) {
  return new Promise((resolve, reject) => {
    const request = http.get(url, { headers, agent: false }, response => {
      response.on('data', () => {});
      response.on('end', () => resolve(response));
      response.on('error', reject);
    });
    request.on('error', reject);
    request.setTimeout(4000, () => request.destroy(new Error('Local DSH request timed out')));
  });
}

async function publishBrowserSession(url) {
  const home = url.origin + '/';
  const authStarted = elapsed();
  let session = { url: url.href };
  for (let attempt = 0; attempt < 3; ++attempt) {
    try {
      const exchange = await get(url);
      const cookie = exchange.headers['set-cookie']?.[0];
      if (exchange.statusCode !== 303 || !cookie) throw new Error('Local DSH token exchange failed');
      session = { url: home, cookie };
      console.log('DSH_CLIENT_AUTH_READY', exchange.statusCode, elapsed() - authStarted);
      break;
    } catch (error) {
      console.warn('DSH_CLIENT_HTTP_RETRY', attempt + 1, error.message);
    }
  }
  const temporary = launchFile + '.new';
  fs.writeFileSync(temporary, JSON.stringify(session), { mode: 0o600 });
  fs.renameSync(temporary, launchFile);
  console.log('DSH_CLIENT_LISTENING', elapsed());
}

async function start() {
  process.env.HOME = '/root';
  process.env.DSH_HOME = '/root/dsh-client';
  process.env.NO_COLOR = '1';
  process.env.NARB_DISABLE_NATIVE_CACHE = '1';
  process.env.DSH_PERMISSION_MODE = 'workspace-write';
  fs.mkdirSync('/workspace', { recursive: true });
  process.chdir('/workspace');

  const native = require('/harmony-publish.node');
  let collectBootMetrics = true;
  let getStartupSource = openStartupSources();
  registerHooks({
    load(url, context, nextLoad) {
      const started = performance.now();
      const packed = getStartupSource && context.format === 'module' &&
        Object.keys(context.importAttributes ?? {}).length === 0 ? getStartupSource(url) : undefined;
      const loaded = packed === undefined ? nextLoad(url, context) :
        { format: 'module', source: packed, shortCircuit: true };
      if (packed !== undefined) moduleLoads.packed++;
      if (collectBootMetrics) {
        moduleLoads.count++;
        moduleLoads.ms += performance.now() - started;
      }
      if (url !== sessionModule && !bashModules.has(url)) return loaded;
      const text = typeof loaded.source === 'string' ? loaded.source : Buffer.from(loaded.source).toString('utf8');
      let source;
      if (url === sessionModule) {
        if (text.includes('await link(tmp, finalPath);')) {
          source = replacePinned(text, 'await link(tmp, finalPath);',
            "try { await link(tmp, finalPath); } catch (error) { if (error?.code !== 'EACCES') throw error; globalThis.__dshClientRenameNoReplace(tmp, finalPath); }", url);
        } else if (text.includes(PATCHED_SESSION)) {
          // patches/series.json already carries the EACCES fallback.
          source = text;
        } else {
          throw new Error('Unexpected pinned DSH implementation: ' + url);
        }
      } else {
        source = replacePinned(text, '"bash",\n\t\t\t"-c",', JSON.stringify(bashPath) + ',\n\t\t\t"-c",', url);
      }
      return { ...loaded, source };
    }
  });
  globalThis.__dshClientRenameNoReplace = (source, target) => {
    const code = native.renameNoReplace(source, target);
    if (code) throw Object.assign(new Error('Session publish errno=' + code),
      { code: code === 17 ? 'EEXIST' : 'EIO', errno: -code });
  };

  const cacheEnabled = !fs.existsSync('/tmp/dsh-startup-no-cache');
  let stopCache;
  const print = console.log.bind(console);
  console.log = (...args) => {
    if (typeof args[0] === 'string' && args[0].startsWith('dsh web: http://127.0.0.1:')) {
      const url = new URL(args[0].slice('dsh web: '.length));
      if (url.hostname === '127.0.0.1' && url.port && url.searchParams.has('token')) {
        const cache = stopCache?.();
        collectBootMetrics = false;
        getStartupSource = undefined;
        const cpu = process.cpuUsage(initialCpu);
        print('DSH_STARTUP_READY', JSON.stringify({
          ms: elapsed(), cacheEnabled, cache,
          loaded: moduleLoads.count, packed: moduleLoads.packed, loadMs: Math.round(moduleLoads.ms),
          userCpuMs: Math.round(cpu.user / 1000), systemCpuMs: Math.round(cpu.system / 1000),
        }));
        publishBrowserSession(url).catch(error => {
          console.error('DSH_CLIENT_START_FAILED', error.message);
          process.exit(1);
        });
        return;
      }
    }
    print(...args);
  };

  process.argv = ['/bin/node', cli, '--patch', '/dsh-client.patch.yml', '--profile', 'web',
    '--host', '127.0.0.1', '--port', '19592', '--no-open'];
  console.log('DSH_CLIENT_START', process.version, path.basename(process.cwd()));
  if (fs.existsSync('/tmp/dsh-startup-probe-tools')) {
    await probeBash().catch(error => console.warn('DSH_CLIENT_BASH_PROBE_ERROR', error.code ?? error.name));
  }
  if (cacheEnabled) stopCache = installBootCache('/dsh/node_modules');
  console.log('DSH_STARTUP_IMPORT', elapsed(), cacheEnabled);
  try {
    const { runCli } = await import('file://' + cli);
    console.log('DSH_STARTUP_CLI_IMPORTED', elapsed());
    await runCli();
    console.log('DSH_STARTUP_PROFILE_MOUNTED', elapsed());
  } catch (error) {
    stopCache?.();
    throw error;
  }
}

start().catch(error => {
  console.error('DSH_CLIENT_START_FAILED', error);
  process.exit(1);
});

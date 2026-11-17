'use strict';
const fs = require('node:fs');
const { randomUUID } = require('node:crypto');
const http = require('node:http');
const { Socket } = require('node:net');
const { spawn } = require('node:child_process');
const { EventEmitter } = require('node:events');
const { constants } = require('node:os');
const { Module, registerHooks } = require('node:module');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { performance } = require('node:perf_hooks');
const started = performance.now();
const safeMode = process.env.HARMONY_SAFE_MODE === '1';
const root = process.env.HARMONY_NATIVE_WEB_ROOT;
const dsh = path.join(root, '.dsh-0.2.2-rc.4/dsh/node_modules');
const cli = path.join(dsh, '@deepseek-ai/dsh/lib/bin.js');
const home = path.join(root, 'native-benchmark-home');
const workspace = path.join(root, 'workspace-native');
const ripgrep = path.join(dsh, '@vscode/ripgrep-linux-arm64/bin/rg');
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
function replacePinned(source, point, replacement) {
  if (source.split(point).length !== 2) throw new Error('Unexpected pinned native integration source');
  return source.replace(point, replacement);
}
function patchWorkflow(source) {
  const start = '\t\t\tif (this.runtime.sandboxMode === void 0 && this.policy.mode';
  const end = '\t\t\tthis.terminal = true;';
  const index = source.indexOf(start);
  const stop = source.indexOf(end, index);
  if (index < 0 || stop < 0 || source.indexOf(start, index + 1) !== -1 ||
      !source.slice(index, stop).includes('const outcome = await this.runtime.run(this.runtime.resolve({')) {
    throw new Error('Unexpected pinned workflow-ptc execution entry');
  }
  return source.slice(0, index) +
    '\t\t\tconst outcome = await globalThis.__harmonyWorkflowRun(this.bindings(), this.controller.signal);\n' +
    source.slice(stop);
}
function patchPtc(source) {
  const start = '\t\tconst executable = await this.ctx.subprocess.resolveExecutable';
  const end = '\t\tthis.handle = handle;';
  const index = source.indexOf(start);
  const stop = source.indexOf(end, index);
  if (index < 0 || stop < 0 || source.indexOf(start, index + 1) !== -1 ||
      !source.slice(index, stop).includes('const handle = this.ctx.subprocess.spawn({')) {
    throw new Error('Unexpected pinned PTC worker entry');
  }
  const replacement = `    if (this.closed) return;
    let handle;
    try {
      handle = globalThis.__harmonyPtc.launch(cwd, this.policy, this.config, this.controller.signal);
    } catch (error) {
      throw new SandboxUnavailableError(this.policy.mode, String(error?.message ?? error));
    }
    this.confined = {
      argv: ["harmonyos-ptc"], enforcement: "partial",
      denialSignatures: ["permission denied", "eacces", "eperm", "exdev"],
      runnerFailureRules: [],
    };
`;
  return replacePinned(source.slice(0, index) + replacement + source.slice(stop),
    'import { stripTypeScriptTypes } from "node:module";',
    'const stripTypeScriptTypes = globalThis.__harmonyPtc.strip;');
}
function quoteShellArgument(value) {
  if (typeof value !== 'string' || value.includes('\0')) throw new TypeError('Invalid command argument');
  return "'" + value.replaceAll("'", "'\\''") + "'";
}
function installProotSpawn(workspace) {
  const bridge = addon('libdshshell.so');
  const allowedRoot = fs.realpathSync(workspace);
  const signals = new Map(Object.entries(constants.signals).map(([name, value]) => [value, name]));
  globalThis.__harmonyHostSpawn = (program, args, options) => {
    if (safeMode) throw new Error('Guest subprocesses are disabled in HarmonyOS recovery mode');
    // Keep the existing bounded search adapter and its signed /bin/rg mapping.
    if (program === ripgrep) return globalThis.__harmonyProotSpawn(program, args, options);
    if (!Array.isArray(options.stdio) || options.stdio.length !== 3 ||
        !['ignore', 'pipe'].includes(options.stdio[0]) ||
        options.stdio.slice(1).some(mode => !['pipe', 'inherit'].includes(mode))) {
      throw new Error('Harmony subprocess supports standard input/output pipes; extra control descriptors are unavailable');
    }
    const cwd = fs.realpathSync(options.cwd);
    relativeInWorkspace(allowedRoot, cwd);
    const environment = Object.entries(options.env ?? {}).flatMap(([key, value]) => {
      if (value === undefined) return [];
      if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(key) || /^(?:HARMONY_|PROOT_|LD_)/.test(key) ||
          typeof value !== 'string' || value.includes('\0')) {
        throw new TypeError('Invalid or reserved Harmony subprocess environment variable');
      }
      return [key + '=' + value];
    });
    const child = launchGuest(cwd, 'exec -- ' + [program, ...args].map(quoteShellArgument).join(' '), environment, true);
    if (options.stdio[0] === 'ignore') child.stdin.end();
    for (const [index, destination] of [[1, process.stdout], [2, process.stderr]]) {
      if (options.stdio[index] === 'inherit') {
        child.stdio[index].pipe(destination, { end: false });
        child.stdio[index] = null;
        child[index === 1 ? 'stdout' : 'stderr'] = null;
      }
    }
    return child;
  };
  globalThis.__harmonyMcpSpawn = (program, args, options) => {
    if (safeMode) throw new Error('Local MCP servers are disabled in HarmonyOS recovery mode');
    if (typeof program !== 'string' || program.length === 0) throw new TypeError('Expected an MCP command');
    const requested = options.cwd || allowedRoot;
    const hostCwd = requested === '/workspace-native' || requested.startsWith('/workspace-native/')
      ? path.join(allowedRoot, path.posix.relative('/workspace-native', requested))
      : path.resolve(allowedRoot, requested);
    const guest = path.posix.join('/workspace-native', relativeInWorkspace(allowedRoot, fs.realpathSync(hostCwd)));
    const environment = Object.entries(options.env ?? {}).map(([key, value]) => {
      if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(key) ||
          /^(?:HARMONY_|PROOT_|LD_)/.test(key) ||
          ['BASH_ENV', 'ENV', 'NODE_OPTIONS', 'PATH', 'HOME', 'TMPDIR'].includes(key) ||
          typeof value !== 'string' || value.includes('\0')) {
        throw new TypeError('Invalid or reserved MCP environment variable');
      }
      return key + '=' + value;
    });
    return launchGuest(guest, 'exec -- ' + [program, ...args].map(quoteShellArgument).join(' '), environment);
  };
  globalThis.__harmonyProotSpawn = (program, args, options) => {
    if (program !== 'bash' && program !== ripgrep) return spawn(program, args, options);
    if (options.stdio.join(',') !== 'ignore,pipe,pipe') throw new Error('Harmony tools require captured output');
    const cwd = fs.realpathSync(options.cwd);
    const guest = path.posix.join('/workspace-native', relativeInWorkspace(allowedRoot, cwd));
    let command;
    if (program === ripgrep) {
      const separator = args.indexOf('--');
      const flags = separator < 0 ? args : args.slice(0, separator);
      if (flags[0] !== '--no-config' || !['--files', '--json'].includes(flags[1]) ||
          flags.slice(2).some(value => !/^--(?:glob=|regexp=|sort=modified$|no-ignore$|hidden$)/.test(value)) ||
          (separator >= 0 && args.length !== separator + 2)) {
        throw new Error('Unsupported Harmony ripgrep argument vector');
      }
      if (separator >= 0) {
        const requested = fs.realpathSync(path.resolve(cwd, args[separator + 1]));
        relativeInWorkspace(allowedRoot, requested);
        flags.push('--', './' + (path.relative(cwd, requested) || '.'));
      }
      command = 'exec /bin/rg ' + flags.map(quoteShellArgument).join(' ');
    } else {
      if (args.length !== 2 || args[0] !== '-c') throw new Error('Harmony Bash requires one non-interactive command');
      command = args[1];
    }
    return launchGuest(guest, command);
  };
  function launchGuest(guest, command, environment, host = false) {
    const streaming = environment !== undefined;
    const launched = streaming
      ? bridge.launchPiped(path.dirname(root), guest, command, environment)
      : bridge.launch(path.dirname(root), guest, command);
    const child = new EventEmitter();
    child.pid = launched.pid;
    if (host) mark('host-subprocess-started', { pid: child.pid });
    child.exitCode = null;
    child.signalCode = null;
    child.stdin = streaming ? new Socket({ fd: launched.stdinFd, readable: false, writable: true }) : null;
    child.stdout = streaming ? new Socket({ fd: launched.stdoutFd, readable: true, writable: false })
      : fs.createReadStream(null, { fd: launched.stdoutFd });
    child.stderr = streaming ? new Socket({ fd: launched.stderrFd, readable: true, writable: false })
      : fs.createReadStream(null, { fd: launched.stderrFd });
    child.stdio = [child.stdin, child.stdout, child.stderr];
    let exited = false;
    child.kill = (signal = 'SIGTERM') => {
      if (exited) return false;
      try {
        return process.kill(-child.pid, signal);
      } catch (error) {
        if (error?.code === 'ESRCH') return false;
        throw error;
      }
    };
    if (streaming) {
      // The MCP SDK expects the ChildProcess lifecycle: exit first, then close after output.
      const streamsClosed = Promise.all([child.stdout, child.stderr].map(stream =>
        new Promise(resolve => stream.once('close', resolve))));
      child.once('exit', () => {
        child.stdin.destroy();
        void streamsClosed.then(() => child.emit('close', child.exitCode, child.signalCode));
      });
      child.stderr.on('error', () => {});
      child.stderr.resume();
      queueMicrotask(() => child.emit('spawn'));
    }
    const timer = setInterval(() => {
      let result;
      try {
        result = bridge.pollExit(child.pid);
        if (!result) return;
        clearInterval(timer);
        exited = true;
        if (host) mark('host-subprocess-reaped', { pid: child.pid });
        child.exitCode = result.exitCode < 0 ? null : result.exitCode;
        child.signalCode = signals.get(result.signal) ?? null;
        if (child.exitCode === 0) {
          const status = Buffer.alloc(3);
          const count = fs.readSync(launched.statusFd, status);
          const text = status.toString();
          if (count !== 3 || !/^\d{3}$/.test(text) || Number(text) > 255) {
            throw new Error('Bash exited without a valid command status');
          }
          child.exitCode = Number(text);
        }
      } catch (error) {
        clearInterval(timer);
        exited = true;
        if (!result) fs.closeSync(launched.statusFd);
        child.emit('error', error);
        if (streaming) {
          for (const stream of child.stdio) stream?.destroy();
          child.emit('exit', child.exitCode, child.signalCode);
        }
        return;
      } finally {
        if (result) fs.closeSync(launched.statusFd);
      }
      child.emit('exit', child.exitCode, child.signalCode);
    }, 25);
    return child;
  }
  return launchGuest;
}
function relativeInWorkspace(root, target) {
  const relative = path.relative(root, target);
  if (relative === '..' || relative.startsWith('../') || path.isAbsolute(relative)) {
    throw new Error('Harmony tool requires a path in the native DSH workspace');
  }
  return relative;
}
async function sortGlobPaths(paths, workdir, signal) {
  const entries = [];
  for (let offset = 0; offset < paths.length; offset += 32) {
    signal.throwIfAborted();
    const batch = await Promise.all(paths.slice(offset, offset + 32).map(async file => {
      try {
        const info = await fs.promises.lstat(path.resolve(workdir, file), { bigint: true });
        return { file, modified: info.mtimeNs };
      } catch (error) {
        if (error?.code !== 'ENOENT' && error?.code !== 'ENOTDIR') throw error;
        return null;
      }
    }));
    entries.push(...batch.filter(Boolean));
  }
  signal.throwIfAborted();
  entries.sort((a, b) => a.modified < b.modified ? -1 : a.modified > b.modified ? 1 : 0);
  return entries.map(entry => entry.file);
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
  mark('node-js', { platform: process.platform, node: process.version, safeMode });
  fs.mkdirSync(home, { recursive: true });
  fs.mkdirSync(workspace, { recursive: true });
  const passwd = path.join(root, 'etc/passwd');
  fs.writeFileSync(passwd + '.new', `mobile-harness:x:${process.getuid()}:${process.getgid()}:Mobile Harness:/workspace-native:/bin/bash
`, { mode: 0o644 });
  fs.renameSync(passwd + '.new', passwd);
  process.chdir(workspace);
  process.env.HOME = home;
  process.env.DSH_HOME = home;
  process.env.TMPDIR = path.join(root, 'tmp');
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
  const appBootUrl = paths('dsh-app-boot/lib/index.js');
  const flockUrl = paths('node-addon-system/lib/flock.js');
  const persistenceUrl = paths('dsh-session-persistence-jsonl/lib/index.js');
  const subprocessUrl = paths('dsh-subprocess-local/lib/index.js');
  const attachmentUrl = paths('dsh-attachment-local/lib/index.js');
  const searchUrl = paths('dsh-tool-fs-search/lib/index.js');
  const ripgrepUrl = paths('dsh-util-ripgrep/lib/index.js');
  const packageUrl = paths('dsh-plugin-manager/lib/index.js');
  const mcpClientUrl = paths('dsh-mcp-client/lib/index.js');
  const workflowUrl = paths('dsh-workflow-ptc/lib/index.js');
  const ptcUrl = paths('dsh-ptc-runtime-node/lib/index.js');
  const officeUrl = paths('dsh-office-kit/lib/index.js');
  const httpParserUrl = pathToFileURL(path.join(dsh, 'undici/lib/dispatcher/client-h1.js')).href;
  const { patchClientH1 } = require(path.join(root, 'dsh-harmony-http.cjs'));
  globalThis.__harmonyLlhttp = imports => require(path.join(root, 'dsh-harmony-llhttp.cjs'))(imports);
  const officeAdapter = pathToFileURL(path.join(root, 'dsh-harmony-office-entry.mjs')).href;
  const ptcEnabled = !safeMode && fs.readFileSync(path.join(root, 'dsh-harmony-ptc-enabled'), 'utf8') === '1';
  if (ptcEnabled) {
    globalThis.__harmonyPtc = require(path.join(root, 'dsh-harmony-ptc.cjs')).bindPtc(addon('libdshworkflow.so'), mark);
  }
  const mcpStdioUrl = pathToFileURL(path.join(dsh, '@modelcontextprotocol/client/dist/stdio.mjs')).href;
  const launchGuest = installProotSpawn(workspace);
  globalThis.__harmonyOffice = safeMode ? {
    createConverter() { throw Object.assign(new Error('Office workers are disabled in HarmonyOS recovery mode'), { code: 'unavailable' }); },
  } : require(path.join(root, 'dsh-harmony-office.cjs')).createOfficeFactory(root,
    require(path.join(root, 'dsh-harmony-office-launch.cjs')).createOfficeLauncher(addon('libdshworkflow.so'), globalThis.__harmonyMcpSpawn, mark),
    mark, pathToFileURL(path.join(dsh, '@deepseek-ai/libreoffice-kit/lib/index.js')).href);
  const { createSharp } = require(path.join(root, 'dsh-harmony-sharp.cjs'));
  const { createPackageRunner } = require(path.join(root, 'dsh-harmony-package.cjs'));
  globalThis.__harmonySharp = createSharp(root, launchGuest);
  globalThis.__harmonyPackageRunner = createPackageRunner(root, home, launchGuest);
  globalThis.__harmonyWorkflowRun = safeMode
    ? () => { throw new Error('Workflows are disabled while HarmonyOS recovery mode is active'); }
    : require(path.join(root, 'dsh-harmony-workflow.cjs')).createWorkflowRunner(addon('libdshworkflow.so'), mark);
  const flock = addon('libdshflock.so').tryLock;
  const rename = addon('libdshpublish.so').renameNoReplace;
  globalThis.__harmonyWebFlock = flock;
  globalThis.__harmonyPackagedRg = ripgrep;
  globalThis.__harmonySortGlobPaths = sortGlobPaths;
  globalThis.__harmonyWebRename = (source, target) => {
    const errno = rename(source, target);
    if (errno) throw Object.assign(new Error('exclusive publish failed'), { errno, code: errno === 17 ? 'EEXIST' : 'EIO' });
  };
  globalThis.__harmonyAttachmentBoundary = (directory, filesystemRoot) =>
    directory === home ? root : filesystemRoot;
  globalThis.__harmonyAttachmentAlias = async (source, target) => {
    const temporary = path.join(path.dirname(target), '.' + randomUUID() + '.tmp');
    await fs.promises.copyFile(source, temporary, fs.constants.COPYFILE_EXCL);
    try {
      const handle = await fs.promises.open(temporary, 'r');
      try { await handle.sync(); } finally { await handle.close(); }
      globalThis.__harmonyWebRename(temporary, target);
    } finally {
      await fs.promises.rm(temporary, { force: true });
    }
  };
  let loadCount = 0;
  let loadMs = 0;
  let booting = true;
  registerHooks({
    resolve(specifier, context, nextResolve) {
      if (context.parentURL === officeUrl && specifier === '@deepseek-ai/libreoffice-kit') {
        return { url: officeAdapter, shortCircuit: true };
      }
      return nextResolve(specifier, context);
    },
    load(url, context, nextLoad) {
      const start = performance.now();
      const result = nextLoad(url, context);
      if (url === httpParserUrl && typeof WebAssembly === 'undefined') {
        const source = typeof result.source === 'string' ? result.source : Buffer.from(result.source).toString();
        mark('http-parser-portable', { runtime: 'llhttp-js' });
        return { ...result, source: patchClientH1(source) };
      }
      if (booting) {
        loadCount++;
        loadMs += performance.now() - start;
      }
      if (safeMode && url === appBootUrl) {
        const source = typeof result.source === 'string' ? result.source : Buffer.from(result.source).toString();
        return { ...result, source: replacePinned(source,
          '...loadOptionalPatches(binName, join(context.home, "cordis.patch.yml")) ?? [],',
          '...[],') };
      }
      if (url !== flockUrl && url !== persistenceUrl && url !== subprocessUrl &&
          url !== attachmentUrl && url !== searchUrl && url !== ripgrepUrl && url !== packageUrl &&
          url !== mcpClientUrl && url !== mcpStdioUrl && url !== workflowUrl && !(ptcEnabled && url === ptcUrl)) return result;
      const source = typeof result.source === 'string' ? result.source : Buffer.from(result.source).toString();
      if (url === ptcUrl) return { ...result, source: patchPtc(source) };
      if (url === workflowUrl) return { ...result, source: patchWorkflow(source) };
      if (url === mcpClientUrl) {
        return { ...result, source: replacePinned(source, 'env: buildChildEnv(config.env),', 'env: config.env,') };
      }
      if (url === mcpStdioUrl) {
        const isolated = replacePinned(source, '...getDefaultEnvironment(),', '');
        return { ...result, source: replacePinned(isolated, 'import spawn from "cross-spawn";',
          'const spawn = globalThis.__harmonyMcpSpawn;') };
      }
      if (url === subprocessUrl) {
        return { ...result, source: replacePinned(source, 'internals = {};', 'internals = { spawn: globalThis.__harmonyProotSpawn };') };
      }
      if (url === ripgrepUrl) {
        return { ...result, source: replacePinned(source,
          '(await import("@vscode/ripgrep")).rgPath', 'globalThis.__harmonyPackagedRg') };
      }
      if (url === searchUrl) {
        let patched = replacePinned(source, '\t\t"--sort=modified",\n', '');
        patched = replacePinned(patched, 'paths: all', 'paths: await globalThis.__harmonySortGlobPaths(all, run.workdir, exec.signal)');
        return { ...result, source: patched };
      }
      if (url === packageUrl) {
        return { ...result, source: replacePinned(source, 'import { execa } from "execa";',
          'const execa = globalThis.__harmonyPackageRunner;') };
      }
      if (url === attachmentUrl) {
        let patched = replacePinned(source, 'ensureDurableDirectory(home, parse(home).root)',
          'ensureDurableDirectory(home, globalThis.__harmonyAttachmentBoundary(home, parse(home).root))');
        patched = replacePinned(patched, 'createLazyRequire("sharp", import.meta.url)', '() => globalThis.__harmonySharp');
        patched = replacePinned(patched, 'await image.raw().toBuffer();', 'await image.verifyDecoded();');
        patched = replacePinned(patched, 'await link(staged.path, target);',
          "try { await link(staged.path, target); } catch (error) { if (error?.code !== 'EACCES') throw error; globalThis.__harmonyWebRename(staged.path, target); }");
        patched = replacePinned(patched, 'await unlink(staged.path);', 'await removeTemporary(staged.path);');
        patched = replacePinned(patched, 'await link(source, target);',
          "try { await link(source, target); } catch (error) { if (error?.code !== 'EACCES') throw error; await globalThis.__harmonyAttachmentAlias(source, target); }");
        return { ...result, source: patched };
      }
      const point = url === flockUrl ? '    const { platform, arch } = process;' : 'await link(tmp, finalPath);';
      const replacement = url === flockUrl
        ? "    if (process.platform === 'openharmony') return { tryLock: globalThis.__harmonyWebFlock };\n" + point
        : "try { await link(tmp, finalPath); } catch (error) { if (error?.code !== 'EACCES') throw error; globalThis.__harmonyWebRename(tmp, finalPath); }";
      return { ...result, source: replacePinned(source, point, replacement) };
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
  fs.writeFileSync(nativePatch, '- id: workspace-controller\n  config:\n    documentsDirectory: ' + JSON.stringify(workspace) + '\n' +
    (safeMode ? '' : '- id: subprocess\n  disabled: true\n- insert:\n    - id: harmony-subprocess\n      name: ' +
      JSON.stringify(path.join(root, 'dsh-harmony-subprocess.mjs')) + '\n'), { mode: 0o600 });
  const profileArgs = safeMode
    ? ['--profile', 'mobile-recovery', '--from-default-profile', 'web']
    : ['--profile', 'web'];
  process.argv = ['node', cli, '--patch', path.join(root, 'dsh-client.patch.yml'), '--patch', nativePatch,
    ...profileArgs, '--host', '127.0.0.1', '--port', '19592', '--no-open'];
  const { runCli } = await import(pathToFileURL(cli).href);
  mark('cli-imported');
  await runCli();
  mark('profile-mounted');
}
main().catch(fail);

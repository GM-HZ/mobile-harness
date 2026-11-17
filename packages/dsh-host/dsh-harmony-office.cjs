'use strict';
const path = require('node:path');
const { randomUUID } = require('node:crypto');

const FRAME = 'MH_OFFICE_RPC ';
const MAX_FRAME = 128 * 1024;

function createOfficeFactory(root, spawn, mark, kitModule) {
  const physicalRoot = path.resolve(root);
  function guestPath(value) {
    if (typeof value !== 'string' || !path.isAbsolute(value)) throw new TypeError('Expected an absolute Office path');
    value = path.resolve(value);
    if (value === '/system/fonts' || value.startsWith('/system/fonts/')) {
      return '/usr/share/fonts/harmonyos' + value.slice('/system/fonts'.length);
    }
    const relative = path.relative(physicalRoot, value);
    if (relative === '..' || relative.startsWith('../') || path.isAbsolute(relative)) {
      throw new Error('Office scratch and font paths must be inside the application runtime');
    }
    return '/' + relative.split(path.sep).join('/');
  }
  function hostImages(result, request, native) {
    const output = native ? request.outputDir : guestPath(request.outputDir);
    return { ...result, inputPath: request.inputPath, images: result.images.map(image => {
      const relative = path.posix.relative(output, image.path);
      if (!relative || relative === '..' || relative.startsWith('../') || path.posix.isAbsolute(relative)) {
        throw new Error('Office engine returned an image outside its private output directory');
      }
      return { ...image, path: path.join(request.outputDir, relative) };
    }) };
  }
  async function connect(options = {}) {
      const { resolveEnginePackage: _resolver, ...settings } = options;
      const directories = settings.fontDirectories ?? ['/system/fonts'];
      directories.forEach(guestPath);
      if (typeof settings.fontMetadataCacheDirectory === 'string') guestPath(settings.fontMetadataCacheDirectory);
      const workerId = randomUUID();
      const child = await spawn();
      const native = child.runtime === 'native';
      const runtimePath = value => native ? path.resolve(value) : guestPath(value);
      settings.fontDirectories = directories.map(runtimePath);
      if (typeof settings.fontMetadataCacheDirectory === 'string') {
        settings.fontMetadataCacheDirectory = runtimePath(settings.fontMetadataCacheDirectory);
      }
      const pending = new Map();
      let buffer = '', diagnostics = '', terminal = false, closed = false, disposed;
      let settleClose;
      const exited = new Promise(resolve => { settleClose = resolve; });
      mark('office-worker-started', { id: workerId, pid: child.pid, runtime: child.runtime });
      function failure(message) {
        return Object.assign(new Error(message + (diagnostics ? ': ' + diagnostics : '')), {
          name: 'ConversionError', code: 'unavailable',
        });
      }
      function stop(error) {
        if (terminal) return;
        terminal = true;
        for (const item of pending.values()) item.reject(error);
        pending.clear();
        child.kill('SIGKILL');
      }
      child.stderr.setEncoding('utf8');
      child.stderr.on('data', text => { if (diagnostics.length < 4096) diagnostics += text.slice(0, 4096 - diagnostics.length); });
      child.stdout.setEncoding('utf8');
      child.stdout.on('data', text => {
        buffer += text;
        if (buffer.length > MAX_FRAME && !buffer.includes('\n')) return stop(failure('Office worker frame exceeded its limit'));
        let index;
        while ((index = buffer.indexOf('\n')) >= 0) {
          const line = buffer.slice(0, index); buffer = buffer.slice(index + 1);
          if (line.length > MAX_FRAME) return stop(failure('Office worker frame exceeded its limit'));
          if (!line.startsWith(FRAME)) continue;
          let frame;
          try { frame = JSON.parse(line.slice(FRAME.length)); }
          catch { return stop(failure('Invalid Office worker response')); }
          const item = pending.get(frame.id);
          if (!item) continue;
          if (frame.event === 'running') {
            mark('office-operation-running', { id: workerId, request: frame.id, method: item.method });
            continue;
          }
          pending.delete(frame.id);
          if (item.method !== 'initialize' && item.method !== 'dispose') {
            mark('office-operation-ended', { id: workerId, request: frame.id, method: item.method,
              elapsedMs: Date.now() - item.started, code: frame.error?.code ?? 'completed' });
          }
          if (frame.error) item.reject(Object.assign(new Error(frame.error.message), {
            name: 'ConversionError', code: frame.error.code,
          }));
          else item.resolve(frame.value);
        }
      });
      child.on('error', error => stop(failure(String(error))));
      child.stdin.on('error', error => { if (!closed) stop(failure(String(error))); });
      child.on('exit', (code, signal) => {
        terminal = true;
        for (const item of pending.values()) item.reject(failure('Office worker exited before completing its request'));
        pending.clear();
        mark('office-worker-reaped', { id: workerId, pid: child.pid, code, signal });
      });
      child.on('close', () => { settleClose(); });
      function send(frame) {
        if (terminal) throw failure('Office worker is no longer running');
        child.stdin.write(JSON.stringify(frame) + '\n');
      }
      async function call(method, request, signal) {
        signal?.throwIfAborted();
        if (closed && method !== 'dispose') throw failure('Office converter is disposed');
        const id = randomUUID();
        let timer, forced;
        let aborted = false;
        const abort = () => {
          aborted = true;
          try { send({ method: 'cancel', target: id }); } catch { /* exit rejects the pending request */ }
          forced = setTimeout(() => stop(failure('Office worker did not acknowledge cancellation')), 5000);
        };
        const result = new Promise((resolve, reject) => { pending.set(id, { resolve, reject, method, started: Date.now() }); });
        try {
          send({ id, method, request });
          signal?.addEventListener('abort', abort, { once: true });
          // The Kit owns the conversion deadline; this also covers a failed transport or stuck initialization.
          const budget = method === 'initialize' || method === 'dispose' ? 30000 : (settings.timeoutMs ?? 120000) + 15000;
          timer = setTimeout(() => stop(failure('Office worker exceeded its response deadline')), budget);
          return await result;
        } catch (error) {
          if (terminal) await exited;
          if (aborted) throw signal.reason;
          throw error;
        } finally {
          pending.delete(id); clearTimeout(timer); clearTimeout(forced);
          signal?.removeEventListener('abort', abort);
        }
      }
      try { await call('initialize', { settings, engineModule: native ? kitModule : 'file:///dsh/node_modules/@deepseek-ai/libreoffice-kit/lib/index.js' }); }
      catch (error) { stop(error); await exited; throw error; }
      function operation(method, request, signal) {
        guestPath(request.inputPath);
        guestPath(method === 'renderImages' ? request.outputDir : request.outputPath);
        const translated = { ...request, inputPath: runtimePath(request.inputPath) };
        if (method === 'renderImages') translated.outputDir = runtimePath(request.outputDir);
        else translated.outputPath = runtimePath(request.outputPath);
        return call(method, translated, signal).then(result => method === 'renderImages' ? hostImages(result, request, native) : result);
      }
      return {
        backend: 'wasm',
        get unavailable() { return terminal; },
        render: (request, signal) => operation('render', request, signal),
        convert: (request, signal) => operation('convert', request, signal),
        recalculate: (request, signal) => operation('recalculate', request, signal),
        renderImages: (request, signal) => operation('renderImages', request, signal),
        dispose() {
          if (disposed) return disposed;
          closed = true;
          disposed = (async () => {
            try { if (!terminal) await call('dispose'); }
            finally {
              child.stdin.end();
              const deadline = setTimeout(() => { if (!terminal) child.kill('SIGKILL'); }, 2000);
              try { await exited; } finally { clearTimeout(deadline); }
            }
          })();
          return disposed;
        },
      };
  }
  return {
    async createConverter(options) {
      let current = await connect(options);
      let opening, disposed, closed = false;
      const unavailable = () => Object.assign(new Error('Office converter is disposed'), { code: 'unavailable' });
      async function acquire() {
        if (closed) throw unavailable();
        if (current.unavailable) {
          if (!opening) {
            const previous = current;
            opening = (async () => {
              await previous.dispose();
              current = await connect(options);
            })();
          }
          const attempt = opening;
          try { await attempt; } finally { if (opening === attempt) opening = undefined; }
        }
        if (closed) throw unavailable();
        return current;
      }
      return {
        backend: 'wasm',
        render: async (request, signal) => (await acquire()).render(request, signal),
        convert: async (request, signal) => (await acquire()).convert(request, signal),
        recalculate: async (request, signal) => (await acquire()).recalculate(request, signal),
        renderImages: async (request, signal) => (await acquire()).renderImages(request, signal),
        dispose() {
          if (!disposed) {
            closed = true;
            disposed = (async () => {
              try { await opening; } finally { await current.dispose(); }
            })();
          }
          return disposed;
        },
      };
    },
  };
}
module.exports = { createOfficeFactory };

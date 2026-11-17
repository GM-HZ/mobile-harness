'use strict';
const { Socket } = require('node:net');
const { PassThrough } = require('node:stream');
const { EventEmitter } = require('node:events');
const { randomUUID } = require('node:crypto');
const { constants } = require('node:os');

function createOfficeLauncher(native, guest, record) {
  let unsupported = false;
  const signals = new Map(Object.entries(constants.signals).map(([name, value]) => [value, name]));
  function launchNative() {
    const worker = native.launchOffice();
    const socket = new Socket({ fd: worker.fd, readable: true, writable: true });
    const child = new EventEmitter();
    child.closed = new Promise(resolve => child.once('close', resolve));
    child.pid = worker.pid; child.runtime = 'native';
    child.stdin = child.stdout = socket; child.stderr = new PassThrough();
    let finished = false, channelClosed = false, channelLost = false, closeSent = false;
    const maybeClose = () => {
      if (finished && channelClosed && !closeSent) { closeSent = true; child.emit('close', child.exitCode, child.signalCode); }
    };
    function finish(code, signal) {
      if (finished) return;
      finished = true; clearInterval(timer);
      child.exitCode = signal ? null : code; child.signalCode = signals.get(signal) ?? null;
      child.stderr.end();
      record('office-native-process-reaped', { id: worker.id, pid: worker.pid, code, signal });
      child.emit('exit', child.exitCode, child.signalCode);
      maybeClose();
    }
    child.kill = () => {
      if (finished) return false;
      try { native.terminate(worker.id); return true; }
      catch {
        try { process.kill(worker.pid, 'SIGKILL'); return true; }
        catch (error) { if (error.code === 'ESRCH') finish(255, 9); return false; }
      }
    };
    socket.on('close', () => { channelClosed = true; maybeClose(); });
    socket.on('error', error => { child.emit('error', error); });
    child.on('error', () => {});
    const timer = setInterval(() => {
      if (channelLost) {
        try { process.kill(worker.pid, 0); }
        catch (error) { if (error.code === 'ESRCH') finish(255, 9); }
        return;
      }
      try {
        const state = native.status(worker.id);
        if (state) finish(state.exitCode, state.signal);
      } catch (error) {
        channelLost = true; child.kill(); socket.destroy(); child.emit('error', error);
      }
    }, 25);
    return child;
  }
  async function capabilities(child) {
    const id = randomUUID();
    let buffer = '';
    let timer, onData, onError, onExit;
    try {
      return await new Promise((resolve, reject) => {
        onError = error => reject(error);
        onExit = () => reject(new Error('Native Office capability probe exited'));
        onData = text => {
          buffer += text;
          if (buffer.length > 32768) return reject(new Error('Native Office probe response exceeded its limit'));
          let end;
          while ((end = buffer.indexOf('\n')) >= 0) {
            const line = buffer.slice(0, end); buffer = buffer.slice(end + 1);
            if (!line.startsWith('MH_OFFICE_RPC ')) continue;
            let frame;
            try { frame = JSON.parse(line.slice('MH_OFFICE_RPC '.length)); }
            catch { return reject(new Error('Invalid native Office capability response')); }
            if (frame.id !== id) continue;
            if (frame.error) return reject(new Error(frame.error.message));
            if (frame.value?.wasm !== true || frame.value.value !== 42) return reject(new Error('Native Office WebAssembly is unavailable'));
            resolve(frame.value);
          }
        };
        child.stdout.setEncoding('utf8'); child.stdout.on('data', onData);
        child.once('error', onError); child.once('exit', onExit);
        timer = setTimeout(() => reject(new Error('Native Office capability probe timed out')), 5000);
        child.stdin.write(JSON.stringify({ id, method: 'capabilities' }) + '\n');
      });
    } finally {
      clearTimeout(timer);
      child.stdout.removeListener('data', onData);
      child.removeListener('error', onError); child.removeListener('exit', onExit);
    }
  }
  return async () => {
    if (!unsupported) {
      // Broker admission errors propagate; falling back must not bypass its process limit.
      const child = launchNative();
      const started = Date.now();
      try {
        const value = await capabilities(child);
        record('office-native-capability', { pid: child.pid, available: true, elapsedMs: Date.now() - started, ...value });
        return child;
      } catch (error) {
        child.kill(); child.stdin.destroy(); await child.closed;
        unsupported = true;
        record('office-native-capability', { pid: child.pid, available: false, error: String(error.message).slice(0, 500) });
      }
    }
    const child = guest('/bin/node', ['--no-jitless', '--max-old-space-size=512', '/dsh-harmony-office-worker.mjs'], {});
    child.runtime = 'proot'; return child;
  };
}
module.exports = { createOfficeLauncher };

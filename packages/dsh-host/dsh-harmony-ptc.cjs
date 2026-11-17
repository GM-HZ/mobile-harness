'use strict';

const fs = require('node:fs');
const path = require('node:path');
const { Socket } = require('node:net');
const { constants } = require('node:os');
const { PassThrough } = require('node:stream');

function bindPtc(native, mark) {
  const signals = new Map(Object.entries(constants.signals).map(([name, code]) => [code, name]));
  return {
    strip(source) {
      const result = require('./amaro.cjs').transformSync(source, { mode: 'strip-only' });
      if (typeof result?.code !== 'string') throw new Error('Invalid PTC compiler result');
      return result.code;
    },
    launch(cwd, policy, config, signal) {
      signal.throwIfAborted();
      if (policy.mode !== 'read-only' && policy.mode !== 'workspace-write') {
        throw new Error('HarmonyOS PTC requires a workspace file policy');
      }
      const extraRoots = policy.mode === 'workspace-write' ? [...new Set(policy.additionalWritableRoots ?? [])] : [];
      if (extraRoots.length > 16) throw new Error('HarmonyOS PTC supports at most 16 additional writable roots');
      const roots = [policy.workspaceRoot, ...extraRoots];
      if (fs.realpathSync(cwd) !== cwd || roots.some(root => fs.realpathSync(root) !== root || !fs.statSync(root).isDirectory()) ||
          !roots.some(root => {
            const relative = path.relative(root, cwd);
            return relative !== '..' && !relative.startsWith('../') && !path.isAbsolute(relative);
          })) {
        throw new Error('HarmonyOS PTC requires a canonical working directory inside an authorized root');
      }
      const { fd, id } = native.launchPtc(policy.workspaceRoot, policy.mode === 'workspace-write',
        config.maxMessageBytes, config.maxOldGenerationSizeMb, cwd, extraRoots);
      mark('ptc-worker-admitted', { id, mode: policy.mode });
      const control = new Socket({ fd, readable: true, writable: true, allowHalfOpen: true });
      const stdout = new PassThrough();
      const stderr = new PassThrough();
      const completion = Promise.withResolvers();
      let exited = false;
      let stopping = false;
      const timer = setInterval(() => {
        let status;
        try {
          status = native.status(id);
          if (!status) return;
          mark('ptc-worker-reaped', { id, exitCode: status.exitCode, signal: status.signal });
          const signal = signals.get(status.signal) ?? (stopping && status.exitCode === 143 ? 'SIGTERM' : null);
          completion.resolve({
            exitCode: signal ? null : status.exitCode,
            signal,
          });
        } catch (error) {
          completion.reject(error);
        }
        exited = true;
        clearInterval(timer);
        stdout.end();
        stderr.end();
      }, 25);
      return {
        control, stdout, stderr, collected: {}, done: completion.promise,
        terminate() {
          if (exited || stopping) return;
          native.terminate(id);
          stopping = true;
        },
        async waitForExit(bound) {
          if (bound?.aborted) return false;
          const aborted = Promise.withResolvers();
          const onAbort = () => aborted.resolve(false);
          bound?.addEventListener('abort', onAbort, { once: true });
          try { return await Promise.race([completion.promise.then(() => true), aborted.promise]); }
          finally { bound?.removeEventListener('abort', onAbort); }
        },
      };
    },
  };
}

module.exports = { bindPtc };

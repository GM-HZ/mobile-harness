import { writeFile } from 'node:fs/promises';
import { Worker } from 'node:worker_threads';
export const name = 'mh-builtin-binding-probe';
const destination = __MH_PROBE_RESULT__;
function inspectBinding() {
  const module = { exports: {} };
  process.dlopen(module, 'libguest_require_builtin.so');
  const api = module.exports;
  const internals = ['internal/modules/esm/loader', 'internal/modules/cjs/loader', 'internal/modules/helpers', 'internal/modules/esm/utils', 'internal/modules/esm/resolve'];
  return { platform: process.platform, node: process.version, exports: Object.keys(api).sort(),
    info: api.getNativeBindingInfo(), internals: internals.map(id => ({ id, loaded: !!api.requireBuiltin(id) })) };
}
export function apply(ctx) {
  let worker;
  ctx.effect(async () => {
    const result = {};
    try {
      try { result.host = inspectBinding(); }
      catch (error) { result.hostBindingError = { code: error.code, message: error.message }; }
      const body = `const { parentPort } = require('node:worker_threads');
        (async () => {
          const result = {};
          try { result.binding = (${inspectBinding.toString()})(); }
          catch (error) { result.bindingError = { code: error.code, message: error.message }; }
          try {
            const { Session } = require('node:inspector'); const session = new Session();
            session.connectToMainThread();
            try { result.inspector = await new Promise((resolve,reject) => session.post('Runtime.evaluate', { expression: '1 + 41', returnByValue: true }, (error, value) => error ? reject(error) : resolve(value))); }
            finally { session.disconnect(); }
          } catch (error) { result.inspectorError = { code: error.code, message: error.message }; }
          parentPort.postMessage(result);
        })();`;
      worker = new Worker(body, { eval: true, execArgv: [] });
      result.worker = await new Promise((resolve, reject) => {
        const timeout = setTimeout(() => reject(new Error('Worker probe timeout')), 10000);
        worker.once('message', value => { clearTimeout(timeout); resolve(value); });
        worker.once('error', error => { clearTimeout(timeout); reject(error); });
        worker.once('exit', code => { if (code !== 0) { clearTimeout(timeout); reject(new Error('Worker exit ' + code)); } });
      });
    } catch (error) { result.error = { code: error.code, message: error.message }; }
    finally { await worker?.terminate(); await writeFile(destination, JSON.stringify(result)); }
    return () => worker?.terminate();
  });
}

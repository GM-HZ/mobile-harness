import { createInterface } from 'node:readline';

const FRAME = 'MH_OFFICE_RPC ';
const methods = new Set(['render', 'convert', 'recalculate', 'renderImages']);
const active = new Map();
let converter, initialization, closing = false;
function respond(id, value, error) {
  const result = error ? { id, error: { code: error.code ?? 'failed', message: String(error.message ?? error).slice(0, 4096) } } : { id, value };
  process.stdout.write(FRAME + JSON.stringify(result) + '\n');
}
async function execute(frame) {
  const { id, method, request } = frame;
  if (method === 'cancel') { active.get(frame.target)?.abort(new Error('Office operation cancelled')); return; }
  if (typeof id !== 'string') throw new Error('Office request is missing its identity');
  if (method === 'capabilities') {
    const bytes = Buffer.from('0061736d010000000105016000017f0302010007070103666f6f00000a06010400412a0b', 'hex');
    const value = new WebAssembly.Instance(new WebAssembly.Module(bytes)).exports.foo();
    respond(id, { wasm: true, value, platform: process.platform, node: process.version });
    return;
  }
  if (method === 'initialize') {
    if (initialization) throw new Error('Office converter was already initialized');
    const location = new URL(request.engineModule);
    if (location.protocol !== 'file:' || location.search || location.hash ||
        !location.pathname.endsWith('/@deepseek-ai/libreoffice-kit/lib/index.js')) throw new Error('Invalid pinned Office engine module');
    initialization = import(location.href).then(({ createConverter }) => createConverter(request.settings));
    converter = await initialization;
    respond(id, { backend: converter.backend });
    return;
  }
  if (method === 'dispose') {
    closing = true;
    await initialization;
    await converter?.dispose();
    respond(id, null);
    return;
  }
  if (closing || !converter || !methods.has(method)) throw new Error('Invalid Office operation or disposed converter');
  const controller = new AbortController(); active.set(id, controller);
  process.stdout.write(FRAME + JSON.stringify({ id, event: 'running' }) + '\n');
  try { respond(id, await converter[method](request, controller.signal)); }
  finally { active.delete(id); }
}
const input = createInterface({ input: process.stdin });
input.on('line', line => {
  if (line.length > 128 * 1024) { process.stderr.write('Office request exceeded its limit\n'); process.exitCode = 1; input.close(); return; }
  let frame;
  try { frame = JSON.parse(line); }
  catch { process.stderr.write('Invalid Office request\n'); process.exitCode = 1; input.close(); return; }
  void execute(frame).catch(error => respond(frame.id, undefined, error));
});
input.on('close', () => {
  closing = true;
  for (const controller of active.values()) controller.abort();
  void Promise.resolve(initialization).then(() => converter?.dispose()).catch(() => { process.exitCode = 1; });
});

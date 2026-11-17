import { readFile, readdir } from 'node:fs/promises';
import { setTimeout as delay } from 'node:timers/promises';

const packages = __MH_DSH_PACKAGES__;
const workspace = __MH_WORKSPACE__;
const { Context } = await import(packages + 'cordis/lib/index.js');
const { defineTool } = await import(packages + 'dsh-tools/lib/index.js');
const { default: OfficeKit, OfficeSourceKey } = await import(packages + 'dsh-office-kit/lib/index.js');
const bytes = await readFile(new URL('./input.docx', import.meta.url));
const temp = process.env.TMPDIR;
const timeline = temp + '/dsh-native-timeline.log';

export const name = 'mh-office-provider-fixture';
export const inject = ['tools'];

async function trace() {
  return (await readFile(timeline, 'utf8')).split('\n').filter(Boolean).map(row => JSON.parse(row));
}
async function scratch() {
  return (await readdir(temp)).filter(name => name.startsWith('dsh-office-kit-'));
}
export function apply(ctx) {
  const states = new Map();
  ctx.effect(() => async () => {
    await Promise.all([...states.values()].map(state => state.owner.fiber.dispose()));
    states.clear();
  });
  async function describe(state) {
    const started = (await trace()).filter(row => row.event === 'office-worker-started' && !state.beforeWorkers.has(row.id));
    if (!state.worker && started.length === 1) state.worker = started[0];
    return {
      status: state.status, closed: state.closed, code: state.code ?? '',
      bytes: state.bytes ?? 0, elapsedMs: state.elapsedMs ?? 0,
      workerId: state.worker?.id ?? '', workerPid: state.worker?.pid ?? 0,
      postDisposeRejected: state.postDisposeRejected ?? false,
      remainingScratch: (await scratch()).filter(name => !state.beforeScratch.has(name)).length,
    };
  }
  ctx.tools.register(defineTool({
    name: 'mh_office_provider',
    description: 'Exercise fixture-owned real Office provider lifetime and failure recovery.',
    parameters: {
      action: { type: 'string', required: true, enum: ['create', 'cancel', 'status', 'dispose', 'crash', 'retry'] },
      case: { type: 'string', required: true, enum: ['idle', 'active', 'cancel', 'timeout', 'crash'] },
    },
    output: {
      schema: {
        type: 'object', additionalProperties: false,
        properties: {
          status: { type: 'string', required: true }, closed: { type: 'boolean', required: true },
          code: { type: 'string', required: true }, bytes: { type: 'integer', required: true },
          elapsedMs: { type: 'number', required: true }, workerId: { type: 'string', required: true },
          workerPid: { type: 'integer', required: true }, postDisposeRejected: { type: 'boolean', required: true },
          remainingScratch: { type: 'integer', required: true },
        },
      },
      render(_args, result) { return [{ type: 'text', text: JSON.stringify(result) }]; },
    },
    async execute(args) {
      let state = states.get(args.case);
      if (args.action === 'create') {
        if (state) throw new Error('This fixture already owns the requested provider');
        const owner = new Context();
        state = { owner, status: 'pending', closed: false,
          beforeWorkers: new Set((await trace()).filter(row => row.event === 'office-worker-started').map(row => row.id)),
          beforeScratch: new Set(await scratch()), controller: new AbortController() };
        states.set(args.case, state);
        await owner.plugin(OfficeKit, { outputDirectory: workspace + '/outputs/' + args.case,
          fontDirectories: ['/system/fonts'], timeoutMs: args.case === 'timeout' ? 100 : 180000 });
        state.provider = owner.officeKit;
        state.source = { key: OfficeSourceKey('provider-' + args.case), version: 'v1', bytes: bytes.length,
          async read(signal, maximum) {
            signal.throwIfAborted();
            if (bytes.length > maximum) throw new Error('Fixture exceeds source reservation');
            return { bytes: Uint8Array.from(bytes), version: 'v1' };
          } };
        state.request = { extension: 'docx', priority: 'foreground', source: state.source };
        state.pending = state.provider.convert(state.request, state.controller.signal).then(result => {
          if (Buffer.from(result.pdf).subarray(0, 5).toString() !== '%PDF-') throw new Error('Provider returned invalid PDF');
          state.bytes = result.pdf.length; state.status = 'completed';
        }).catch(error => { state.status = 'error'; state.code = error.code ?? error.name; });
        if (['idle', 'timeout', 'crash'].includes(args.case)) await state.pending;
      }
      if (!state) throw new Error('No fixture-owned provider for this case');
      if (args.action === 'cancel') {
        const start = Date.now();
        state.controller.abort(new Error('Fixture cancelled this reader'));
        await state.pending;
        state.elapsedMs = Date.now() - start;
      }
      if (args.action === 'crash') {
        await describe(state);
        if (!state.worker || state.worker.pid <= 0) throw new Error('Missing fixture-owned process identity');
        process.kill(-state.worker.pid, 'SIGKILL');
        await delay(100);
      }
      if (args.action === 'retry') {
        state.status = 'pending'; state.code = '';
        state.pending = state.provider.convertTo({ extension: 'docx', format: 'txt', source: state.source,
          output: { owner: 'fixture', name: 'retry.txt' } }).then(async result => {
          const text = await readFile(result.path, 'utf8');
          if (!text.includes('HARMONY_OFFICE_')) throw new Error('Retry lost the input document text');
          state.bytes = result.bytes; state.status = 'completed';
        }).catch(error => { state.status = 'error'; state.code = error.code ?? error.name; });
        await state.pending;
      }
      if (args.action === 'dispose') {
        const start = Date.now();
        await state.owner.fiber.dispose();
        await state.pending;
        state.closed = true; state.elapsedMs = Date.now() - start;
        try { await state.provider.convert(state.request); }
        catch { state.postDisposeRejected = true; }
      }
      return describe(state);
    },
  }));
}

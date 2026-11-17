// Observe genuine provider output before interrupting only an owned test call.
import { readFile, writeFile } from 'node:fs/promises';
const directory = __MH_WORKSPACE__;
export const name = 'mh-compaction-stream-fault';
export const inject = ['llm'];

export function apply(ctx) {
  ctx.on('llm/stream', (options, next) => (async function* () {
    let control;
    try { control = JSON.parse(await readFile(directory + '/control.json', 'utf8')); }
    catch (error) { if (error.code !== 'ENOENT') throw error; }
    if (options.purpose !== 'compaction' || options.sessionId !== control?.sessionId) {
      yield* next(); return;
    }
    for await (const chunk of next()) {
      if (chunk.type === 'text-delta' && chunk.text.length > 0) {
        await writeFile(directory + '/' + control.action + '-observed.json', JSON.stringify({
          sessionId: options.sessionId, purpose: options.purpose, provider: options.provider,
          model: options.model, chunkType: chunk.type, realTextCharacters: chunk.text.length,
        }));
        if (control.action === 'failure') throw new Error('OWNED_COMPACTION_STREAM_FAILURE');
        if (control.action === 'cancel') {
          await new Promise((_resolve, reject) => {
            const abort = () => reject(options.signal.reason ?? new Error('Owned request aborted'));
            if (options.signal.aborted) abort();
            else options.signal.addEventListener('abort', abort, { once: true });
          });
        }
      }
      yield chunk;
    }
  })());
}

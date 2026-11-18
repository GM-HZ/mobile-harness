export const name = 'mh-auto-review-response-fixture';
export const inject = ['llm'];

export function apply(ctx) {
  ctx.on('llm/stream', async function* (options, next) {
    if (!options.system?.startsWith('REVIEW_POLICY\n')) {
      yield* next();
      return;
    }
    const pending = options.messages.at(-1)?.content.find(block => block.type === 'text')?.text ?? '';
    const malformed = pending.includes('malformed.txt');
    const reject = pending.includes('rejected.txt') || pending.includes('cancelled.txt');
    const text = malformed ? '{"risk":"low","decision":"deny"}' : reject
      ? '{"risk":"medium","decision":"deny","reason":"Owned fixture requires confirmation."}'
      : '{"risk":"low","decision":"allow"}';
    yield { type: 'block-start', index: 0, blockType: 'text' };
    yield { type: 'text-delta', index: 0, text };
    yield { type: 'block-end', index: 0, block: { type: 'text', text } };
    yield { type: 'finish', reason: { kind: 'stop' } };
  }, { prepend: true });
}

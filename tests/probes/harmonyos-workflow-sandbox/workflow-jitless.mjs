import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { stripTypeScriptTypes } from 'node:module';

assert.equal(typeof WebAssembly, 'undefined', 'run this probe with Node --jitless');
const sourceRoot = new URL('../../../vendor/repos/dsh/packages/workflow/workflow-ptc/src/', import.meta.url);
const guestSource = readFileSync(new URL('guest-source.ts', sourceRoot), 'utf8')
  .match(/^export const WORKFLOW_GUEST_SOURCE = (.+)$/m);
const hostSource = readFileSync(new URL('host.ts', sourceRoot), 'utf8');
assert.ok(guestSource, 'expected the checked-in RC.3 guest bundle');
assert.ok(hostSource.includes(
  'const PROGRAM = `const { runWorkflowGuest } = await import(${JSON.stringify(GUEST_URL)}); return await runWorkflowGuest(workflowHost);`',
), 'update this probe if the upstream workflow wrapper changes');
const guestUrl = `data:text/javascript,${encodeURIComponent(JSON.parse(guestSource[1]))}`;
const program = `const { runWorkflowGuest } = await import(${JSON.stringify(guestUrl)}); return await runWorkflowGuest(workflowHost);`;
assert.throws(
  () => stripTypeScriptTypes(`async function probe() { ${program} }`),
  { code: 'ERR_WEBASSEMBLY_NOT_SUPPORTED' },
);

const prompts = [];
const disposed = [];
const events = [];
const host = {
  async begin() {
    return {
      meta: { name: 'jitless-workflow-probe', description: 'test fixed JavaScript and mock child bindings' },
      body: "phase('Probe'); return await parallel([() => agent('one'), () => agent('two')]);",
      args: {},
      limits: { maxConcurrentAgents: 2, maxTotalAgents: 2, maxItemsPerCall: 2, syncTimeoutMs: 5000 },
    };
  },
  async startChild({ prompt }) {
    prompts.push(prompt);
    return { callId: prompts.length, childId: `fixture-${prompts.length}` };
  },
  async childResult({ callId }) {
    return { output: [{ type: 'text', text: prompts[callId - 1] }], stopReason: 'completed' };
  },
  async disposeChild({ callId }) {
    disposed.push(callId);
    return null;
  },
  async progress(batch) {
    events.push(...batch);
    return null;
  },
};

// Fixed, trusted upstream wrapper and fixed fixture body only. This probe supplies no isolation.
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
const result = await new AsyncFunction('workflowHost', program)(host);
assert.deepEqual(result, { value: ['one', 'two'], stopReason: 'completed', agentsStarted: 2 });
assert.deepEqual(disposed.sort(), [1, 2]);
assert.deepEqual(events.map(({ type }) => type).sort(), [
  'agent-end', 'agent-end', 'agent-start', 'agent-start', 'phase',
]);
console.log(JSON.stringify({
  node: process.version,
  jitless: true,
  stripError: 'ERR_WEBASSEMBLY_NOT_SUPPORTED',
  wrapper: 'function-body',
  result,
  disposed,
}));

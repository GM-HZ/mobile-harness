'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const { stripTypeScriptTypes } = require('node:module');
const { constants } = require('node:os');
const { performance } = require('node:perf_hooks');
const vm = require('node:vm');
const addon = { exports: {} };
process.dlopen(addon, 'libworkflownode.so');

async function run() {
  const guestUrl = PACKAGED_WORKFLOW_GUEST_URL;
  await import(guestUrl);
  const program = `const { runWorkflowGuest } = await import(${JSON.stringify(guestUrl)}); return await runWorkflowGuest(workflowHost);`;
  assert.throws(() => stripTypeScriptTypes(`async function probe() { ${program} }`),
    { code: 'ERR_WEBASSEMBLY_NOT_SUPPORTED' });
  const start = performance.now();
  const amaro = PACKAGED_AMARO_PROBE_ENABLED ? {
    compile: require('./amaro.cjs').transformSync,
    baseline: require('./reference.json'),
    verify: require('./verify.cjs').verify,
  } : undefined;
  const compilerLoadMs = Math.round(performance.now() - start);
  const inherited = fs.openSync(__filename, 'r');
  assert.equal(addon.exports.socketErrno(), 0);
  const errno = addon.exports.confine();
  if (errno !== 0) throw new Error('seccomp errno=' + errno);

  assert.throws(() => fs.openSync(__filename, 'r'), { code: 'EPERM' });
  assert.throws(() => fs.readSync(inherited, Buffer.alloc(1)), { code: 'EPERM' });
  assert.throws(() => fs.writeSync(2, 'denied'), { code: 'EPERM' });
  assert.equal(addon.exports.socketErrno(), constants.errno.EPERM);
  const typescript = amaro && {
    ...amaro.verify(amaro.compile, amaro.baseline), loadMs: compilerLoadMs,
  };
  if (amaro) {
    const program = 'async function __dsh_program__() {\nconst value: number = await Promise.resolve(6); return value * 7;\n}';
    const { code } = amaro.compile(program, { mode: 'strip-only' });
    typescript.typedResult = await new vm.Script(code + '\n__dsh_program__();').runInNewContext();
    assert.equal(typescript.typedResult, 42);
  }

  fs.writeSync(1, '+');
  const input = Buffer.alloc(512);
  let used = 0;
  while (used < input.length) {
    assert.equal(addon.exports.waitInput(), 0, 'waiting for fixture input');
    const count = fs.readSync(0, input, used, input.length - used, null);
    if (count === 0) break;
    used += count;
  }
  assert.ok(used > 0 && used < input.length);
  const body = input.toString('utf8', 0, used);
  const prompts = [];
  const disposed = [];
  const progress = [];
  const host = {
    async begin() {
      return {
        meta: { name: 'harmony-workflow-probe', description: 'run upstream workflow under a seccomp filter' },
        body,
        args: {},
        limits: { maxConcurrentAgents: 2, maxTotalAgents: 2, maxItemsPerCall: 2, syncTimeoutMs: 1500 },
      };
    },
    async progress(events) {
      progress.push(...events.map(({ type }) => type));
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
    },
  };
  // Node's VM timeout starts a libuv loop and thread. The supervisor owns the deadline
  // in this isolated test process. The marker proves the spinning fixture reached the VM.
  const runInContext = vm.Script.prototype.runInContext;
  vm.Script.prototype.runInContext = function (context, { timeout, ...options }) {
    assert.equal(timeout, 1500);
    fs.writeSync(1, '!');
    return runInContext.call(this, context, options);
  };
  const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
  const result = await new AsyncFunction('workflowHost', program)(host);
  assert.deepEqual(result, { value: ['one', 'two'], agentsStarted: 2, stopReason: 'completed' });
  assert.deepEqual(disposed.sort(), [1, 2]);
  assert.deepEqual(progress.sort(), ['agent-end', 'agent-end', 'agent-start', 'agent-start', 'phase']);
  fs.writeSync(1, JSON.stringify({
    node: process.version, platform: process.platform, pid: process.pid,
    nativeSeccomp: true, vmTimeoutDelegated: true, filesystemDenied: true,
    fdReadDenied: true, fdWriteDenied: true, socketDenied: true,
    result, disposed, typescript,
  }));
  addon.exports.finish();
}

run().catch(error => {
  fs.writeSync(1, 'error: ' + error.stack);
  addon.exports.finish();
});

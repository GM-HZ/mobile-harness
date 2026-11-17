import assert from 'node:assert/strict';
import { once } from 'node:events';
import { readFile, rm } from 'node:fs/promises';
const packages = __MH_DSH_PACKAGES__;
const root = __MH_ROOT__;
const cwd = __MH_WORKSPACE__;
const { Context } = await import(packages + 'cordis/lib/index.js');
const { defineTool } = await import(packages + 'dsh-tools/lib/index.js');
const { default: Provider } = await import('file://' + root + '/dsh-harmony-subprocess.mjs');
export const name = 'mh-subprocess-provider-fixture';
export const inject = ['tools'];

async function run() {
  const owner = new Context();
  await owner.plugin(Provider);
  const provider = owner.subprocess;
  const result = {};
  const collect = { stdin: 'ignore', stdout: { maxBytes: 32768 }, stderr: { maxBytes: 4096 } };
  const spawn = (argv, stdio = collect, extra = {}) => provider.spawn({ argv, cwd, graceMs: 150, stdio, ...extra });
  const settle = async child => {
    const outcome = await child.done;
    assert.equal(await child.waitForExit(), true);
    return outcome;
  };
  try {
    const node = await provider.resolveExecutable('node');
    const git = await provider.resolveExecutable('git');
    assert.equal(node, root + '/bin/node'); assert.equal(git, root + '/usr/bin/git');
    await assert.rejects(provider.resolveExecutable('mh-does-not-exist-acceptance'), { code: 'SUBPROCESS_EXECUTABLE_NOT_FOUND' });
    await assert.rejects(provider.resolveExecutable('./relative-node'), /absolute executable/);
    result.executionWorldLookup = { node, git, missingRejected: true, relativeRejected: true };
    const literal = "literal'\";$(touch NEVER)\n中文";
    const child = spawn([node, '-e', `let s='';process.stdin.setEncoding('utf8');process.stdin.on('data',x=>s+=x);process.stdin.on('end',()=>{process.stdout.write(JSON.stringify({cwd:process.cwd(),args:process.argv.slice(1),stdin:s}));process.stderr.write('STDERR_MARKER')});`, '--', literal],
      { stdin: 'pipe', stdout: 'pipe', stderr: { maxBytes: 4096 } });
    const chunks = [];
    const reading = (async () => { for await (const chunk of child.stdout) chunks.push(chunk); })();
    child.stdin.end('two chunks\n汉字');
    assert.deepEqual(await settle(child), { exitCode: 0, signal: null });
    await reading;
    assert.deepEqual(JSON.parse(Buffer.concat(chunks)), { cwd, args: [literal], stdin: 'two chunks\n汉字' });
    assert.match(child.collected.stderr.readFrom(0).text, /STDERR_MARKER/);
    result.literalArgvNativeCwdStreamingAndEof = true;
    // Only fake ambient values are installed; real credentials are never read.
    const fake = { MH_PARENT_SECRET: 'ambient-fake-secret', DSH_FAKE_IDENTITY: 'ambient-fake-id', MH_AMBIENT: 'remove-me' };
    const saved = Object.fromEntries(Object.keys(fake).map(key => [key, process.env[key]]));
    Object.assign(process.env, fake);
    try {
      const envChild = spawn([node, '-e', 'process.stdout.write(JSON.stringify({secret:process.env.MH_PARENT_SECRET??null,dsh:process.env.DSH_FAKE_IDENTITY??null,ambient:process.env.MH_AMBIENT??null,token:process.env.MH_TOKEN??null}))'], collect,
        { env: { MH_AMBIENT: undefined, MH_TOKEN: 'deliberately-configured' } });
      assert.equal((await settle(envChild)).exitCode, 0);
      assert.deepEqual(JSON.parse(envChild.collected.stdout.readFrom(0).text), { secret: null, dsh: null, ambient: null, token: 'deliberately-configured' });
      result.upstreamAmbientScrubExplicitEnvAndTombstone = true;
    } finally {
      for (const [key, value] of Object.entries(saved)) {
        if (value === undefined) delete process.env[key]; else process.env[key] = value;
      }
    }
    const output = '0123456789'.repeat(1000) + 'END';
    const spilling = spawn([node, '-e', 'process.stdout.write("0123456789".repeat(1000)+"END");process.exitCode=37'],
      { stdin: 'ignore', stdout: { maxBytes: 64, spill: { maxBytes: 20000 } }, stderr: { maxBytes: 4096 } });
    assert.deepEqual(await settle(spilling), { exitCode: 37, signal: null });
    const tail = spilling.collected.stdout.readFrom(0);
    assert.equal(tail.lossy, true); assert.equal(tail.nextOffset, Buffer.byteLength(output));
    assert.equal(tail.text, output.slice(-64)); assert.ok(tail.spillPath);
    assert.equal(await readFile(tail.spillPath, 'utf8'), output); await rm(tail.spillPath);
    result.nonzeroExitBoundedTailFullSpill = true;
    for (const action of ['abort', 'dispose']) {
      const controller = new AbortController();
      const active = spawn([node, '-e', 'process.stdout.write("ACTUALLY_RUNNING");setInterval(()=>{},1000)'],
        { stdin: 'ignore', stdout: 'pipe', stderr: { maxBytes: 4096 } }, { signal: controller.signal });
      const [ready] = await once(active.stdout, 'data', { signal: AbortSignal.timeout(15000) });
      assert.equal(ready.toString(), 'ACTUALLY_RUNNING');
      const started = Date.now();
      if (action === 'abort') controller.abort(new Error('Owned active subprocess cancellation'));
      else await owner.fiber.dispose();
      const outcome = await settle(active);
      assert.ok(outcome.signal === 'SIGTERM' || outcome.signal === 'SIGKILL', JSON.stringify(outcome));
      assert.ok(Date.now() - started < 5000);
      result[action] = { actualRunningObserved: true, managedRangeExited: true, elapsedMs: Date.now() - started, outcome };
    }
    return result;
  } finally { await owner.fiber.dispose(); }
}

export function apply(ctx) {
  ctx.tools.register(defineTool({
    name: 'mh_subprocess_contract', description: 'Run owned real Alpine subprocess streaming and lifecycle acceptance.',
    parameters: {},
    output: { schema: { type: 'object', additionalProperties: true, properties: {} },
      render(_args, result) { return [{ type: 'text', text: JSON.stringify(result) }]; } },
    async execute() { return await run(); },
  }));
}

import assert from 'node:assert/strict';
import { readFile, writeFile } from 'node:fs/promises';
const packages = __MH_DSH_PACKAGES__;
const root = __MH_ROOT__;
const cwd = __MH_WORKSPACE__;
const { Context } = await import(packages + 'cordis/lib/index.js');
const { defineTool } = await import(packages + 'dsh-tools/lib/index.js');
const { Lsp } = await import(packages + 'dsh-lsp/lib/index.js');
const LspStdio = await import(packages + 'dsh-lsp-stdio/lib/index.js');
const { default: FileSystem } = await import(packages + 'dsh-fs-local/lib/index.js');
const { default: Subprocess } = await import('file://' + root + '/dsh-harmony-subprocess.mjs');
export const name = 'mh-lsp-lifecycle-fixture';
export const inject = ['tools'];

async function run(action) {
  const owner = new Context();
  const marker = cwd + '/' + action + '-held.json';
  const controller = new AbortController();
  const source = 'export function twice(value: number): number { return value * 2; }\nexport const answer = twice(21);\n';
  const query = { operation: 'hover', workspaceRoot: cwd, filePath: 'a.ts', position: { line: 1, character: 24 } };
  const result = {};
  try {
    await writeFile(cwd + '/a.ts', source);
    await writeFile(cwd + '/tsconfig.json', JSON.stringify({ compilerOptions: { strict: true, types: [] }, files: ['a.ts'] }));
    await owner.plugin(Lsp);
    await owner.plugin(FileSystem, { cwd });
    await owner.plugin(Subprocess);
    const fiber = await owner.plugin(LspStdio, { servers: { typescript: {
      command: 'node', args: [cwd + '/relay.cjs', root + '/.dsh-0.2.2-rc.5/dsh/node_modules/typescript-language-server/lib/cli.mjs', marker],
      extensionToLanguage: { '.ts': 'typescript' }, shutdownTimeoutMs: 250, killGraceMs: 250,
      initializationOptions: { disableAutomaticTypingAcquisition: true, maxTsServerMemory: 384,
        tsserver: { path: root + '/.dsh-0.2.2-rc.5/toolchains/lsp/node_modules/typescript/lib/tsserver.js', useSyntaxServer: 'never' } },
    } } });
    const pending = owner.lsp.query(query, controller.signal).then(value => ({ value }), error => ({ error }));
    const deadline = Date.now() + 30000;
    let held;
    while (!held && Date.now() < deadline) {
      try { held = JSON.parse(await readFile(marker, 'utf8')); }
      catch (error) { if (error.code !== 'ENOENT') throw error; }
      if (!held) await new Promise(resolve => setTimeout(resolve, 50));
    }
    assert.ok(held, 'real language server must answer before cancellation/disposal');
    assert.match(JSON.stringify(held.realReply.result), /twice/);
    assert.match(JSON.stringify(held.realReply.result), /number/);
    result.realSemanticReplyHeld = held;
    const start = Date.now();
    if (action === 'cancel') controller.abort(new Error('Owned LSP query cancellation'));
    else await fiber.dispose();
    const outcome = await pending;
    assert.ok(outcome.error, 'pending query must reject');
    result.rejected = { name: outcome.error.name, message: outcome.error.message,
      ...(outcome.error.code === undefined ? {} : { code: outcome.error.code }) };
    result.settleMs = Date.now() - start;
    assert.ok(result.settleMs < 8000);
    if (action === 'cancel') {
      const retry = await owner.lsp.query(query, AbortSignal.timeout(25000));
      assert.equal(retry.kind, 'hover'); assert.match(retry.hover.contents, /twice/); assert.match(retry.hover.contents, /number/);
      result.retryRealHover = retry;
      await fiber.dispose();
    } else {
      await assert.rejects(owner.lsp.query(query), { code: 'LSP_UNAVAILABLE' });
      result.routeUnregistered = true;
    }
    return result;
  } finally { await owner.fiber.dispose(); }
}

export function apply(ctx) {
  ctx.tools.register(defineTool({
    name: 'mh_lsp_lifecycle', description: 'Verify actual language-server cancellation and provider disposal on owned fixtures.',
    parameters: { action: { type: 'string', required: true, enum: ['cancel', 'dispose'] } },
    output: { schema: { type: 'object', additionalProperties: true, properties: {} },
      render(_args, value) { return [{ type: 'text', text: JSON.stringify(value) }]; } },
    async execute(args) { return await run(args.action); },
  }));
}

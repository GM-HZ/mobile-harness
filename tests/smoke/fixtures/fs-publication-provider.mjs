import assert from 'node:assert/strict';
import { readFile, readdir, writeFile } from 'node:fs/promises';
const packages = __MH_DSH_PACKAGES__;
const cwd = __MH_WORKSPACE__;
const { defineTool } = await import(packages + 'dsh-tools/lib/index.js');
export const name = 'mh-fs-publication-fixture';
export const inject = ['tools', 'fs'];

export function apply(ctx) {
  ctx.tools.register(defineTool({
    name: 'mh_fs_publication', description: 'Verify owned real atomic no-replace publication and guarded failure boundaries.',
    parameters: {}, output: { schema: { type: 'object', additionalProperties: true, properties: {} },
      render(_args, result) { return [{ type: 'text', text: JSON.stringify(result) }]; } },
    async execute() {
      const fs = ctx.fs;
      assert.equal(fs.sandboxMode, 'workspace-write');
      assert.equal(typeof fs.internals.linkFile, 'function');
      const policy = { mode: 'workspace-write', workspaceRoot: cwd };
      const original = fs.internals.inspectTemp;
      const result = { provider: fs.constructor.name, publicPublicationBoundaryInstalled: true };
      const create = async (file, content, signal) => fs.writeText(await fs.resolve(cwd + '/' + file), content,
        { kind: 'createIfAbsent' }, signal, policy);
      try {
        const content = '完整 🧭\n';
        await create('new.txt', content);
        assert.equal(await readFile(cwd + '/new.txt', 'utf8'), content);
        await assert.rejects(create('new.txt', 'MUST_NOT_OVERWRITE'), { code: 'FS_NOT_OBSERVED' });
        assert.equal(await readFile(cwd + '/new.txt', 'utf8'), content);
        result.createAndExistingDestinationNoOverwrite = true;
        let raced = false;
        fs.internals.inspectTemp = async paths => {
          await original?.(paths);
          if (paths.tempPath.endsWith('/raced.txt.tmp')) {
            await writeFile(cwd + '/raced.txt', 'COMPETITOR_WON', { flag: 'wx' });
            raced = true;
          }
        };
        await assert.rejects(create('raced.txt', 'MUST_NOT_OVERWRITE_COMPETITOR'), { code: 'FS_NOT_OBSERVED' });
        assert.equal(raced, true);
        assert.equal(await readFile(cwd + '/raced.txt', 'utf8'), 'COMPETITOR_WON');
        result.actualCompetitorCreatedAfterStagingPreserved = true;
        const controller = new AbortController(); let staged = false;
        fs.internals.inspectTemp = async paths => {
          await original?.(paths);
          if (paths.tempPath.endsWith('/cancelled.txt.tmp')) { staged = true; controller.abort(); }
        };
        await assert.rejects(create('cancelled.txt', 'MUST_NOT_PUBLISH', controller.signal), { code: 'FS_ABORTED' });
        assert.equal(staged, true);
        await assert.rejects(readFile(cwd + '/cancelled.txt'), { code: 'ENOENT' });
        result.cancelAfterRealStagingPublishedNothing = true;
        assert.equal((await readdir(cwd)).some(name => name.startsWith('.') && name.endsWith('.tmpdir')), false);
        result.privateStagingCleanedAfterSuccessCollisionAndAbort = true;
        return result;
      } finally {
        if (original === undefined) delete fs.internals.inspectTemp;
        else fs.internals.inspectTemp = original;
      }
    },
  }));
}

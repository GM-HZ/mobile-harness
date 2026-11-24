'use strict';
const fs = require('node:fs/promises');
const path = require('node:path');

function inside(root, target) {
  const relative = path.relative(root, target);
  if (relative === '..' || relative.startsWith('../') || path.isAbsolute(relative)) {
    throw new Error('Search path must be within the local workspace');
  }
}

function createWorkspaceSearch(workspace, loadAddon) {
  let addon;
  return async (workdir, signal, tool, argv, cap, SearchError) => {
    try {
      signal.throwIfAborted();
      const separator = argv.indexOf('--');
      const flags = argv.slice(1, separator < 0 ? undefined : separator);
      const filterFlag = flags.find(flag => flag.startsWith('--glob=') && !flag.startsWith('--glob=!'));
      const globFlags = flags.filter(flag => flag.startsWith('--glob='));
      // Glob can include an initial pruning pair before its actual pattern.
      const filter = tool === 'glob' ? globFlags[globFlags[0] === '--glob=!**' ? 2 : 0]?.slice(7)
        : filterFlag?.slice(7);
      const pattern = flags.find(flag => flag.startsWith('--regexp='))?.slice(9);
      const root = await fs.realpath(workspace);
      const cwd = await fs.realpath(workdir);
      const requested = path.resolve(cwd, separator < 0 ? '.' : argv[separator + 1]);
      inside(root, cwd);
      inside(root, requested);
      const target = await fs.realpath(requested);
      inside(root, target);
      signal.throwIfAborted();
      addon ??= loadAddon();
      const cancelled = Buffer.alloc(1);
      const abort = () => addon.cancel(cancelled);
      signal.addEventListener('abort', abort, { once: true });
      try {
        const request = Buffer.from(JSON.stringify({ tool, workdir: cwd, target, pattern, filter, cap }));
        const result = JSON.parse(await addon.run(request, cancelled));
        signal.throwIfAborted();
        if (result.error) throw new SearchError(result.message, result.error);
        return { stdout: result.stdout, noMatches: result.stdout.length === 0, workdir: cwd };
      } finally {
        signal.removeEventListener('abort', abort);
      }
    } catch (error) {
      if (signal.aborted) throw new SearchError(tool + ' search was cancelled', 'SEARCH_ABORTED');
      if (error instanceof SearchError) throw error;
      throw new SearchError(tool + ' could not search this workspace path: ' + error.message,
        'SEARCH_FAILED', { cause: error });
    }
  };
}

module.exports = { createWorkspaceSearch };

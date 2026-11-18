import { existsSync } from 'node:fs';
import path from 'node:path';

export const name = 'mh-worktree-restore-gate';
export const inject = ['subprocess'];
const repository = __MH_REPOSITORY__;
const checkoutPool = path.join(repository, '.agents/worktrees') + '/';
const guestBash = __MH_GUEST_BASH__;

export function apply(ctx) {
  const runtime = ctx.subprocess;
  const spawn = runtime.spawn;
  runtime.spawn = function (spec) {
    if (!existsSync(path.join(repository, 'hold-reset')) ||
        !spec.cwd?.startsWith(checkoutPool) ||
        !spec.argv.includes('reset') || spec.argv.at(-1) !== 'HEAD') {
      return spawn.call(this, spec);
    }
    // Keep the real provider and its abort signal. Delay only the fixture's
    // final Git command, after real worktree add created its registration.
    return spawn.call(this, {
      ...spec,
      argv: [guestBash, '-c',
        'printf READY > "$1"; shift; sleep 45; exec "$@"',
        'worktree-restore-gate', path.join(repository, 'reset-started'), ...spec.argv],
    });
  };
  ctx.effect(() => () => { runtime.spawn = spawn; });
}

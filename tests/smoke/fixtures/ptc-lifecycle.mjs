import { randomUUID } from 'node:crypto';

const packages = __MH_DSH_PACKAGES__;
const workspace = __MH_WORKSPACE__;
const { defineTool } = await import(packages + 'dsh-tools/lib/index.js');
const { installModelSelection } = await import(packages + 'dsh-agent/lib/index.js');

export const name = 'mh-ptc-lifecycle-fixture';
export const inject = ['tools', 'agents', 'sessions', 'agentPresets'];

export function apply(ctx) {
  const handles = new Map();
  ctx.effect(() => async () => {
    const results = await Promise.allSettled([...handles.values()].map(async pending => (await pending).dispose()));
    handles.clear();
    const failed = results.find(result => result.status === 'rejected');
    if (failed) throw failed.reason;
  });
  ctx.tools.register(defineTool({
    name: 'mh_ptc_lifecycle',
    description: 'Own and dispose isolated PTC regression Agents. Each case has an independent handle.',
    parameters: {
      action: { type: 'string', required: true, enum: ['create', 'dispose'] },
      case: { type: 'string', required: true, enum: ['idle', 'active'] },
    },
    output: {
      schema: {
        type: 'object', additionalProperties: false,
        properties: {
          sessionId: { type: 'string', required: true },
          disposed: { type: 'boolean', required: true },
          agentRegistered: { type: 'boolean', required: true },
          sessionRegistered: { type: 'boolean', required: true },
          disposeMs: { type: 'number', required: true },
        },
      },
      render(_args, value) { return [{ type: 'text', text: JSON.stringify(value) }]; },
    },
    async execute(args) {
      if (args.action === 'create' && !handles.has(args.case)) {
        const pending = ctx.agents.create({
          sessionId: 'session-' + randomUUID(),
          agentOptions: { provider: 'deepseek-official', model: 'deepseek-flash', reasoningEffort: 'off' },
          meta: { cwd: workspace, agentPreset: 'ptc' },
          setup: async agentCtx => {
            installModelSelection(agentCtx);
            await ctx.agentPresets.mount(agentCtx, 'ptc');
          },
        });
        handles.set(args.case, pending);
        pending.catch(() => { if (handles.get(args.case) === pending) handles.delete(args.case); });
      }
      const pending = handles.get(args.case);
      if (!pending) throw new Error('No fixture-owned Agent for this case');
      const handle = await pending;
      const sessionId = handle.agent.id;
      const started = Date.now();
      if (args.action === 'dispose') {
        await handle.dispose();
        handles.delete(args.case);
      }
      return {
        sessionId, disposed: args.action === 'dispose',
        agentRegistered: ctx.agents.get(sessionId) !== undefined,
        sessionRegistered: ctx.sessions.get(sessionId) !== undefined,
        disposeMs: args.action === 'dispose' ? Date.now() - started : 0,
      };
    },
  }));
}

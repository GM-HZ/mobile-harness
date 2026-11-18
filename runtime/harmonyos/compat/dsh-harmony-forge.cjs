'use strict';
const fs = require('node:fs');
const path = require('node:path');

function createGhRunner(launch, quote) {
  return async (command, args, options) => {
    if (!['gh', '/usr/bin/gh'].includes(command)) {
      return { shortMessage: 'Harmony Forge requires the packaged GitHub CLI' };
    }
    const signal = options.cancelSignal;
    if (signal.aborted) return { isCanceled: true };
    // Match the CLI's private credential store. The selected workspace and its
    // environment cannot redirect authentication or resolve another executable.
    const environment = [
      'HOME=/native-benchmark-home', 'GH_CONFIG_DIR=/native-benchmark-home/.config/gh',
      'GH_PROMPT_DISABLED=1', 'GH_NO_UPDATE_NOTIFIER=1', 'GH_PAGER=', 'NO_COLOR=1', 'CLICOLOR=0',
      ...['HTTP_PROXY', 'HTTPS_PROXY', 'NO_PROXY', 'http_proxy', 'https_proxy', 'no_proxy']
        .filter(name => typeof options.env[name] === 'string').map(name => name + '=' + options.env[name]),
    ];
    let child;
    try {
      child = launch('/', 'exec /usr/bin/gh ' + args.map(quote).join(' '), environment);
    } catch (error) {
      return { shortMessage: 'Harmony gh launch failed: ' + (error.code ?? error.name) };
    }
    return await new Promise(resolve => {
      const outputs = { stdout: [], stderr: [] };
      const sizes = { stdout: 0, stderr: 0 };
      let timedOut = false;
      let isMaxBuffer = false;
      let killTimer;
      let launchError;
      const terminate = () => {
        if (killTimer || child.exitCode !== null || child.signalCode !== null) return;
        child.kill('SIGTERM');
        killTimer = setTimeout(() => child.kill('SIGKILL'), 1000);
      };
      const timeout = setTimeout(() => { timedOut = true; terminate(); }, options.timeout);
      signal.addEventListener('abort', terminate, { once: true });
      for (const stream of ['stdout', 'stderr']) {
        child[stream].on('data', chunk => {
          sizes[stream] += chunk.length;
          if (sizes[stream] > options.maxBuffer) {
            isMaxBuffer = true;
            terminate();
          } else {
            outputs[stream].push(chunk);
            options.onOutput?.(chunk);
          }
        });
        child[stream].on('error', error => { launchError ??= error; });
      }
      child.on('error', error => { launchError ??= error; });
      child.once('close', code => {
        clearTimeout(timeout);
        clearTimeout(killTimer);
        signal.removeEventListener('abort', terminate);
        resolve({
          exitCode: Number.isInteger(code) ? code : undefined,
          stdout: Buffer.concat(outputs.stdout).toString().replace(/\r?\n$/, ''),
          stderr: Buffer.concat(outputs.stderr).toString().replace(/\r?\n$/, ''),
          isCanceled: signal.aborted, timedOut, isMaxBuffer,
          shortMessage: launchError ? (launchError.code ?? launchError.name) : 'Harmony gh did not return an exit code',
        });
      });
      child.stdin.on('error', error => {
        if (error.code !== 'EPIPE') launchError ??= error;
      });
      child.stdin.end(options.input);
    });
  };
}

function startForgeAccountBridge(root, runGh, mark) {
  const directory = path.join(root, 'tmp/github-account');
  const request = path.join(directory, 'request.json');
  const consumed = path.join(directory, 'consumed.json');
  const status = path.join(directory, 'status.json');
  fs.mkdirSync(directory, { recursive: true, mode: 0o700 });
  for (const file of [request, consumed, status, status + '.new']) fs.rmSync(file, { force: true });
  let active;
  let last;
  let activeAccount;

  function publish(id, phase, fields = {}) {
    try {
      fs.writeFileSync(status + '.new', JSON.stringify({ id, phase, ...fields }), { mode: 0o600 });
      fs.renameSync(status + '.new', status);
      last = id;
    } catch {
      mark('forge-account-status-unavailable');
    }
  }

  async function execute(id, action, controller) {
    const signIn = action === 'login';
    const args = signIn ? ['auth', 'login', '--web', '--git-protocol', 'https', '--skip-ssh-key']
      : action === 'logout' ? ['auth', 'logout'] : ['auth', 'status', '--active'];
    args.push('--hostname', 'github.com');
    if (action === 'logout' && activeAccount) args.push('--user', activeAccount);
    let output = '';
    let presented = false;
    publish(id, 'working');
    mark('forge-account-started', { action });
    try {
      const options = {
        env: process.env, input: undefined, cancelSignal: controller.signal,
        timeout: signIn ? 900000 : 15000, maxBuffer: 32768,
        onOutput: signIn ? chunk => {
          if (presented || controller.signal.aborted) return;
          output += chunk.toString();
          const code = /one-time code:\s+([A-Z0-9]{4}-[A-Z0-9]{4})\b/i.exec(output)?.[1];
          if (!code) return;
          presented = true;
          publish(id, 'authorize', { code: code.toUpperCase() });
        } : undefined,
      };
      let result = await runGh('gh', args, options);
      if (action === 'logout' && result.exitCode === 0 && !controller.signal.aborted) {
        result = await runGh('gh', ['auth', 'status', '--active', '--hostname', 'github.com'], options);
      }
      let phase = 'failed';
      let account;
      if (controller.signal.aborted) phase = 'canceled';
      else if (result.exitCode === 0) {
        phase = 'signed-in';
        account = /(?:Logged in as |Logged in to github\.com account )([a-z0-9-]{1,39})\b/i
          .exec(result.stderr + '\n' + result.stdout)?.[1];
      } else if (!signIn && /not logged (?:into|in to)/i.test(result.stderr + '\n' + result.stdout)) {
        phase = 'signed-out';
      }
      if (phase === 'signed-in' || phase === 'signed-out') activeAccount = account;
      publish(id, phase, account ? { account } : {});
      mark('forge-account-finished', { action, phase });
    } finally {
      active = undefined;
    }
  }

  function receive() {
    try {
      fs.renameSync(request, consumed);
    } catch (error) {
      if (error.code !== 'ENOENT') mark('forge-account-request-unavailable');
      return;
    }
    let command;
    try {
      const file = fs.openSync(consumed, fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW | fs.constants.O_NONBLOCK);
      try {
        if (!fs.fstatSync(file).isFile()) return;
        const buffer = Buffer.alloc(513);
        const length = fs.readSync(file, buffer);
        if (length > 512) return;
        command = JSON.parse(buffer.subarray(0, length).toString());
      } finally { fs.closeSync(file); }
    } catch {
      return;
    } finally { fs.rmSync(consumed, { force: true }); }
    if (!command || typeof command.id !== 'string' || !/^[a-z0-9-]{6,60}$/.test(command.id)) return;
    const { id, action } = command;
    if (action === 'cancel') {
      if (active?.id === id) active.controller.abort();
      else if (!active && last !== id) publish(id, 'canceled');
      return;
    }
    if (active || !['status', 'login', 'logout'].includes(action)) return;
    const controller = new AbortController();
    active = { id, controller };
    void execute(id, action, controller).catch(() => publish(id, 'failed'));
  }
  const interval = setInterval(receive, 250);
  interval.unref();
}

module.exports = { createGhRunner, startForgeAccountBridge };

'use strict';

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

module.exports = { createGhRunner };

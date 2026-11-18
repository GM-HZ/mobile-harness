'use strict';
const { EventEmitter } = require('node:events');
const { pathToFileURL } = require('node:url');
const { isMainThread, parentPort, Worker, workerData } = require('node:worker_threads');

function createTunnelLauncher(entry, mark) {
  return (_executable, args, { env, stdio }) => {
    if (args.length !== 1 || args[0] !== entry || stdio.join(',') !== 'ignore,pipe,pipe,ipc') {
      throw new Error('Unexpected Harmony LiveShare gateway launch');
    }
    const worker = new Worker(__filename, {
      name: 'dsh-liveshare-gateway', execArgv: [], stdout: true, stderr: true,
      env: Object.fromEntries(Object.entries(env).filter(([, value]) => value !== undefined)),
      workerData: { entry },
    });
    const { threadId } = worker;
    const child = Object.assign(new EventEmitter(), {
      connected: true, exitCode: null, signalCode: null,
      stdout: worker.stdout, stderr: worker.stderr,
      send(message) {
        if (!child.connected) return false;
        worker.postMessage(message);
        return true;
      },
      kill(signal) {
        if (!child.connected) return false;
        child.connected = false;
        child.signalCode = signal;
        worker.terminate().catch(error => child.emit('error', error));
        return true;
      },
    });
    mark('liveshare-worker-started', { threadId });
    worker.once('online', () => child.emit('spawn'));
    worker.on('message', message => child.emit('message', message));
    worker.once('error', error => {
      child.connected = false;
      child.emit('error', error);
    });
    worker.once('exit', code => {
      child.connected = false;
      if (child.signalCode === null) child.exitCode = code;
      mark('liveshare-worker-stopped', { threadId, code });
      child.emit('exit', child.exitCode, child.signalCode);
    });
    return child;
  };
}

if (isMainThread) {
  module.exports = { createTunnelLauncher };
} else {
  // Keep the packaged gateway's IPC message contract on an isolated Node thread.
  process.send = message => {
    parentPort.postMessage(message);
    return true;
  };
  parentPort.on('message', message => process.emit('message', message));
  parentPort.once('close', () => process.emit('disconnect'));
  import(pathToFileURL(workerData.entry).href).catch(error => {
    console.error(error);
    process.exit(1);
  });
}

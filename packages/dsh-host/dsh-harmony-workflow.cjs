'use strict';

const fs = require('node:fs');
const { Socket } = require('node:net');
const { setTimeout: delay } = require('node:timers/promises');
const { bindingNames, listen, send } = require('./dsh-harmony-workflow-wire.cjs');

function createWorkflowRunner(native, record = () => {}) {
  return async function runWorkflow(bindings, signal) {
    signal.throwIfAborted();
    const { fd, id } = native.launch();
    const completion = Promise.withResolvers();
    let socket;
    let timer;
    let active = true;
    let ready = false;
    let beginRequested = false;
    let begun = false;
    let reaped = false;
    let slice = 'pending';
    let syncTimeout;
    let lastCall = 0;
    const pending = new Set();
    const fail = error => {
      if (!active) return;
      active = false;
      completion.reject(error);
    };
    const aborted = () => fail(new Error('Workflow cancelled'));
    try {
      socket = new Socket({ fd, readable: true, writable: true });
      signal.addEventListener('abort', aborted, { once: true });
      if (signal.aborted) aborted();
      timer = setTimeout(() => fail(new Error('Workflow worker startup timed out')), 10000);
      socket.on('end', () => fail(new Error('Workflow worker exited before returning a result')));
      listen(socket, message => {
        if (!active) return;
        if (message.type === 'ready' && !ready) {
          ready = true;
          record('workflow-worker-ready', { id });
        } else if (message.type === 'error') {
          fail(new Error(typeof message.message === 'string' ? message.message.slice(0, 1024) : 'Workflow worker failed'));
        } else if (ready && message.type === 'call') {
          const fn = Object.hasOwn(bindings, message.method) && bindingNames.includes(message.method) && bindings[message.method];
          if (!Number.isSafeInteger(message.id) || message.id <= lastCall || typeof fn !== 'function' ||
              pending.size >= 128 || (message.method === 'begin' ? beginRequested : !begun)) {
            throw new Error('Invalid Workflow binding request');
          }
          if (message.method === 'begin') beginRequested = true;
          lastCall = message.id;
          const reply = response => { if (active) send(socket, { type: 'reply', id: message.id, ...response }); };
          const call = Promise.resolve().then(() => fn(message.args, { signal })).then(value => {
            if (message.method === 'begin') {
              syncTimeout = value?.limits?.syncTimeoutMs;
              if (!Number.isSafeInteger(syncTimeout) || syncTimeout < 1 || syncTimeout > 2147483647) {
                throw new Error('Invalid Workflow synchronous timeout');
              }
              begun = true;
              record('workflow-worker-bound', { id });
            }
            reply({ value });
          }, error => reply({ error: String(error?.message ?? error).slice(0, 1024) }));
          pending.add(call);
          void call.catch(fail).finally(() => pending.delete(call));
        } else if (begun && message.type === 'slice-start' && slice === 'pending' && message.timeout === syncTimeout) {
          slice = 'running';
          clearTimeout(timer);
          record('workflow-worker-running', { id });
          timer = setTimeout(() => fail(new Error(`Workflow synchronous execution exceeded ${syncTimeout} ms`)), syncTimeout);
        } else if (message.type === 'slice-end' && slice === 'running') {
          slice = 'ended';
          clearTimeout(timer);
        } else if (message.type === 'result' && slice === 'ended') {
          active = false;
          completion.resolve(message.value);
        } else {
          throw new Error('Unexpected Workflow control message');
        }
      }, fail);
      const value = await completion.promise;
      const exit = await waitForExit(native, id);
      reaped = true;
      if (exit.exitCode !== 0 || exit.signal !== 0) throw new Error('Workflow worker did not exit successfully');
      return { value };
    } finally {
      active = false;
      clearTimeout(timer);
      signal.removeEventListener('abort', aborted);
      if (socket) socket.destroy();
      else fs.closeSync(fd);
      // The normal result path already consumed the child status.
      if (!reaped) {
        native.terminate(id);
        await waitForExit(native, id);
      }
      record('workflow-worker-reaped', { id });
    }
  };
}

async function waitForExit(native, id) {
  for (let attempt = 0; attempt < 50; ++attempt) {
    const status = native.status(id);
    if (status) return status;
    await delay(20);
  }
  throw new Error('Workflow worker cleanup timed out');
}

module.exports = { createWorkflowRunner };

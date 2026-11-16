'use strict';

const fs = require('node:fs');
const vm = require('node:vm');
const { bindingNames, encode, parseFrames } = require('./dsh-harmony-workflow-wire.cjs');
const addon = { exports: {} };
process.dlopen(addon, 'libdshworkflow.so');
const native = addon.exports;

function send(message) {
  const frame = encode(message);
  for (let offset = 0; offset < frame.length;) {
    native.waitChannel(true);
    try { offset += fs.writeSync(0, frame, offset, frame.length - offset); }
    catch (error) { if (error.code !== 'EAGAIN') throw error; }
  }
}

function run(runWorkflowGuest) {
  const pending = new Map();
  let id = 0;
  const bind = method => args => {
    const requestId = ++id;
    const promise = Promise.withResolvers();
    pending.set(requestId, promise);
    send({ type: 'call', id: requestId, method, args });
    return promise.promise;
  };
  const receive = parseFrames(message => {
    const reply = pending.get(message.id);
    if (message.type !== 'reply' || !reply) throw new Error('Invalid Workflow reply');
    pending.delete(message.id);
    if (typeof message.error === 'string') reply.reject(new Error(message.error));
    else reply.resolve(message.value);
  });
  const runInContext = vm.Script.prototype.runInContext;
  vm.Script.prototype.runInContext = function (context, { timeout, ...options }) {
    send({ type: 'slice-start', timeout });
    try { return runInContext.call(this, context, options); }
    finally { send({ type: 'slice-end' }); }
  };

  // No script or session data crosses the channel until this restriction succeeds.
  native.confine();
  send({ type: 'ready' });
  const host = Object.fromEntries(bindingNames.map(name => [name, bind(name)]));
  let settled;
  void runWorkflowGuest(host).then(value => { settled = { type: 'result', value }; }, error => {
    settled = { type: 'error', message: String(error?.message ?? error).slice(0, 1024) };
  });
  // The worker runs only JavaScript promises and the single blocking control channel.
  // This entry is a Node callback, outside a running promise microtask checkpoint.
  const buffer = Buffer.alloc(65536);
  for (;;) {
    process._tickCallback();
    if (settled) {
      send(settled);
      native.finish(settled.type === 'result' ? 0 : 1);
    }
    native.waitChannel(false);
    let count;
    try { count = fs.readSync(0, buffer, 0, buffer.length, null); }
    catch (error) { if (error.code === 'EAGAIN') continue; throw error; }
    if (count === 0) native.finish(1);
    // Parser may keep a partial frame until the next read.
    receive(Buffer.from(buffer.subarray(0, count)));
  }
}

import(PACKAGED_WORKFLOW_GUEST_URL).then(({ runWorkflowGuest }) => {
  setImmediate(() => {
    try { run(runWorkflowGuest); }
    catch (error) {
      try { send({ type: 'error', message: String(error?.message ?? error).slice(0, 1024) }); }
      finally { native.finish(1); }
    }
  });
}, () => native.finish(1));

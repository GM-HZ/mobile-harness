const assert = require('node:assert/strict');
const { once } = require('node:events');
const { createInterface } = require('node:readline');
const WebSocket = require(process.argv[2]);

async function run() {
  const lines = createInterface({ input: process.stdin })[Symbol.asyncIterator]();
  const input = JSON.parse((await lines.next()).value);
  const origin = 'http://127.0.0.1:19592';
  const socket = new WebSocket(input.endpoint, { headers: { Host: '127.0.0.1:19592', Origin: origin, Cookie: input.cookie } });
  try {
    await once(socket, 'open');
    let contextId;
    let nextId = 0;
    const pending = new Map();
    socket.on('message', raw => {
      const row = JSON.parse(raw.toString());
      if (row.method === 'Runtime.executionContextCreated' &&
          row.params.context.origin === origin && row.params.context.auxData?.type === 'dsh-client') {
        contextId = row.params.context.id;
      }
      pending.get(row.id)?.(row);
    });
    const call = async (method, params = {}) => {
      const id = ++nextId;
      const response = new Promise(resolve => pending.set(id, resolve));
      socket.send(JSON.stringify({ id, method, params }));
      const result = await response;
      pending.delete(id);
      assert.equal(result.error, undefined, JSON.stringify(result.error));
      return result.result;
    };
    await call('Runtime.enable');
    for (let retry = 0; !contextId && retry < 60; retry++) await new Promise(resolve => setTimeout(resolve, 200));
    assert.ok(contextId, 'ArkWeb CDP realm is unavailable');
    console.log(JSON.stringify({ ready: true }));
    for (;;) {
      const line = await lines.next();
      if (line.done) return;
      const expression = JSON.parse(line.value);
      const result = await call('Runtime.evaluate', { contextId, expression, returnByValue: true, awaitPromise: true });
      if (result.exceptionDetails) throw new Error(result.exceptionDetails.text);
      console.log(JSON.stringify(result.result.value ?? null));
    }
  } finally {
    socket.terminate();
  }
}
run().catch(error => { console.error(String(error)); process.exit(1); });

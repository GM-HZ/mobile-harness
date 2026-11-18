const assert = require('node:assert/strict');
const { once } = require('node:events');
const fs = require('node:fs');
const WebSocket = require(process.argv[2]);
const input = JSON.parse(fs.readFileSync(0, 'utf8'));

async function reject(url, options, status) {
  const socket = new WebSocket(url, options);
  const [, response] = await once(socket, 'unexpected-response');
  socket.on('error', () => {});
  response.resume();
  socket.terminate();
  assert.equal(response.statusCode, status);
}

async function verify() {
  const origin = 'http://127.0.0.1:19592';
  const headers = { Host: '127.0.0.1:19592', Origin: origin };
  await reject(input.proxy, { headers }, 401);
  await reject(input.direct, {}, 403);
  const socket = new WebSocket(input.proxy, { headers: { ...headers, Cookie: input.cookie } });
  try {
    await once(socket, 'open');
    const events = [];
    const pending = new Map();
    let id = 0;
    socket.on('message', raw => {
      const row = JSON.parse(raw.toString());
      if (row.id !== undefined) pending.get(row.id)?.(row);
      else events.push(row);
    });
    const call = async (method, params = {}) => {
      const requestId = ++id;
      const result = new Promise(resolve => pending.set(requestId, resolve));
      socket.send(JSON.stringify({ id: requestId, method, params }));
      const row = await result;
      pending.delete(requestId);
      assert.equal(row.error, undefined, JSON.stringify(row.error));
      return row.result;
    };
    const host = await call('Runtime.evaluate', {
      expression: '6 * 7',
      returnByValue: true,
    });
    assert.equal(host.result.value, 42);
    await call('Runtime.enable');
    let client;
    for (let retry = 0; retry < 60; retry++) {
      client = events.find(event => event.method === 'Runtime.executionContextCreated'
        && event.params.context.auxData?.type === 'dsh-client'
        && event.params.context.origin === origin)?.params.context;
      if (client) break;
      await new Promise(resolve => setTimeout(resolve, 200));
    }
    assert.ok(client, 'ArkWeb diagnostic realm did not connect');
    const page = await call('Runtime.evaluate', {
      contextId: client.id,
      expression: '({ origin: location.origin, document: document.nodeType })',
      returnByValue: true,
    });
    assert.deepEqual(page.result.value, { origin, document: 9 });
    console.log(JSON.stringify({ anonymousProxyStatus: 401, directCdpStatus: 403,
      hostEvaluation: host.result.value, arkWeb: page.result.value }));
  } finally {
    socket.terminate();
  }
}

verify().catch(error => { console.error(String(error)); process.exitCode = 1; });

const fs = require('node:fs');
const WebSocket = require(process.argv[2]);
const input = JSON.parse(fs.readFileSync(0, 'utf8'));

async function main() {
  const origin = 'http://127.0.0.1:19592';
  const socket = new WebSocket(input.proxy, {
    headers: { Host: '127.0.0.1:19592', Origin: origin, Cookie: input.cookie },
  });
  await new Promise((resolve, reject) => {
    socket.once('open', resolve);
    socket.once('error', reject);
  });
  let id = 0;
  const pending = new Map();
  socket.on('message', raw => {
    const row = JSON.parse(raw.toString());
    if (row.id !== undefined) pending.get(row.id)?.(row);
  });
  const call = async (method, params = {}) => {
    const requestId = ++id;
    const answer = new Promise(resolve => pending.set(requestId, resolve));
    socket.send(JSON.stringify({ id: requestId, method, params }));
    const row = await answer;
    pending.delete(requestId);
    if (row.error) throw new Error(JSON.stringify(row.error));
    return row.result;
  };
  const results = [];
  for (const item of input.expressions) {
    try {
      const answer = await call('Runtime.evaluate', {
        expression: item.expression,
        returnByValue: true,
        awaitPromise: item.awaitPromise === true,
        timeout: item.timeout ?? 15000,
      });
      results.push({
        label: item.label ?? null,
        value: answer.result?.value === undefined ? null : answer.result.value,
        description: answer.result?.description ?? null,
        exception: answer.exceptionDetails
          ? (answer.exceptionDetails.exception?.description ?? answer.exceptionDetails.text)
          : null,
      });
    } catch (error) {
      results.push({ label: item.label ?? null, callError: String(error) });
    }
  }
  socket.close();
  console.log(JSON.stringify(results));
}

main().catch(error => {
  console.log(JSON.stringify([{ failure: String(error) }]));
  process.exit(1);
});

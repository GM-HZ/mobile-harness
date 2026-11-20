const fs = require('node:fs');
const WebSocket = require(process.argv[2]);
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const started = Date.now();
let finished = false;
const finish = result => {
  if (finished) return;
  finished = true;
  try { socket.terminate(); } catch {}
  console.log(JSON.stringify({ ...result, elapsedMs: Date.now() - started }));
  process.exit(0);
};
const socket = new WebSocket(input.url, {
  headers: input.headers ?? {},
  rejectUnauthorized: input.rejectUnauthorized !== false,
  handshakeTimeout: input.timeout ?? 8000,
});
socket.on('open', () => finish({ outcome: 'upgraded' }));
socket.on('unexpected-response', (request, response) => {
  response.resume();
  finish({ outcome: 'http', status: response.statusCode, headers: { server: response.headers.server ?? null } });
});
socket.on('error', error => finish({ outcome: 'error', message: String(error?.message ?? error) }));
setTimeout(() => finish({ outcome: 'timeout' }), input.timeout ?? 9000);

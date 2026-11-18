'use strict';
const http = require('node:http');
const { WebSocketServer } = require(process.argv[2]);

const credential = 'fixture-payload.fixture-signature';
const shares = new Map();
const log = record => console.log(JSON.stringify(record));
function reply(response, status, value) {
  response.writeHead(status, { 'content-type': 'application/json' });
  response.end(JSON.stringify(value));
}
const server = http.createServer((request, response) => {
  const url = new URL(request.url, 'http://127.0.0.1');
  if (url.pathname === '/__liveshare/owner-credential') {
    reply(response, 200, { supported: true });
    return;
  }
  const share = url.searchParams.get('shareId');
  if (!shares.has(share) || request.headers.authorization !== shares.get(share)) {
    reply(response, 404, { error: 'unknown-share' });
    return;
  }
  if (url.pathname === '/__liveshare/requests' && request.method === 'GET') {
    reply(response, 200, {
      version: 1, accessMode: 'open', allowedSubjectIds: [], sessionMode: 'view', requests: [],
    });
    return;
  }
  if (url.pathname === '/__liveshare/share' && request.method === 'DELETE') {
    shares.delete(share);
    log({ deleted: share });
    reply(response, 200, {});
    return;
  }
  reply(response, 404, { error: 'unknown-route' });
});
const sockets = new WebSocketServer({ noServer: true });
server.on('upgrade', (request, socket, head) => {
  const url = new URL(request.url, 'http://127.0.0.1');
  const share = url.searchParams.get('shareId') || '';
  const owner = request.headers.authorization;
  const authenticated = /^Bearer [A-Za-z0-9_-]+$/.test(owner || '')
    && request.headers['x-liveshare-owner-credential'] === credential
    && (!shares.has(share) || shares.get(share) === owner);
  if (url.pathname !== '/__tunnel_gateway__' || !share || !authenticated) {
    socket.end('HTTP/1.1 401 Unauthorized\r\nConnection: close\r\n\r\n');
    return;
  }
  const probe = share.startsWith('test-');
  if (!probe) shares.set(share, owner);
  sockets.handleUpgrade(request, socket, head, channel => {
    log({ registered: share, probe });
    channel.on('close', code => log({ closed: share, code }));
  });
});
server.listen(0, '127.0.0.1', () => console.log(server.address().port));

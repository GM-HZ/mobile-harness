'use strict';
// Minimal HTTPS reverse proxy that also forwards WebSocket upgrades, used to
// exercise the public Relay preflight path locally with a self-signed certificate.
const fs = require('node:fs');
const http = require('node:http');
const https = require('node:https');
const net = require('node:net');

const [certPath, keyPath, targetPort] = process.argv.slice(2);
const target = Number(targetPort);

const server = https.createServer({
  cert: fs.readFileSync(certPath),
  key: fs.readFileSync(keyPath),
}, (request, response) => {
  const upstream = http.request({
    host: '127.0.0.1', port: target, method: request.method, path: request.url,
    headers: { ...request.headers, host: '127.0.0.1:' + target },
  }, answer => {
    response.writeHead(answer.statusCode, answer.headers);
    answer.pipe(response);
  });
  upstream.on('error', () => { response.writeHead(502); response.end(); });
  request.pipe(upstream);
});

server.on('upgrade', (request, socket, head) => {
  const upstream = net.connect(target, '127.0.0.1', () => {
    const headers = Object.entries({ ...request.headers, host: '127.0.0.1:' + target })
      .map(([name, value]) => name + ': ' + value).join('\r\n');
    upstream.write(request.method + ' ' + request.url + ' HTTP/1.1\r\n' + headers + '\r\n\r\n');
    if (head && head.length) upstream.write(head);
    socket.pipe(upstream);
    upstream.pipe(socket);
  });
  upstream.on('error', () => socket.destroy());
  socket.on('error', () => upstream.destroy());
});

server.listen(0, '127.0.0.1', () => {
  process.stdout.write(String(server.address().port) + '\n');
});

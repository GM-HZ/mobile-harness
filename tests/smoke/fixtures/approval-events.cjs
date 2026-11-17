'use strict';

const readline = require('node:readline');
const { randomUUID } = require('node:crypto');
const WebSocket = require(process.argv[2]);
let socket;
const input = readline.createInterface({ input: process.stdin });
input.once('line', line => {
  const config = JSON.parse(line);
  socket = new WebSocket(config.url + '/api/remote.mux', {
    headers: { Host: config.host, Cookie: config.cookie, Origin: 'http://' + config.host },
  });
  socket.on('open', () => {
    socket.send(JSON.stringify({ type: 'open', streamId: randomUUID(), endpoint: '$events', payload: { args: {} } }));
  });
  socket.on('message', data => {
    const frame = JSON.parse(String(data));
    if (frame.type === 'item') process.stdout.write(JSON.stringify(frame.value) + '\n');
    else if (frame.type === 'error') process.stdout.write(JSON.stringify({ type: 'error', error: frame.error }) + '\n');
  });
  socket.on('error', error => {
    process.stdout.write(JSON.stringify({ type: 'error', message: error.message }) + '\n');
  });
});
input.on('close', () => { if (socket) socket.close(); });

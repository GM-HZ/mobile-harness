'use strict';
// Run with and without --jitless against the same locked Undici and real sockets.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const net = require('node:net');
const zlib = require('node:zlib');
const { registerHooks } = require('node:module');
const { pathToFileURL } = require('node:url');
const { patchClientH1 } = require('../../packages/dsh-host/dsh-harmony-http.cjs');
const [modules, portable] = process.argv.slice(2).map(value => path.resolve(value));
if (!modules || !portable) throw new Error('Usage: node [--jitless] portable-http.cjs <node_modules> <portable-parser>');
const parser = pathToFileURL(path.join(modules, 'undici/lib/dispatcher/client-h1.js')).href;
let patched = false;
globalThis.__harmonyLlhttp = require(portable);
const source = fs.readFileSync(path.join(modules, 'undici/lib/dispatcher/client-h1.js'), 'utf8');
assert.throws(() => patchClientH1(source + '\n'), /Unexpected locked/);
registerHooks({ load(url, context, next) {
  const result = next(url, context);
  if (url !== parser || typeof WebAssembly !== 'undefined') return result;
  patched = true;
  return { ...result, source: patchClientH1(String(result.source)) };
} });
const undici = require(modules + '/undici');
const fetch = (url, options = {}) => undici.fetch(url, { signal: AbortSignal.timeout(5000), ...options });
const listen = server => new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const close = server => new Promise(resolve => server.close(resolve));

(async () => {
  const payload = 'HARMONY_HTTP_中文_' + 'abcdef'.repeat(65536);
  const sockets = new Set();
  const own = server => server.on('connection', socket => {
    sockets.add(socket); socket.on('close', () => sockets.delete(socket));
  });
  let proxyConnects = 0;
  let proxyForwards = 0;
  const target = own(http.createServer(async (request, response) => {
    const url = request.url;
    if (url === '/redirect') { response.writeHead(302, { location: '/chunked' }); response.end(); return; }
    if (url === '/slow') { response.writeHead(200, { 'content-type': 'text/plain' }); response.write('pending'); return; }
    if (url === '/gzip') { response.writeHead(200, { 'content-encoding': 'gzip' }); response.end(zlib.gzipSync(payload)); return; }
    if (url === '/head') { response.writeHead(200, { 'content-length': '12345' }); response.end(); return; }
    if (url === '/empty') { response.writeHead(204); response.end(); return; }
    if (url === '/echo') {
      const chunks = []; for await (const chunk of request) chunks.push(chunk);
      response.end(Buffer.concat(chunks)); return;
    }
    if (url === '/error') { response.writeHead(418); response.end('fixture error'); return; }
    response.writeHead(200, { 'content-type': 'text/plain', trailer: 'x-fixture' });
    for (let index = 0; index < payload.length; index += 4096) response.write(payload.slice(index, index + 4096));
    response.addTrailers({ 'x-fixture': 'complete' }); response.end();
  }));
  const proxy = own(http.createServer((request, response) => {
    proxyForwards++;
    const destination = new URL(request.url);
    assert.equal(destination.origin, 'http://127.0.0.1:' + target.address().port);
    const upstream = http.request(destination, { method: request.method, headers: request.headers }, reply => {
      response.writeHead(reply.statusCode, reply.headers); reply.pipe(response);
    });
    upstream.on('error', error => response.destroy(error)); request.pipe(upstream);
  }));
  proxy.on('connect', (request, client, head) => {
    proxyConnects++;
    assert.equal(request.url, '127.0.0.1:' + target.address().port);
    const upstream = net.connect(target.address().port, '127.0.0.1', () => {
      client.write('HTTP/1.1 200 Connection Established\r\n\r\n');
      if (head.length) upstream.write(head);
      upstream.pipe(client); client.pipe(upstream);
    });
    sockets.add(upstream); upstream.on('close', () => sockets.delete(upstream));
    client.on('error', () => upstream.destroy()); upstream.on('error', () => client.destroy());
  });
  const malformed = own(net.createServer(socket => socket.once('data', () => socket.end(
    'HTTP/1.1 200 OK\r\nContent-Length: 1\r\nContent-Length: 2\r\nConnection: close\r\n\r\nxx'))));
  let proxyAgent;
  let tunnelAgent;
  try {
    await Promise.all([listen(target), listen(proxy), listen(malformed)]);
    const base = 'http://127.0.0.1:' + target.address().port;
    const checks = [];
    const record = name => { checks.push(name); if (process.env.MH_HTTP_TRACE) console.error(name); };
    for (let i = 0; i < 3; i++) assert.equal(await (await fetch(base + '/chunked')).text(), payload);
    record('chunked-trailers-large-body-repeated-keepalive');
    assert.equal(await (await fetch(base + '/gzip')).text(), payload); record('gzip');
    assert.equal(await (await fetch(base + '/redirect')).text(), payload); record('redirect');
    assert.equal(await (await fetch(base + '/head', { method: 'HEAD' })).text(), ''); record('head');
    assert.equal((await fetch(base + '/empty')).status, 204); record('empty');
    assert.equal(await (await fetch(base + '/echo', { method: 'POST', body: '中文 body' })).text(), '中文 body'); record('post');
    const error = await fetch(base + '/error'); assert.equal(error.status, 418); assert.equal(await error.text(), 'fixture error'); record('http-error-body');
    const controller = new AbortController();
    const pending = await fetch(base + '/slow', { signal: controller.signal });
    controller.abort(); await assert.rejects(pending.text(), error => error.name === 'AbortError');
    assert.equal(await (await fetch(base + '/chunked')).text(), payload); record('cancel-body-and-reuse');
    // Exact error from the same Undici version's native-WASM control run.
    await assert.rejects(fetch('http://127.0.0.1:' + malformed.address().port), error => error.cause?.code === 'UND_ERR_RES_CONTENT_LENGTH_MISMATCH');
    record('malformed-framing-rejected');
    proxyAgent = new undici.ProxyAgent('http://127.0.0.1:' + proxy.address().port);
    assert.equal(await (await fetch(base + '/chunked', { dispatcher: proxyAgent })).text(), payload);
    assert.equal(proxyForwards, 1); record('explicit-forward-proxy-dispatcher');
    tunnelAgent = new undici.ProxyAgent({ uri: 'http://127.0.0.1:' + proxy.address().port, proxyTunnel: true });
    assert.equal(await (await fetch(base + '/chunked', { dispatcher: tunnelAgent })).text(), payload);
    assert.equal(proxyConnects, 1); record('explicit-connect-proxy-dispatcher');
    assert.equal(patched, typeof WebAssembly === 'undefined');
    console.log(JSON.stringify({ jitless: typeof WebAssembly === 'undefined', patched, checks }));
  } finally {
    await Promise.allSettled([undici.getGlobalDispatcher().destroy(), proxyAgent?.destroy(), tunnelAgent?.destroy()]);
    for (const socket of sockets) socket.destroy();
    await Promise.all([close(target), close(proxy), close(malformed)]);
  }
})().catch(error => { console.error(error); process.exitCode = 1; });

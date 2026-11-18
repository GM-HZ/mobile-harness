'use strict';
const http = require('node:http');
const { createHash, randomBytes } = require('node:crypto');
const { WebSocketServer } = require(process.argv[2]);

const login = process.argv.includes('--owner-login');
const credential = login ? Buffer.from(JSON.stringify({
  subjectId: 'owner', displayName: 'Fixture Relay Owner', expiresAt: Date.now() + 60 * 60_000,
})).toString('base64url') + '.fixture-signature' : 'fixture-payload.fixture-signature';
const codes = new Map();
const shares = new Map();
const actor = {
  providerId: 'fixture', tenantId: 'local', subjectId: 'reader', credential: 'synthetic-reader-claim',
};
let requestId = 0;
const log = record => console.log(JSON.stringify(record));
function reply(response, status, value) {
  response.writeHead(status, { 'content-type': 'application/json' });
  response.end(JSON.stringify(value));
}
function forwardViewer(request, response, state) {
  if (request.headers.authorization !== 'Bearer fixture-viewer') {
    reply(response, 401, { error: 'viewer-login-required' });
    return;
  }
  if (!state?.channel) {
    reply(response, 404, { error: 'unknown-share' });
    return;
  }
  const chunks = [];
  request.on('data', chunk => chunks.push(chunk));
  request.on('end', () => {
    const body = JSON.parse(Buffer.concat(chunks));
    const id = ++requestId;
    const channel = state.channel;
    const upload = body.op === 'call' && body.path === '/api/fileUploads/upload';
    const started = performance.now();
    const done = (data) => {
      const frame = JSON.parse(data);
      if (frame.type !== 'share-rpc-res' || frame.id !== id) return;
      clearTimeout(timer);
      channel.off('message', done);
      if (upload) log({ attachmentCall: id, status: frame.status, elapsedMs: Math.round(performance.now() - started) });
      reply(response, frame.status, frame.body);
    };
    const timer = setTimeout(() => {
      channel.off('message', done);
      if (upload) log({ attachmentCall: id, status: 504, elapsedMs: Math.round(performance.now() - started) });
      reply(response, 504, { error: 'viewer-read-timed-out' });
    }, upload ? 25000 : 6000);
    channel.on('message', done);
    channel.send(JSON.stringify({ type: 'share-rpc', id, actor, body }));
  });
}

const server = http.createServer((request, response) => {
  const url = new URL(request.url, 'http://127.0.0.1');
  if (login && url.pathname === '/__liveshare/owner-authorize' && request.method === 'GET') {
    const { origin, state, code_challenge, instance } = Object.fromEntries(url.searchParams);
    if (origin !== 'http://127.0.0.1:19592' || !/^[\w-]{22}$/.test(state) ||
        !/^[\w-]{43}$/.test(code_challenge) || !instance) {
      reply(response, 400, { error: 'fixture-authorization-invalid' });
      return;
    }
    const code = randomBytes(24).toString('base64url');
    codes.set(code, { challenge: code_challenge, instance });
    log({ ownerAuthorizationDisplayed: true });
    response.writeHead(200, { 'content-type': 'text/html; charset=utf-8' });
    response.end(`<!doctype html><title>Fixture Relay Owner</title>
<button id="approve">Authorize fixture owner</button><script>
const origin = ${JSON.stringify(origin)};
const completion = ${JSON.stringify({ type: 'liveshare-auth-code', code, state })};
document.querySelector('#approve').onclick = () => window.opener.postMessage(completion, origin);
window.addEventListener('message', event => {
  if (event.origin === origin && event.source === window.opener &&
      event.data?.type === 'liveshare-auth-ack' && event.data.state === completion.state) window.close();
});
</script>`);
    return;
  }
  if (url.pathname === '/__liveshare/owner-credential') {
    if (login && request.method === 'POST') {
      let body = '';
      request.on('data', chunk => { body += chunk; });
      request.on('end', () => {
        const { code, code_verifier, instanceKey } = JSON.parse(body);
        const issued = codes.get(code);
        if (!issued || typeof code_verifier !== 'string' || issued.instance !== instanceKey ||
            createHash('sha256').update(code_verifier).digest('base64url') !== issued.challenge) {
          reply(response, 403, { error: 'invalid-code' });
          return;
        }
        codes.delete(code);
        log({ ownerCredentialRedeemed: true, pkceMatched: true });
        reply(response, 200, { credential });
      });
      return;
    }
    reply(response, 200, { supported: true });
    return;
  }
  const share = url.searchParams.get('shareId');
  const state = shares.get(share);
  if (url.pathname === '/__share/rpc' && request.method === 'POST') {
    forwardViewer(request, response, state);
    return;
  }
  if (url.pathname === '/__fixture/revoke' && request.method === 'POST' &&
      request.headers.authorization === 'Bearer fixture-admin' && state) {
    state.authority = { ...state.authority, version: 2, allowedSubjectIds: ['fixture:local:other'] };
    reply(response, 200, { revoked: true });
    return;
  }
  if (!state || request.headers.authorization !== state.owner) {
    reply(response, 404, { error: 'unknown-share' });
    return;
  }
  if (url.pathname === '/__liveshare/requests' && request.method === 'GET') {
    reply(response, 200, { ...state.authority, requests: [] });
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
    && (!shares.has(share) || shares.get(share).owner === owner);
  if (url.pathname !== '/__tunnel_gateway__' || !share || !authenticated) {
    socket.end('HTTP/1.1 401 Unauthorized\r\nConnection: close\r\n\r\n');
    return;
  }
  const probe = share.startsWith('test-');
  sockets.handleUpgrade(request, socket, head, channel => {
    if (!probe) {
      const state = shares.get(share) ?? {
        owner,
        authority: {
          version: 1, accessMode: url.searchParams.get('accessMode'),
          allowedSubjectIds: url.searchParams.getAll('allowedSubjectId'),
          sessionMode: url.searchParams.get('sessionMode') === 'write' ? 'write' : 'view',
        },
      };
      state.channel = channel;
      shares.set(share, state);
    }
    log({ registered: share, probe });
    channel.on('close', code => {
      const state = shares.get(share);
      if (state?.channel === channel) delete state.channel;
      log({ closed: share, code });
    });
  });
});
server.listen(0, '127.0.0.1', () => console.log(server.address().port));

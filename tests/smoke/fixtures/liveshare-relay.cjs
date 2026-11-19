'use strict';
const fs = require('node:fs');
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
let viewerConfig = null;
const logRecords = [];
const log = record => { logRecords.push(record); console.log(JSON.stringify(record)); };
function viewerAuthorized(request) {
  return request.headers.authorization === 'Bearer fixture-viewer' ||
    /(?:^|;\s*)mh_viewer=fixture-viewer(?:;|$)/.test(request.headers.cookie || '');
}
function shareFor(request, url) {
  const explicit = url.searchParams.get('shareId');
  if (explicit) return explicit;
  const match = /(?:^|;\s*)mh_share=([^;]+)/.exec(request.headers.cookie || '');
  return match ? decodeURIComponent(match[1]) : null;
}
function askOwner(state, body, timeout) {
  return new Promise(resolve => {
    const channel = state?.channel;
    if (!channel) { resolve({ status: 404, body: { error: 'unknown-share' } }); return; }
    const id = ++requestId;
    const started = performance.now();
    const done = data => {
      let frame;
      try { frame = JSON.parse(data); } catch { return; }
      if (frame.type !== 'share-rpc-res' || frame.id !== id) return;
      clearTimeout(timer);
      channel.off('message', done);
      resolve({ status: frame.status, body: frame.body, elapsedMs: Math.round(performance.now() - started) });
    };
    const timer = setTimeout(() => {
      channel.off('message', done);
      resolve({ status: 504, body: { error: 'viewer-read-timed-out' }, elapsedMs: Math.round(performance.now() - started) });
    }, timeout);
    channel.on('message', done);
    channel.send(JSON.stringify({ type: 'share-rpc', id, actor, body }));
  });
}
function reply(response, status, value) {
  response.writeHead(status, { 'content-type': 'application/json' });
  response.end(JSON.stringify(value));
}
function forwardViewer(request, response, state) {
  if (!viewerAuthorized(request)) {
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
    const cookieViewer = !request.headers.authorization && /mh_viewer=fixture-viewer/.test(request.headers.cookie || '');
    log({ viewerRpc: body.op + ':' + (body.path || ''), viaCookie: cookieViewer });
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
  if (url.pathname === '/__fixture/log' && request.method === 'GET' &&
      request.headers.authorization === 'Bearer fixture-admin') {
    reply(response, 200, { records: logRecords });
    return;
  }
  if (url.pathname === '/__fixture/viewer' && request.method === 'POST' &&
      request.headers.authorization === 'Bearer fixture-admin') {
    const chunks = [];
    request.on('data', chunk => chunks.push(chunk));
    request.on('end', () => {
      viewerConfig = JSON.parse(Buffer.concat(chunks));
      log({ viewerConfigured: true, sessionId: viewerConfig.sessionId });
      reply(response, 200, { ok: true });
    });
    return;
  }
  if (url.pathname === '/health' && request.method === 'GET') {
    reply(response, 200, { release_id: 'mobile-harness-test-relay' });
    return;
  }
  const share = shareFor(request, url);
  const state = shares.get(share);
  if (url.pathname === '/__liveshare/context' && request.method === 'GET' && state) {
    log({ viewerContext: true, share, viaCookie: /mh_viewer=fixture-viewer/.test(request.headers.cookie || '') });
    reply(response, 200, {
      shareId: share, sessionId: viewerConfig?.sessionId ?? '', ownerDisplayName: viewerConfig?.ownerDisplayName ?? 'Fixture Owner',
      viewer: { subjectId: 'reader', displayName: 'Fixture Viewer' },
      capabilities: {
        sessionMode: state.authority?.sessionMode === 'write' ? 'write' : 'view',
        readOnly: state.authority?.sessionMode !== 'write', online: Boolean(state.channel), allowsFork: false,
      },
    });
    return;
  }
  if (url.pathname === '/' && request.method === 'GET' && state && viewerConfig?.carrier) {
    void (async () => {
      try {
        const asset = await askOwner(state, { op: 'asset', path: '' }, 20000);
        if (asset.status !== 200 || typeof asset.body?.base64 !== 'string') {
          log({ viewerPageAssetFailed: asset.status, share });
          reply(response, asset.status, asset.body);
          return;
        }
        const html = Buffer.from(asset.body.base64, 'base64').toString('utf8');
        const count = { value: 0 };
        const injected = html.replace(/<head(?:\s[^>]*)?>/i, match => {
          count.value += 1;
          return match + '<script>' + viewerConfig.carrier + '</script>';
        });
        if (count.value !== 1) {
          log({ viewerPageHeadMissing: count.value, share });
          reply(response, 500, { error: 'fixture-viewer-page-head-missing' });
          return;
        }
        if (process.env.MH_RELAY_PAGE_DUMP) fs.writeFileSync(process.env.MH_RELAY_PAGE_DUMP, injected);
        log({ viewerPageServed: true, share, sessionId: viewerConfig.sessionId,
              userAgent: request.headers['user-agent'] || '', elapsedMs: asset.elapsedMs });
        response.writeHead(200, {
          'content-type': 'text/html; charset=utf-8',
          'set-cookie': ['mh_viewer=fixture-viewer; Path=/; HttpOnly',
                         'mh_share=' + encodeURIComponent(share) + '; Path=/'],
        });
        response.end(injected);
      } catch (error) {
        log({ viewerPageFailed: String(error).slice(0, 500), share });
        reply(response, 500, { error: 'fixture-viewer-page-failed', message: String(error) });
      }
    })();
    return;
  }
  if (request.method === 'GET' && state && viewerAuthorized(request) && url.pathname !== '/__share/rpc') {
    void (async () => {
      try {
        const path = url.pathname.slice(1) + url.search;
        const asset = await askOwner(state, { op: 'asset', path }, 25000);
        log({ viewerAsset: path.slice(0, 160), status: asset.status, elapsedMs: asset.elapsedMs });
        if (asset.status !== 200) { reply(response, asset.status, asset.body); return; }
        response.writeHead(200, { 'content-type': asset.body?.contentType || 'application/octet-stream' });
        response.end(Buffer.from(asset.body?.base64 || '', 'base64'));
      } catch (error) {
        reply(response, 500, { error: 'fixture-viewer-asset-failed', message: String(error) });
      }
    })();
    return;
  }
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
  if (url.pathname === '/__fixture/authorize' && request.method === 'POST' &&
      request.headers.authorization === 'Bearer fixture-admin' && state) {
    state.authority = { ...state.authority, version: 3, allowedSubjectIds: ['fixture:local:reader'] };
    log({ viewerReauthorized: share });
    reply(response, 200, { authorized: true });
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
  log({ unhandled: request.method + ' ' + url.pathname, share, hasState: Boolean(state) });
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

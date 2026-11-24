'use strict';

const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { stripTypeScriptTypes } = require('node:module');
const path = require('node:path');

async function main() {
  const files = new Map();
  const requests = [];
  let redirect;
  let destroyed = 0;
  let response = {
    responseCode: 303,
    header: { location: './', 'set-cookie': 'dsh-auth-fixture=v1.payload.sig; Domain=other.example; Path=/;' },
  };
  const sdk = {
    url: { URL: { parseURL: (value, base) => new URL(value, base) } },
    util: {
      TextDecoder: { create: () => ({ decodeToString: bytes => new TextDecoder().decode(bytes) }) },
      TextEncoder: class { encodeInto(value) { return new TextEncoder().encode(value); } },
    },
    http: {
      InterceptorType: { REDIRECTION: 'redirect' },
      RequestMethod: { GET: 'GET' },
      HttpInterceptorChain: class {
        addChain(chain) {
          [redirect] = chain;
          return true;
        }
        apply() { return true; }
      },
      createHttp() {
        return {
          async request(address, options) {
            requests.push(address);
            assert.equal(options.usingCache, false);
            assert.equal(redirect.interceptorType, 'redirect');
            assert.equal(await redirect.interceptorHandle({}, response), false);
            return response;
          },
          destroy() { destroyed++; },
        };
      },
    },
    fileIo: {
      OpenMode: { WRITE_ONLY: 1, CREATE: 2, TRUNC: 4 },
      readTextSync(file) {
        if (!files.has(file)) throw new Error('missing');
        return files.get(file);
      },
      openSync(file) { return { fd: file }; },
      writeSync(file, data) {
        files.set(file, Buffer.from(data).toString('utf8'));
        return data.byteLength;
      },
      fsyncSync() {},
      closeSync() {},
      renameSync(source, destination) {
        files.set(destination, files.get(source));
        files.delete(source);
      },
    },
  };
  globalThis.remoteHostSdkMocks = sdk;
  const file = path.join(__dirname, '../../apps/harmonyos/entry/src/main/ets/runtime/RemoteHosts.ets');
  const source = readFileSync(file, 'utf8').replace(/^import .*;\n/gm, '');
  const code = stripTypeScriptTypes('const { url, util, http, fileIo } = globalThis.remoteHostSdkMocks;\n' + source);
  const remote = await import('data:text/javascript;base64,' + Buffer.from(code).toString('base64'));

  const origin = 'https://server.example:19443';
  assert.equal(remote.remoteHostOrigin(' Https://Server.Example:19443/ '), origin);
  for (const bad of ['http://server.example', `${origin}/?token=secret`, `${origin}/#fragment`,
    'https://user:secret@server.example', `${origin}/alternate`]) {
    assert.throws(() => remote.remoteHostOrigin(bad));
  }
  assert(remote.allowedRemoteRequest(origin, origin + '/api/chat'));
  for (const bad of ['http://127.0.0.1:19592/', 'https://server.example:19444/',
    'https://server.example.attacker.example:19443/', 'file:///tmp/secret']) {
    assert(!remote.allowedRemoteRequest(origin, bad));
  }

  const build = (selfBuild, appGallery) => ({
    filesDir: '/test',
    resourceManager: {
      getRawFileListSync() { return appGallery ? ['appgallery.patch.yml'] : []; },
      getRawFileContentSync() { return Buffer.from(JSON.stringify({ selfBuild })); },
    },
  });
  const context = build(true, false);
  assert(remote.isRemoteHostsEnabled(context));
  assert(!remote.isRemoteHostsEnabled(build(false, false)));
  assert(!remote.isRemoteHostsEnabled(build(true, true)));
  remote.RemoteHostStore.remember(context, { name: 'remote', origin, token: 'must-not-persist' });
  assert.deepEqual(remote.RemoteHostStore.list(context), [{ name: 'remote', origin }]);
  assert(![...files.values()].some(value => value.includes('must-not-persist')));
  remote.RemoteHostStore.remove(context, origin);
  assert.deepEqual(remote.RemoteHostStore.list(context), []);

  assert.equal(await remote.exchangeRemoteToken(origin, 'synthetic-token'), 'dsh-auth-fixture=v1.payload.sig');
  assert.deepEqual(requests, [origin + '/?token=synthetic-token']);
  response = { ...response, header: { ...response.header, location: 'https://attacker.example/' } };
  await assert.rejects(remote.exchangeRemoteToken(origin, 'synthetic-token'), /same-origin/);
  response = { responseCode: 303, header: { location: './', 'set-cookie': 'tracking=fixture;' } };
  await assert.rejects(remote.exchangeRemoteToken(origin, 'synthetic-token'), /Missing DSH/);
  await assert.rejects(remote.exchangeRemoteToken('http://server.example', 'synthetic-token'));
  assert.equal(destroyed, 3);
  console.log('REMOTE_HOST_CONTRACT_OK');
}

main().catch(error => {
  console.error(error.message);
  process.exitCode = 1;
});

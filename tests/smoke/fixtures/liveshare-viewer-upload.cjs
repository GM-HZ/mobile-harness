'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

async function main() {
  const { base, share, session, outside, html, carrier, files } = JSON.parse(fs.readFileSync(0, 'utf8'));
  const { installViewerCarrier } = await import('data:text/javascript;base64,' + carrier);
  globalThis.document = { baseURI: base + '/?shareId=' + share };
  globalThis.location = new URL(document.baseURI);
  const networkFetch = globalThis.fetch;
  let requests = 0;
  let active = 0;
  let peak = 0;
  globalThis.fetch = async (url, init) => {
    assert.equal(new URL(url, base).href, base + '/__share/rpc?shareId=' + share);
    requests++;
    active++;
    peak = Math.max(peak, active);
    try {
      return await networkFetch(new URL(url, base), {
        ...init, headers: { ...init.headers, Authorization: 'Bearer fixture-viewer' },
      });
    } finally {
      active--;
    }
  };
  installViewerCarrier({ basePath: '', shareId: share, sessionId: session, readTimeoutMs: 8000 });
  const script = html.match(/<script id="dsh-share-upload">([\s\S]*?)<\/script>/)?.[1];
  assert.ok(script, 'The owner must serve the actual visitor upload hook');
  vm.runInThisContext(script, { filename: 'served-liveshare-upload.js' });
  async function upload(file, sessionId, signal) {
    const query = new URLSearchParams({ sessionId, name: file.name });
    if (file.mediaType) query.set('mediaType', file.mediaType);
    const url = 'api/session/uploadFileBinary?' + query.toString();
    const response = await globalThis.__DSH_FILE_UPLOAD__.fetch(url, {
      method: 'POST', body: new Blob([Buffer.from(file.data, 'base64')]), signal,
    });
    assert.equal(response.status, 200);
    return response.json();
  }
  const stopped = new AbortController();
  stopped.abort();
  await assert.rejects(upload(files[0], session, stopped.signal), { name: 'AbortError' });
  assert.equal(requests, 0);
  const refused = [];
  for (const file of files.slice(0, 2)) {
    const result = await upload(file, outside);
    assert.equal(result.ok, false);
    assert.equal(result.error.code, 'remote-access/denied');
    refused.push(result.error.code);
  }
  const staged = await Promise.all(files.map(async file => {
    const result = await upload(file, session);
    assert.equal(result.ok, true, JSON.stringify(result));
    return result.value;
  }));
  assert.equal(requests, files.length + refused.length);
  assert.equal(peak, 1);
  console.log(JSON.stringify({ refused, staged, cancelledBeforeTransfer: true, requests, peak }));
}

main().catch(error => {
  console.error(error);
  process.exitCode = 1;
});

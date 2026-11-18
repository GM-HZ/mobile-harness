'use strict';

const { Module, registerHooks } = require('node:module');
const { pathToFileURL } = require('node:url');
const { isMainThread } = require('node:worker_threads');

if (isMainThread || !process.argv[1]) throw new Error('Expected the packaged Inspector Worker');

const allowed = new Set([
  'internal/modules/cjs/loader',
  'internal/modules/esm/loader',
  'internal/modules/esm/resolve',
  'internal/modules/esm/utils',
  'internal/modules/helpers',
]);
const load = Module._load;
Module._load = function (id, ...args) {
  if (id === 'node-addon-require-builtin') {
    return {
      isAllowedInternalId: name => allowed.has(name),
      requireBuiltin(name) {
        if (!allowed.has(name)) throw new Error('Unsupported Inspector internal module: ' + name);
        return require(name);
      },
    };
  }
  return load.call(this, id, ...args);
};

// Forward only requests authorized by the Host's existing DevTools proxy.
// The browser ingest socket keeps its independent origin and protocol checks.
const entry = pathToFileURL(process.argv[1]).href;
registerHooks({
  load(url, context, nextLoad) {
    const result = nextLoad(url, context);
    if (url !== entry) return result;
    let source = typeof result.source === 'string' ? result.source : Buffer.from(result.source).toString();
    const http = 'handleHttp(request, response) {';
    const cdp = 'if (url.pathname === `/devtools/page/${this.config.targetId}`) {';
    if (source.split(http).length !== 2 || source.split(cdp).length !== 2) {
      throw new Error('Unexpected pinned Inspector Worker entry');
    }
    const unauthorized = 'request.headers["x-dsh-inspector-token"] !== this.config.clientToken';
    source = source.replace(http, http + '\n' +
      'if (' + unauthorized + ') { response.writeHead(403).end(); return; }');
    source = source.replace(cdp, cdp + '\n' +
      'if (' + unauthorized + ') { socket.end("HTTP/1.1 403 Forbidden\\r\\nConnection: close\\r\\nContent-Length: 0\\r\\n\\r\\n"); return; }');
    return { ...result, source };
  },
});

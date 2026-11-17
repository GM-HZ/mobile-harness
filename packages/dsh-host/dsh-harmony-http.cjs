'use strict';
const { createHash } = require('node:crypto');

// Keep Undici's dispatcher, proxy policy, framing callbacks and errors intact.
// Only the locked llhttp instantiation changes when native WASM is unavailable.
function patchClientH1(source) {
  const expected = 'e8eb930546e7f7755471c75069878e3584b50f2c9ec8468fc8f2a1d236dab9a4';
  if (createHash('sha256').update(source).digest('hex') !== expected) {
    throw new Error('Unexpected locked Undici HTTP/1 parser integration');
  }
  const start = source.indexOf('  const llhttpWasmData');
  const end = source.indexOf('    env: {', start);
  if (start < 0 || end < 0 || !source.slice(start, end).includes('return new WebAssembly.Instance(mod, {')) {
    throw new Error('Unexpected Undici llhttp initialization');
  }
  return source.slice(0, start) + '  return globalThis.__harmonyLlhttp({\n' + source.slice(end);
}

module.exports = { patchClientH1 };

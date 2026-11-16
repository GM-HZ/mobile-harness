'use strict';
const assert = require('node:assert/strict');
const { performance } = require('node:perf_hooks');
const { isDeepStrictEqual } = require('node:util');

function transform(transformSync, input) {
  try {
    return { output: transformSync(input, { mode: 'strip-only' }).code };
  } catch (error) {
    return { error: error.code ?? error.name, message: error.message };
  }
}

function verify(transformSync, baseline) {
  assert.equal(typeof WebAssembly, 'undefined');
  const start = performance.now();
  let rejected = 0;
  for (const [name, input, expected] of baseline) {
    const current = transform(transformSync, input);
    assert.ok(isDeepStrictEqual(current, expected), `Amaro result differed for ${name}`);
    if (current.error) ++rejected;
  }
  return {
    cases: baseline.length, stripped: baseline.length - rejected, rejected,
    stripMs: Math.round(performance.now() - start), wasm: false,
  };
}

module.exports = { transform, verify };

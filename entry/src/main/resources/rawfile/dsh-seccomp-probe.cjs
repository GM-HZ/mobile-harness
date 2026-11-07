'use strict';
const fs = require('node:fs');
const { spawn } = require('node:child_process');
const http = require('node:http');
const assert = require('node:assert/strict');

async function main() {
  const bash = await new Promise((resolve, reject) => {
    const child = spawn('/bin/bash', ['-c', 'set -o pipefail; printf "DSH_SECCOMP_OK\\n" | grep -Fx DSH_SECCOMP_OK'],
      { cwd: '/tmp', detached: true, stdio: ['ignore', 'pipe', 'pipe'] });
    let output = '';
    child.stdout.on('data', chunk => { output += chunk; });
    child.on('error', reject);
    child.on('close', code => resolve({ output, code }));
  });
  assert.deepEqual(bash, { output: 'DSH_SECCOMP_OK\n', code: 0 });
  assert.ok(fs.realpathSync('/dsh/node_modules/@deepseek-ai/dsh/package.json'));
  const server = http.createServer((request, response) => response.end('ok'));
  try {
    await new Promise((resolve, reject) => {
      server.once('error', reject);
      server.listen(0, '127.0.0.1', resolve);
    });
    const code = await new Promise((resolve, reject) => {
      http.get('http://127.0.0.1:' + server.address().port, response => {
        response.resume();
        response.on('end', () => resolve(response.statusCode));
      }).on('error', reject);
    });
    assert.equal(code, 200);
  } finally {
    server.close();
  }
  console.log('DSH_SECCOMP_PROBE_OK');
}
main().catch(error => {
  console.error('DSH_SECCOMP_PROBE_FAILED', error.code ?? error.message);
  process.exitCode = 1;
});

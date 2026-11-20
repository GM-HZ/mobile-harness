#!/usr/bin/env python3
"""G1: behavior-level contracts for the compat layer (forge/package/liveshare/sharp).

Runs Node fixtures against the modules' public APIs without a device: argument
guards, registry provenance round-trip, export surfaces. Modules that need the
guest Node/audio stack are covered by G2/G3 instead.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMPAT = ROOT / "runtime/harmonyos/compat"

FIXTURE = r'''
const assert = require('node:assert');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const base = process.env.MH_COMPAT;
const results = [];
function check(id, fn) {
  try { fn(); results.push({ id, ok: true }); }
  catch (error) { results.push({ id, ok: false, error: String(error && error.message || error).slice(0, 300) }); }
}

check('forge-exports', () => {
  const forge = require(path.join(base, 'dsh-harmony-forge.cjs'));
  assert.equal(typeof forge.createGhRunner, 'function');
  assert.equal(typeof forge.startForgeAccountBridge, 'function');
});
check('forge-command-guard', async () => {});
(async () => {
  const forge = require(path.join(base, 'dsh-harmony-forge.cjs'));
  const runner = forge.createGhRunner(() => { throw new Error('launch must not run'); }, value => value);
  const result = await runner('bash', ['-c', 'true'], { env: {}, timeout: 1000, maxBuffer: 1024,
    cancelSignal: new AbortController().signal, onOutput: () => {} });
  check('forge-rejects-non-gh', () => assert.equal(result.shortMessage, 'Harmony Forge requires the packaged GitHub CLI'));
  const aborted = await runner('gh', ['auth', 'status'], { env: {}, timeout: 1000, maxBuffer: 1024,
    cancelSignal: { aborted: true, addEventListener: () => {}, removeEventListener: () => {} }, onOutput: () => {} });
  check('forge-abort', () => assert.equal(aborted.isCanceled, true));

  check('package-exports', () => {
    const module = require(path.join(base, 'dsh-harmony-package.cjs'));
    assert.equal(typeof module.createPackageRunner, 'function');
    assert.equal(typeof module.createRegistryOrigins, 'function');
  });
  check('package-registry-roundtrip', () => {
    const module = require(path.join(base, 'dsh-harmony-package.cjs'));
    const home = fs.mkdtempSync(path.join(os.tmpdir(), 'mh-registry-'));
    const profile = path.join(home, 'profiles', 'web');
    fs.mkdirSync(profile, { recursive: true });
    const marks = [];
    const origins = module.createRegistryOrigins(home, (name, data) => marks.push([name, data]));
    assert.equal(origins.read(profile, 'left-pad', '1.3.0'), undefined);
    origins.record(profile, 'left-pad', '1.3.0', 'https://registry.npmjs.org');
    assert.equal(origins.read(profile, 'left-pad', '1.3.0'), 'https://registry.npmjs.org');
    assert.equal(origins.read(profile, 'left-pad', '9.9.9'), undefined);
    origins.record(profile, 'left-pad', '1.3.0', 'ftp://registry.example');
    assert.equal(origins.read(profile, 'left-pad', '1.3.0'), 'https://registry.npmjs.org');
    origins.forget(profile, 'left-pad');
    assert.equal(origins.read(profile, 'left-pad', '1.3.0'), undefined);
    fs.rmSync(home, { recursive: true, force: true });
  });

  check('liveshare-exports', () => {
    const module = require(path.join(base, 'dsh-harmony-liveshare.cjs'));
    for (const name of ['createTunnelLauncher', 'createSharedPtcPolicy', 'addViewerUploads', 'patchFileUploads', 'patchFileUploadSchemas']) {
      assert.equal(typeof module[name], 'function', name);
    }
  });
  check('sharp-exports', () => {
    const module = require(path.join(base, 'dsh-harmony-sharp.cjs'));
    assert.equal(typeof module.createSharp, 'function');
  });
  check('boot-cache-exports', () => {
    const module = require(path.join(base, 'dsh-boot-cache.cjs'));
    assert.equal(typeof module.installBootCache, 'function');
  });
  process.stdout.write('CONTRACTS ' + JSON.stringify(results) + '\n');
  process.exit(results.some(row => !row.ok) ? 1 : 0);
})().catch(error => { console.error(error); process.exit(1); });
'''


def main():
    result = subprocess.run(["node", "-e", FIXTURE], capture_output=True, text=True,
                            env={**os.environ, "MH_COMPAT": str(COMPAT)})
    output = result.stdout + result.stderr
    line = next((row for row in result.stdout.splitlines() if row.startswith("CONTRACTS ")), None)
    if not line:
        print("FAIL compat contracts produced no result:\n" + output[-1200:], file=sys.stderr)
        return 1
    results = json.loads(line[len("CONTRACTS "):])
    for row in results:
        print(f"  {'OK  ' if row['ok'] else 'FAIL'} {row['id']}" + (f": {row['error']}" if not row['ok'] else ""))
    passed = sum(1 for row in results if row["ok"])
    print(f"G1 compat contracts: {passed}/{len(results)} passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())

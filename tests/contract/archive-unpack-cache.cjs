const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const enginePath = process.argv[2];
const engine = fs.readFileSync(enginePath, 'utf8');
const method = engine.match(/^  private async unpack\b[^{]*\{([\s\S]*?)^  }$/m);
assert.ok(method, 'DshEngine.unpack must be available to the archive cache contract');

const files = new Map();
const archiveName = 'fixture.zip';
const outputRoot = '/output';
const payload = `${outputRoot}/payload`;
const marker = `${outputRoot}/.validated-unpack-v2-${archiveName}`;
const modes = { WRITE_ONLY: 1, CREATE: 2, TRUNC: 4 };
let requested;
let failExtraction = false;
let extractions = 0;
let hadPriorMarkerOnFailure;

const context = {
  filesDir: '/private',
  resourceManager: {
    getRawFdSync: () => ({ fd: 'raw', offset: 0, length: requested.length }),
    closeRawFdSync() {},
  },
};
const fileIo = {
  OpenMode: modes,
  WhenceType: { SEEK_SET: 0 },
  accessSync: path => files.has(path),
  readTextSync(path) {
    assert.ok(files.has(path), `Missing fixture file ${path}`);
    return files.get(path);
  },
  openSync(path, mode) {
    if ((mode & modes.TRUNC) || !files.has(path)) files.set(path, '');
    return { fd: path };
  },
  closeSync() {},
  fsyncSync() {},
  lseek() {},
  async read(fd, buffer, { length }) {
    assert.equal(fd, 'raw');
    new Uint8Array(buffer).set(Buffer.from(requested).subarray(0, length));
    return length;
  },
  async write(fd, buffer, { length }) {
    return this.writeSync(fd, Buffer.from(buffer).toString('utf8', 0, length));
  },
  writeSync(fd, data) {
    files.set(fd, files.get(fd) + data);
    return Buffer.byteLength(data);
  },
  unlinkSync(path) { files.delete(path); },
  renameSync(from, to) {
    files.set(to, this.readTextSync(from));
    files.delete(from);
  },
};
const zlib = {
  ParallelStrategy: { PARALLEL_STRATEGY_PARALLEL_DECOMPRESSION: 0 },
  async decompressFile(archive, root) {
    assert.equal(root, outputRoot);
    assert.equal(fileIo.readTextSync(archive), requested);
    extractions++;
    if (failExtraction) {
      hadPriorMarkerOnFailure = files.has(marker);
      files.set(payload, `${requested}:partial`);
      throw new Error('fixture extraction interrupted');
    }
    files.set(payload, requested);
  },
};
// Use the ArkTS method body unchanged in an isolated context with file IO doubles.
const unpack = vm.runInNewContext(
  `(async function(context, name, root, identity) {${method[1]}})`,
  { fileIo, zlib, hilog: { info() {} } },
  { filename: enginePath },
);

function unpackIdentity(identity) {
  requested = identity;
  return unpack(context, archiveName, outputRoot, identity);
}

async function main() {
  const a = 'a'.repeat(64);
  const b = 'b'.repeat(64);
  for (const identity of [a, b, a]) {
    assert.equal(await unpackIdentity(identity), true);
    assert.equal(files.get(payload), identity);
  }
  assert.equal(await unpackIdentity(a), false, 'same-identity warm startup must reuse the layer');
  assert.equal(extractions, 3);

  failExtraction = true;
  await assert.rejects(unpackIdentity(b), /fixture extraction interrupted/);
  assert.equal(files.get(payload), `${b}:partial`);
  failExtraction = false;
  assert.equal(await unpackIdentity(a), true, 'a partial extraction must invalidate the previous layer');
  assert.equal(hadPriorMarkerOnFailure, false, 'invalidate the cached identity before the destination changes');
  assert.equal(files.get(payload), a);
  assert.equal(await unpackIdentity(a), false, 'the repaired layer must be reusable');
  assert.equal(extractions, 5);
}

main().catch(error => {
  console.error(error);
  process.exitCode = 1;
});

'use strict';
const fs = require('node:fs');
const vm = require('node:vm');
const addon = { exports: {} };
process.dlopen(addon, 'libptcnodeprobe.so');
const native = addon.exports;
const marker = 'ptc-fixture\0';
const amaro = PACKAGED_AMARO_PROBE_ENABLED ? require('./amaro.cjs') : undefined;

function readAsync() {
  if (!amaro) return fs.promises.readFile('read.txt', 'utf8');
  const input = "async function read(fs) { const value: string = await fs.promises.readFile('read.txt', 'utf8'); return value; }";
  const { code } = amaro.transformSync(input, { mode: 'strip-only' });
  return new vm.Script(code + '\nread').runInThisContext()(fs);
}

async function capture(fn) {
  try { return { value: await fn(), error: 0 }; }
  catch (error) { return { error: Number.isInteger(error.errno) ? -error.errno : -2 }; }
}

async function run() {
  // Initialize the real libuv filesystem thread pool before applying the filter.
  await fs.promises.stat(__filename);
  const confineError = native.confine();
  if (confineError) throw new Error('seccomp errno=' + confineError);
  const syncRead = await capture(() => fs.readFileSync('read.txt', 'utf8'));
  const asyncRead = await capture(readAsync);
  const directory = await capture(() => fs.promises.readdir('.'));
  const creat = fs.constants.O_CREAT | fs.constants.O_EXCL | fs.constants.O_WRONLY;
  const write = await capture(() => fs.promises.writeFile('created.txt', marker, { flag: creat }));
  const outside = await capture(() => fs.promises.readFile('../outside.txt', 'utf8'));
  const report = Buffer.alloc(40);
  [syncRead.error, asyncRead.error, write.error, outside.error,
    Number(syncRead.value === marker && asyncRead.value === marker),
    Number(write.error === 0), native.directOpenat2(), -1,
    directory.error ? -directory.error : Number(directory.value.join(',') === 'read.txt'),
    Number(Boolean(amaro) && asyncRead.value === marker)]
    .forEach((value, i) => report.writeInt32LE(value, i * 4));
  native.finish(report);
}

run().catch(error => {
  try { fs.writeSync(1, String(error.stack)); }
  finally { process.exit(1); }
});

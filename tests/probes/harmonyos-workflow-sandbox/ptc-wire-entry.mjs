// Staged in place of the pinned bootstrap's final launch statement.
const socket = openInheritedControlChannel();
const native = { exports: {} };
process.dlopen(native, 'libptcnodeprobe.so');
await readFile(new URL(import.meta.url));
await import('node:fs/promises');
process.chdir = directory => {
  if (directory !== 'workspace') throw new Error('Unexpected probe workspace');
};
const confineError = native.exports.confine();
if (confineError) throw new Error('PTC probe seccomp errno=' + confineError);
await runNodeMain(socket, Number(process.argv[2]), process);
native.exports.exit(process.exitCode || 0);

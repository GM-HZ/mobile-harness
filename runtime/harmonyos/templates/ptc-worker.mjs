const control = openInheritedControlChannel();
const allowedDirectory = process.argv[3];
const native = { exports: {} };
process.dlopen(native, 'libdshworkflow.so');
await readFile(new URL(import.meta.url));
await import('node:fs/promises');
process.chdir = directory => {
  if (directory !== allowedDirectory) throw new Error('PTC worker cannot change its authorized workspace');
};
native.exports.confinePtc();
await runNodeMain(control, Number(process.argv[2]), process);
native.exports.finish(process.exitCode ? 1 : 0);

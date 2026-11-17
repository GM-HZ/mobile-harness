const control = openInheritedControlChannel();
let currentDirectory = process.argv[3];
const native = { exports: {} };
process.dlopen(native, 'libdshworkflow.so');
await readFile(new URL(import.meta.url));
await import('node:fs/promises');
process.chdir = directory => {
  if (typeof directory !== 'string') throw new TypeError('Directory must be a string');
  const target = resolve(currentDirectory, directory);
  native.exports.changePtcDirectory(target);
  currentDirectory = target;
};
process.cwd = () => currentDirectory;
native.exports.confinePtc();
await runNodeMain(control, Number(process.argv[2]), process);
native.exports.finish(process.exitCode ? 1 : 0);

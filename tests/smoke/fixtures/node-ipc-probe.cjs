'use strict';
const { fork } = require('node:child_process');
if (process.argv[2] === 'child') {
  process.on('message', message => {
    process.send({ kind: 'pong', value: message.value + 1 }, () => process.disconnect());
  });
  process.send({ kind: 'hello', pid: process.pid });
} else {
  const start = Date.now();
  const log = value => process.stdout.write(JSON.stringify({ ms: Date.now() - start, ...value }) + '\n');
  const child = fork(__filename, ['child'], { silent: true, execArgv: [] });
  const timer = setTimeout(() => { log({ kind: 'timeout' }); child.kill('SIGKILL'); process.exitCode = 1; }, 12000);
  child.stdout.pipe(process.stdout); child.stderr.pipe(process.stderr);
  child.on('spawn', () => log({ kind: 'spawn', pid: child.pid, execPath: process.execPath }));
  child.on('error', error => { log({ kind: 'error', message: String(error) }); process.exitCode = 1; });
  child.on('message', message => {
    log(message);
    if (message.kind === 'hello') child.send({ value: 41 });
    if (message.kind === 'pong') {
      if (message.value !== 42) process.exitCode = 1;
      clearTimeout(timer);
    }
  });
  child.on('exit', (code, signal) => { clearTimeout(timer); log({ kind: 'exit', code, signal }); });
}

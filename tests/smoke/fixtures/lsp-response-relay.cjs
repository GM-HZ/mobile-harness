// Fault injection only: forwards a real server, holding one genuine hover reply.
// No initialize capabilities, source positions or semantic results are invented.
const { spawn } = require('node:child_process');
const fs = require('node:fs');
const [serverFile, marker] = process.argv.slice(2);
const child = spawn(process.execPath, [serverFile, '--stdio'], { stdio: ['pipe', 'pipe', 'pipe'] });
const hoverIds = new Set();
function frames(onFrame) {
  let buffer = Buffer.alloc(0);
  return chunk => {
    buffer = Buffer.concat([buffer, chunk]);
    for (;;) {
      const offset = buffer.indexOf('\r\n\r\n');
      if (offset < 0) return;
      const size = Number(/Content-Length:\s*(\d+)/i.exec(buffer.subarray(0, offset).toString())[1]);
      if (buffer.length < offset + 4 + size) return;
      const frame = buffer.subarray(0, offset + 4 + size);
      const message = JSON.parse(buffer.subarray(offset + 4, offset + 4 + size));
      buffer = buffer.subarray(offset + 4 + size);
      onFrame(message, frame);
    }
  };
}
process.stdin.on('data', frames((message, frame) => {
  if (message.method === 'textDocument/hover') hoverIds.add(message.id);
  // Ignore cancellation to test the provider's documented escalation path.
  if (message.method === '$/cancelRequest') return;
  child.stdin.write(frame);
}));
child.stdout.on('data', frames((message, frame) => {
  if (hoverIds.has(message.id) && message.result && !fs.existsSync(marker)) {
    fs.writeFileSync(marker, JSON.stringify({ realReply: message, childPid: child.pid }));
    return;
  }
  process.stdout.write(frame);
}));
child.stderr.pipe(process.stderr);
child.on('error', error => { console.error(error); process.exitCode = 1; });
child.on('exit', code => process.exit(code ?? 1));
process.stdin.on('end', () => child.stdin.end());

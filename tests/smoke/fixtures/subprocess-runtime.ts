import { once } from 'node:events';
import { createServer } from 'node:http';

const offset: number = 40;
const server = createServer((_request, response) => response.end('stock guest fetch'));
const listening = once(server, 'listening');
server.listen(0, '127.0.0.1');
try {
  await listening;
  const address = server.address();
  if (!address || typeof address === 'string') throw new Error('Expected a TCP server address');
  const response = await fetch(`http://127.0.0.1:${address.port}/`, { signal: AbortSignal.timeout(5000) });
  console.log(JSON.stringify({
    typescript: offset + 2,
    status: response.status,
    body: await response.text(),
    nodeOptions: process.env.NODE_OPTIONS,
  }));
} finally {
  server.closeAllConnections();
  server.close();
}

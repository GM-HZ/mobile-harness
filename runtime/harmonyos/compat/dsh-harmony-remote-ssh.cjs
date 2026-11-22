'use strict';

// SSH remote-host bridge: keep a local TCP listener that forwards into the
// remote DSH Web endpoint through an SSH channel, then exchange the DSH token
// for the browser cookie the WebView needs.
const fs = require('node:fs');
const http = require('node:http');
const net = require('node:net');
const crypto = require('node:crypto');

const CONFIG = '/tmp/remote-host.json';
const LAUNCH = '/tmp/dsh-client-launch';
const LOCAL_PORT = 19592;

function fingerprintOf(key) {
  return 'SHA256:' + crypto.createHash('sha256').update(key).digest('base64').replace(/=+$/, '');
}

function readConfig() {
  const config = JSON.parse(fs.readFileSync(CONFIG, 'utf8'));
  if (!config || config.kind !== 'ssh' || !config.sshHost || !config.sshUser) {
    throw new Error('invalid SSH remote configuration');
  }
  return config;
}

async function connectSsh(config) {
  const { Client } = require('/dsh/node_modules/ssh2');
  const client = new Client();
  return await new Promise((resolve, reject) => {
    let fingerprint = '';
    client.on('error', reject);
    client.on('ready', () => resolve({ client, fingerprint }));
    client.connect({
      host: config.sshHost,
      port: Number(config.sshPort || 22),
      username: config.sshUser,
      password: config.sshPassword || undefined,
      privateKey: config.sshKey || undefined,
      passphrase: config.sshPassphrase || undefined,
      readyTimeout: 25000,
      keepaliveInterval: 15000,
      keepaliveCountMax: 3,
      hostVerifier: key => {
        fingerprint = fingerprintOf(key);
        return !config.fingerprint || config.fingerprint === fingerprint;
      },
    });
  });
}

function createTunnel(client) {
  return new Promise((resolve, reject) => {
    const server = net.createServer(socket => {
      client.forwardOut('127.0.0.1', LOCAL_PORT, '127.0.0.1', LOCAL_PORT, (error, stream) => {
        if (error) {
          socket.destroy();
          return;
        }
        socket.pipe(stream).pipe(socket);
        socket.on('error', () => stream.destroy());
        stream.on('error', () => socket.destroy());
      });
    });
    server.on('error', reject);
    server.listen(LOCAL_PORT, '127.0.0.1', () => resolve(server));
  });
}

function exchangeToken(token) {
  return new Promise((resolve, reject) => {
    const request = http.get({
      host: '127.0.0.1',
      port: LOCAL_PORT,
      path: '/?token=' + encodeURIComponent(token),
      headers: { Host: '127.0.0.1:' + LOCAL_PORT },
    }, response => {
      const cookieHeader = response.headers['set-cookie'];
      const cookie = Array.isArray(cookieHeader) ? cookieHeader[0].split(';')[0] : undefined;
      response.resume();
      if (response.statusCode !== 303 || !cookie) {
        reject(new Error('SSH remote token exchange failed: HTTP ' + response.statusCode));
        return;
      }
      response.on('end', () => resolve(cookie));
    });
    request.on('error', reject);
    request.setTimeout(20000, () => request.destroy(new Error('SSH remote token exchange timed out')));
  });
}

function publish(cookie) {
  const session = { url: 'http://127.0.0.1:19592/', cookie };
  const temporary = LAUNCH + '.new';
  fs.writeFileSync(temporary, JSON.stringify(session), { mode: 0o600 });
  fs.renameSync(temporary, LAUNCH);
  console.log('SSH_REMOTE_READY', JSON.stringify({ url: session.url, cookieSet: true }));
}

async function start() {
  const config = readConfig();
  const connected = await connectSsh(config);
  console.log('SSH_REMOTE_CONNECTED', JSON.stringify({ host: config.sshHost, fingerprint: connected.fingerprint }));
  if (config.fingerprint && connected.fingerprint !== config.fingerprint) {
    throw new Error('SSH host key fingerprint mismatch');
  }
  await createTunnel(connected.client);
  const cookie = await exchangeToken(config.token || '');
  publish(cookie);
  connected.client.on('close', () => {
    console.error('SSH_REMOTE_CLOSED');
    process.exit(2);
  });
  connected.client.on('error', error => {
    console.error('SSH_REMOTE_ERROR', error.code || error.message);
  });
}

start().catch(error => {
  console.error('SSH_REMOTE_FAILED', error.code || error.message);
  try {
    fs.writeFileSync('/tmp/remote-host-error.json', JSON.stringify({ error: String(error) }) + '\n', { mode: 0o600 });
  } catch {}
  process.exit(1);
});

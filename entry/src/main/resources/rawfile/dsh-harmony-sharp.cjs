'use strict';
const fs = require('node:fs/promises');
const path = require('node:path');

function waitForGuest(child) {
  return new Promise((resolve, reject) => {
    let stderr = '';
    child.stdout.resume();
    child.stderr.on('data', chunk => { stderr = (stderr + chunk).slice(-2048); });
    const timer = setTimeout(() => {
      try { child.kill('SIGTERM'); } catch {}
    }, 20000);
    child.once('error', error => {
      clearTimeout(timer);
      reject(error);
    });
    child.once('exit', (code, signal) => {
      clearTimeout(timer);
      if (code === 0) resolve();
      else reject(new Error('Image decoder exited with ' + (signal || code) + ': ' + stderr));
    });
  });
}

function createSharp(root, launch) {
  async function run(source, operation, transforms) {
    const directory = await fs.mkdtemp(path.join(root, 'tmp/dsh-image-'));
    try {
      await fs.writeFile(path.join(directory, 'input'), source, { mode: 0o600 });
      await fs.writeFile(path.join(directory, 'request'), JSON.stringify({ operation, transforms }), { mode: 0o600 });
      await waitForGuest(launch('/workspace-native', 'exec /bin/node --jitless /dsh-harmony-sharp.cjs /tmp/' + path.basename(directory)));
      if (operation === 'decode') return;
      const info = JSON.parse(await fs.readFile(path.join(directory, 'result'), 'utf8'));
      if (operation === 'metadata') return info;
      return { data: await fs.readFile(path.join(directory, 'output')), info };
    } finally {
      await fs.rm(directory, { recursive: true, force: true });
    }
  }
  function image(source, transforms = {}) {
    return {
      metadata: () => run(source, 'metadata', transforms),
      verifyDecoded: () => run(source, 'decode', transforms),
      clone: () => image(source, { ...transforms }),
      rotate() { transforms.rotate = true; return this; },
      toColourspace(space) { transforms.space = space; return this; },
      resize(size) { transforms.size = size; return this; },
      jpeg(options) { transforms.encoder = 'jpeg'; transforms.encoding = options; return this; },
      webp(options) { transforms.encoder = 'webp'; transforms.encoding = options; return this; },
      toBuffer({ resolveWithObject } = {}) {
        if (!resolveWithObject || !transforms.encoder) throw new Error('Unsupported Harmony image output');
        return run(source, 'encode', transforms);
      },
    };
  }
  return image;
}

async function worker(directory) {
  const sharp = require('./dsh/node_modules/sharp');
  sharp.concurrency(1);
  const { operation, transforms } = JSON.parse(await fs.readFile(path.join(directory, 'request'), 'utf8'));
  const pipeline = sharp(await fs.readFile(path.join(directory, 'input')), {
    failOn: 'error',
    limitInputPixels: 100_000_000,
  });
  if (operation === 'metadata') {
    const info = await pipeline.metadata();
    for (const key of ['exif', 'xmp', 'iptc', 'icc', 'tifftagPhotoshop', 'comments']) {
      if (info[key] !== undefined) info[key] = true;
    }
    await fs.writeFile(path.join(directory, 'result'), JSON.stringify(info), { mode: 0o600 });
    return;
  }
  if (operation === 'decode') {
    await pipeline.raw().toBuffer();
    return;
  }
  if (operation !== 'encode' || !['jpeg', 'webp'].includes(transforms.encoder)) {
    throw new Error('Unknown image operation');
  }
  if (transforms.rotate) pipeline.rotate();
  if (transforms.space) pipeline.toColourspace(transforms.space);
  if (transforms.size) pipeline.resize(transforms.size);
  const { data, info } = await pipeline[transforms.encoder](transforms.encoding).toBuffer({ resolveWithObject: true });
  await fs.writeFile(path.join(directory, 'output'), data, { mode: 0o600 });
  await fs.writeFile(path.join(directory, 'result'), JSON.stringify(info), { mode: 0o600 });
}

if (require.main === module) {
  worker(process.argv[2]).catch(error => {
    console.error(error.message);
    process.exitCode = 1;
  });
} else {
  module.exports = { createSharp };
}

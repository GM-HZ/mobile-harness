'use strict';
const fs = require('node:fs/promises');
const path = require('node:path');
const { crc32 } = require('node:zlib');

function pngFacts(bytes) {
  if (bytes.length < 33 || bytes.toString('ascii', 12, 16) !== 'IHDR') throw new Error('Invalid PNG header');
  const colourType = bytes[25];
  let alpha = colourType === 4 || colourType === 6;
  let metadata = colourType !== 2 && colourType !== 6;
  let ended = false;
  for (let offset = 8; offset + 12 <= bytes.length;) {
    const length = bytes.readUInt32BE(offset);
    const type = bytes.toString('ascii', offset + 4, offset + 8);
    const end = offset + length + 8;
    if (end + 4 > bytes.length) throw new Error('Truncated PNG chunk');
    if (crc32(bytes.subarray(offset + 4, end)) !== bytes.readUInt32BE(end)) throw new Error('Invalid PNG checksum');
    offset = end + 4;
    if (type === 'tRNS') alpha = true;
    if (!['IHDR', 'PLTE', 'IDAT', 'IEND', 'sRGB', 'tRNS'].includes(type)) metadata = true;
    if (type === 'IEND' && length === 0) {
      ended = offset === bytes.length;
      break;
    }
  }
  if (!ended) throw new Error('Missing PNG end marker');
  return { hasAlpha: alpha, hasProfile: metadata, depth: bytes[24] === 16 ? 'ushort' : 'uchar' };
}

function jpegSegments(bytes) {
  const segments = [];
  let scan;
  if (bytes.readUInt16BE(bytes.length - 2) !== 0xffd9) throw new Error('Missing JPEG end marker');
  for (let offset = 2; offset + 4 <= bytes.length;) {
    const start = offset;
    if (bytes[offset++] !== 0xff) throw new Error('Invalid JPEG segment');
    while (bytes[offset] === 0xff) offset++;
    const marker = bytes[offset++];
    if (marker === 0xda) {
      scan = bytes.subarray(start);
      break;
    }
    const size = bytes.readUInt16BE(offset);
    if (size < 2 || offset + size > bytes.length) throw new Error('Truncated JPEG segment');
    const metadata = marker === 0xfe || (marker >= 0xe1 && marker <= 0xef) ||
      (marker === 0xe0 && bytes.toString('ascii', offset + 2, offset + 7) !== 'JFIF\0');
    segments.push({ data: bytes.subarray(start, offset + size), metadata });
    offset += size;
  }
  if (!scan) throw new Error('Missing JPEG scan');
  return { segments, scan };
}

function jpegFacts(bytes) {
  const { segments } = jpegSegments(bytes);
  return { hasAlpha: false, hasProfile: segments.some(segment => segment.metadata) };
}

function webpChunks(bytes) {
  if (bytes.length < 20 || bytes.readUInt32LE(4) + 8 !== bytes.length) throw new Error('Invalid WebP size');
  const chunks = [];
  for (let offset = 12; offset < bytes.length;) {
    if (offset + 8 > bytes.length) throw new Error('Truncated WebP header');
    const type = bytes.toString('ascii', offset, offset + 4);
    const size = bytes.readUInt32LE(offset + 4);
    const end = offset + 8 + size + (size % 2);
    if (end > bytes.length) throw new Error('Truncated WebP chunk');
    chunks.push({ type, data: bytes.subarray(offset, end) });
    offset = end;
  }
  return chunks;
}

const webpImageChunks = new Set(['VP8 ', 'VP8L', 'VP8X', 'ALPH', 'ANIM', 'ANMF']);
function webpFacts(bytes) {
  let alpha = false;
  let metadata = false;
  for (const { type, data } of webpChunks(bytes)) {
    if (type === 'VP8X' && data.length >= 9) alpha ||= (data[8] & 0x10) !== 0;
    if (type === 'VP8L' && data.length >= 13) alpha ||= (data[12] & 0x10) !== 0;
    if (type === 'ALPH') alpha = true;
    if (!webpImageChunks.has(type)) metadata = true;
  }
  return { hasAlpha: alpha, hasProfile: metadata };
}

// Image Kit can emit an ICC profile even with property copying turned off.
// The decoder has already converted the pixels to sRGB.
function stripEncodedMetadata(bytes, encoder) {
  if (encoder === 'jpeg') {
    const { segments, scan } = jpegSegments(bytes);
    return Buffer.concat([bytes.subarray(0, 2), ...segments.filter(segment => !segment.metadata)
      .map(segment => segment.data), scan]);
  }
  const header = Buffer.from(bytes.subarray(0, 12));
  const chunks = webpChunks(bytes).filter(chunk => webpImageChunks.has(chunk.type)).map(({ type, data }) => {
    if (type !== 'VP8X') return data;
    const flags = Buffer.from(data);
    flags[8] &= ~0x2c; // ICC, EXIF, XMP
    return flags;
  });
  header.writeUInt32LE(4 + chunks.reduce((sum, chunk) => sum + chunk.length, 0), 4);
  return Buffer.concat([header, ...chunks]);
}

function gifFacts(bytes) {
  const trailer = bytes[bytes.length - 1];
  if (trailer !== 0x3b) throw new Error('Missing GIF trailer');
  // A transparent colour is optional. The normalizer permits WebP to omit
  // alpha for opaque GIFs.
  return { hasAlpha: true, hasProfile: true };
}

const readFacts = { png: pngFacts, jpeg: jpegFacts, webp: webpFacts, gif: gifFacts };
const operation = { metadata: 0, decode: 1, jpeg: 2, webp: 3 };

function createNativeSharp(root, runImage) {
  function image(bytes, transforms = {}) {
    async function run(action, fd = -1) {
      const { width = 0, height = 0 } = transforms.size ?? {};
      return runImage(bytes, operation[action], width, height, transforms.rotate === true,
        transforms.quality ?? 85, fd);
    }
    return {
      async metadata() {
        const result = await run('metadata');
        return { depth: 'uchar', space: 'srgb', ...result, ...readFacts[result.format](bytes) };
      },
      verifyDecoded: () => run('decode'),
      clone: () => image(bytes, { ...transforms }),
      rotate() { transforms.rotate = true; return this; },
      toColourspace(space) {
        if (space !== 'srgb') throw new Error('Unsupported image colour space');
        return this;
      },
      resize(size) { transforms.size = size; return this; },
      jpeg({ quality }) { transforms.encoder = 'jpeg'; transforms.quality = quality; return this; },
      webp({ quality }) { transforms.encoder = 'webp'; transforms.quality = quality; return this; },
      async toBuffer({ resolveWithObject } = {}) {
        if (!resolveWithObject || !transforms.encoder) throw new Error('Unsupported image output');
        const directory = await fs.mkdtemp(path.join(root, 'tmp/dsh-image-'));
        const output = path.join(directory, 'output');
        try {
          const file = await fs.open(output, 'wx', 0o600);
          let info;
          try {
            info = await run(transforms.encoder, file.fd);
          } finally {
            await file.close();
          }
          const data = stripEncodedMetadata(await fs.readFile(output), transforms.encoder);
          return { data, info };
        } finally {
          await fs.rm(directory, { recursive: true, force: true });
        }
      },
    };
  }
  return source => image(Buffer.from(source.buffer, source.byteOffset, source.byteLength));
}

module.exports = { createNativeSharp };

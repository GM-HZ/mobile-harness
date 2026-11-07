'use strict';

const fs = require('node:fs');
const { syncBuiltinESMExports } = require('node:module');

function installBootCache(root) {
  const { existsSync, lstatSync, readFileSync, realpathSync } = fs;
  const nativeRealpath = realpathSync.native;
  const paths = new Map();
  const manifests = new Map();
  const stats = { realpath: 0, componentHits: 0, componentReads: 0, existsHits: 0, manifestHits: 0 };
  let active = false;
  try {
    active = nativeRealpath(root) === root && lstatSync(root).isDirectory();
  } catch {}

  function eligible(file) {
    return active && typeof file === 'string' && file.length < 1024 && file.startsWith(root + '/') &&
      !file.endsWith('/') && !/\/\.?\.?\/|\/\.{1,2}$/.test(file);
  }

  function kindOf(file) {
    if (file === root) return 'directory';
    const cached = paths.get(file);
    if (cached !== undefined) {
      stats.componentHits++;
      return cached;
    }
    const parent = kindOf(file.slice(0, file.lastIndexOf('/')));
    if (parent === 'unknown') return parent;

    let kind = 'missing';
    if (parent === 'directory') {
      stats.componentReads++;
      try {
        const entry = lstatSync(file);
        kind = entry.isSymbolicLink() ? 'unknown' : entry.isDirectory() ? 'directory' : 'entry';
      } catch (error) {
        if (error.code !== 'ENOENT' && error.code !== 'ENOTDIR') return 'unknown';
      }
    }
    paths.set(file, kind);
    return kind;
  }

  function canonical(file, options, fallback) {
    if (options !== undefined || !eligible(file)) return fallback(file, options);
    const kind = kindOf(file);
    if (kind !== 'entry' && kind !== 'directory') return fallback(file, options);
    stats.realpath++;
    return file;
  }

  if (active) {
    fs.realpathSync = (file, options) => canonical(file, options, realpathSync);
    fs.realpathSync.native = (file, options) => canonical(file, options, nativeRealpath);
    fs.existsSync = (file) => {
      if (!eligible(file)) return existsSync(file);
      const kind = kindOf(file);
      if (kind === 'unknown') return existsSync(file);
      stats.existsHits++;
      return kind !== 'missing';
    };
    fs.readFileSync = (file, options) => {
      if (!eligible(file) || !file.endsWith('/package.json') || options !== 'utf8' ||
          kindOf(file) !== 'entry') {
        return readFileSync(file, options);
      }
      if (manifests.has(file)) {
        stats.manifestHits++;
        return manifests.get(file);
      }
      const value = readFileSync(file, options);
      manifests.set(file, value);
      return value;
    };
    syncBuiltinESMExports();
  }

  return () => {
    if (active) {
      active = false;
      fs.realpathSync = realpathSync;
      fs.existsSync = existsSync;
      fs.readFileSync = readFileSync;
      syncBuiltinESMExports();
      paths.clear();
      manifests.clear();
    }
    return stats;
  };
}

module.exports = { installBootCache };

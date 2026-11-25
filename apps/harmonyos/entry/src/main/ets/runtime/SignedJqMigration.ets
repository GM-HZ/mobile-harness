import { common } from '@kit.AbilityKit';
import { fileIo } from '@kit.CoreFileKit';
import { hilog } from '@kit.PerformanceAnalysisKit';
import cryptoFramework from '@ohos.security.cryptoFramework';
import fileIO from '@ohos.fileio';

interface PinnedJq {
  url: string;
  member: string;
  guestPath: string;
  bytes: number;
  sha256: string;
  toolSha256: string;
  legacyLauncherSha256: string;
}

interface LegacyRegistration {
  name: string;
  url: string;
  member: string;
  argv0: string;
  tool: string;
}

function matchesDigest(path: string, maxBytes: number, expected: string): boolean {
  const stat = fileIo.lstatSync(path);
  if (!stat.isFile() || stat.size <= 0 || stat.size > maxBytes) return false;
  const file = fileIo.openSync(path, fileIo.OpenMode.READ_ONLY | fileIo.OpenMode.NOFOLLOW);
  try {
    const contents = new ArrayBuffer(stat.size);
    if (fileIo.readSync(file.fd, contents) !== stat.size) return false;
    const hash = cryptoFramework.createMd('SHA256');
    hash.updateSync({ data: new Uint8Array(contents) });
    const digest = hash.digestSync().data;
    let hexadecimal = '';
    for (const byte of digest) hexadecimal += byte.toString(16).padStart(2, '0');
    return hexadecimal === expected;
  } finally {
    fileIo.closeSync(file.fd);
  }
}

export function migrateSignedJq(context: common.UIAbilityContext, root: string): void {
  const launcher = root + '/usr/bin/jq';
  if (!fileIo.accessSync(launcher)) return;
  const installation = '/usr/lib/mh-tools/jq';
  let recognized = false;
  let temporary = '';
  try {
    const raw = context.resourceManager.getRawFileContentSync('jq-upgrade.json');
    let pin = '';
    for (const byte of raw) pin += String.fromCharCode(byte);
    const pinned = JSON.parse(pin) as PinnedJq;
    if (pinned.guestPath !== '/usr/bin/.mh-jq' || !matchesDigest(launcher, 4096, pinned.legacyLauncherSha256)) return;
    const receipt = root + installation + '/mh-tool.json';
    const receiptStat = fileIo.lstatSync(receipt);
    if (!receiptStat.isFile() || receiptStat.size > 4096) return;
    const installed = JSON.parse(fileIo.readTextSync(receipt)) as LegacyRegistration;
    if (installed.name !== 'jq' || installed.argv0 !== 'jq' || installed.tool !== installation + '/tool' ||
      installed.url !== pinned.url || installed.member !== pinned.member ||
      !matchesDigest(root + installation + '/download', pinned.bytes, pinned.sha256) ||
      !matchesDigest(root + installation + '/tool', pinned.bytes, pinned.toolSha256)) return;
    recognized = true;
    const pending = launcher + '.mh-migrate-' + Date.now();
    // O_WRONLY | O_CREAT | O_EXCL avoids touching a pre-existing staging file.
    const fd = fileIO.openSync(pending, 1 | 64 | 128, 0o755);
    temporary = pending;
    try {
      const contents = '#!/bin/sh\nexec /usr/bin/.mh-jq "$@"\n';
      if (fileIO.writeSync(fd, contents) !== contents.length) throw new Error('Incomplete jq launcher write');
      fileIo.fsyncSync(fd);
    } finally {
      fileIo.closeSync(fd);
    }
    if (!matchesDigest(launcher, 4096, pinned.legacyLauncherSha256)) return;
    fileIo.renameSync(temporary, launcher);
    temporary = '';
    hilog.info(0xD005, 'DSHClient', 'migrated existing jq to its signed launcher');
  } catch (_) {
    if (recognized) hilog.warn(0xD005, 'DSHClient', 'could not migrate existing jq launcher');
  } finally {
    if (temporary) {
      try { fileIo.unlinkSync(temporary); } catch (_) { /* staging cleanup is best-effort */ }
    }
  }
}

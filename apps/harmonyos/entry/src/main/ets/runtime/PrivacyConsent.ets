import { common } from '@kit.AbilityKit';
import { fileIo } from '@kit.CoreFileKit';

const POLICY_REVISION = '2026-11-13';

export function isAppGalleryBuild(context: common.UIAbilityContext): boolean {
  return context.resourceManager.getRawFileListSync('').includes('appgallery.patch.yml');
}

export function hasPrivacyConsent(context: common.UIAbilityContext): boolean {
  try {
    return fileIo.readTextSync(context.filesDir + '/privacy-consent') === POLICY_REVISION;
  } catch (_) {
    return false;
  }
}

export function savePrivacyConsent(context: common.UIAbilityContext): void {
  const path = context.filesDir + '/privacy-consent';
  const file = fileIo.openSync(path + '.new',
    fileIo.OpenMode.CREATE | fileIo.OpenMode.WRITE_ONLY | fileIo.OpenMode.TRUNC);
  try {
    if (fileIo.writeSync(file.fd, POLICY_REVISION) !== POLICY_REVISION.length) {
      throw new Error('Incomplete privacy consent write');
    }
    fileIo.fsyncSync(file.fd);
  } finally {
    fileIo.closeSync(file.fd);
  }
  fileIo.renameSync(path + '.new', path);
}

import { common } from '@kit.AbilityKit';
import { fileIo } from '@kit.CoreFileKit';
import { util } from '@kit.ArkTS';

const POLICY_REVISION = '2026-11-13';

export function isAppGalleryBuild(context: common.UIAbilityContext): boolean {
  return context.resourceManager.getRawFileListSync('').includes('appgallery.patch.yml');
}

export function getPrivacyPolicyUrl(context: common.UIAbilityContext): string {
  const resources = context.resourceManager;
  if (!resources.getRawFileListSync('').includes('appgallery-privacy-url')) return '';
  return util.TextDecoder.create('utf-8').decodeToString(resources.getRawFileContentSync('appgallery-privacy-url'));
}

export function hasPrivacyConsent(context: common.UIAbilityContext, policyUrl: string): boolean {
  try {
    return fileIo.readTextSync(context.filesDir + '/privacy-consent') === POLICY_REVISION + policyUrl;
  } catch (_) {
    return false;
  }
}

export function savePrivacyConsent(context: common.UIAbilityContext, policyUrl: string): void {
  const revision = new util.TextEncoder().encodeInto(POLICY_REVISION + policyUrl);
  const path = context.filesDir + '/privacy-consent';
  const file = fileIo.openSync(path + '.new',
    fileIo.OpenMode.CREATE | fileIo.OpenMode.WRITE_ONLY | fileIo.OpenMode.TRUNC);
  try {
    if (fileIo.writeSync(file.fd, revision.buffer) !== revision.byteLength) {
      throw new Error('Incomplete privacy consent write');
    }
    fileIo.fsyncSync(file.fd);
  } finally {
    fileIo.closeSync(file.fd);
  }
  fileIo.renameSync(path + '.new', path);
}

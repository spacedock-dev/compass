import type { StorageAccess } from './backend';
import { STORAGE_KEYS } from './keys';

export function createSampleInviteDismissal(access: StorageAccess) {
  let held = false;
  return {
    dismissed() {
      if (held) return true;
      const saved = access.attempt((storage) => storage.getItem(STORAGE_KEYS.sampleInvite));
      return saved.ok && saved.value === '1';
    },
    dismiss() {
      held = true;
      access.attempt((storage) => storage.setItem(STORAGE_KEYS.sampleInvite, '1'));
    },
  };
}

import type { StorageAccess } from './backend';
import { STORAGE_KEYS } from './keys';

export interface UpdateDismissals {
  dismissed(version: string): boolean;
  dismiss(version: string): void;
}

export function createUpdateDismissals(access: StorageAccess): UpdateDismissals {
  const held = new Set<string>();
  const read = () => {
    const result = access.attempt((backend) => backend.getItem(STORAGE_KEYS.updateDismissed));
    try {
      const saved: unknown =
        result.ok && result.value && result.value.length <= 2048 ? JSON.parse(result.value) : [];
      const local = [...held];
      held.clear();
      if (Array.isArray(saved))
        for (const version of saved.slice(-32)) {
          if (typeof version === 'string' && /^[0-9A-Za-z.+-]{1,32}$/.test(version))
            held.add(version);
        }
      // Previously held versions, including failed writes, take precedence over imports.
      for (const version of local) {
        held.delete(version);
        held.add(version);
      }
      const newest = [...held].slice(-32);
      held.clear();
      for (const version of newest) held.add(version);
    } catch {
      // A damaged or blocked store must not keep a notice on screen after Dismiss.
    }
  };
  return {
    dismissed(version) {
      read();
      return held.has(version);
    },
    dismiss(version) {
      read();
      held.add(version);
      const versions = [...held].slice(-32);
      held.clear();
      for (const item of versions) held.add(item);
      access.attempt((backend) =>
        backend.setItem(STORAGE_KEYS.updateDismissed, JSON.stringify(versions)),
      );
    },
  };
}

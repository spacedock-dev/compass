import type { StorageAccess } from './backend';

export type ConsentAnswer = 'granted' | 'declined';

export interface ConsentStore {
  /** `null` is unanswered, and a missing or unrecognised entry must never read as granted. */
  get(): ConsentAnswer | null;
  /** Anything but `granted` is recorded as `declined`. Returns whether storage took the write. */
  set(answer: ConsentAnswer): boolean;
}

/**
 * A refused write stays in force for this tab, even if storage still contains an older answer.
 * Otherwise storage lets another tab's answer or withdrawal take effect. The memo also covers
 * an unreadable store.
 */
export function createConsentStore(access: StorageAccess, key: string): ConsentStore {
  let memo: ConsentAnswer | null = null;
  let memoStands = false;
  return {
    get() {
      if (memoStands) return memo;
      const read = access.attempt((backend) => backend.getItem(key));
      if (read.ok && (read.value === 'granted' || read.value === 'declined')) {
        return read.value;
      }
      if (read.ok && read.value === null) return null;
      return memo;
    },
    set(answer) {
      const value: ConsentAnswer = answer === 'granted' ? 'granted' : 'declined';
      memo = value;
      const wrote = access.attempt((backend) => {
        backend.setItem(key, value);
      }).ok;
      memoStands = !wrote;
      return wrote;
    },
  };
}

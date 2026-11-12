import type { StorageAccess } from './backend';
import { STORAGE_KEYS, sessionKey, type SessionIdentity } from './keys';

/** Code points, matching the editor and the server's outcome lines. */
export const MEMO_LIMIT = 2000;

export type MemoKind = 'outcome' | 'focus';
export type MemoState = 'saved' | 'error';

/** `projectKey` is the unique repository key when the group has one, otherwise the label. */
export function memoKey(projectKey: string, focus: SessionIdentity | null, kind: MemoKind): string {
  const scope = focus ? sessionKey(focus) : 'project';
  return `${STORAGE_KEYS.memoPrefix}${encodeURIComponent(projectKey)}:${encodeURIComponent(scope)}:${kind}`;
}

/** Bound loaded values at whole code points. */
export function boundMemo(value: unknown): string {
  return typeof value === 'string' ? [...value].slice(0, MEMO_LIMIT).join('') : '';
}

export interface MemoStore {
  read(key: string, refresh?: boolean): string;
  write(key: string, value: string): MemoState;
  /** Undo this tab's writes only while storage still holds the last value it observed. */
  restore(key: string, original: string): MemoState | undefined;
  state(key: string): MemoState | undefined;
}

export function createMemoStore(access: StorageAccess): MemoStore {
  const drafts = new Map<string, string>();
  const observed = new Map<string, string | null>();
  const states = new Map<string, MemoState>();
  const write = (key: string, value: string): MemoState => {
    const bounded = boundMemo(value);
    drafts.set(key, bounded);
    const state: MemoState = access.attempt((backend) => backend.setItem(key, bounded)).ok
      ? 'saved'
      : 'error';
    if (state === 'saved') observed.set(key, bounded);
    states.set(key, state);
    return state;
  };
  return {
    read(key, refresh = false) {
      const draft = drafts.get(key);
      if (draft !== undefined && !refresh) return draft;
      const read = access.attempt((backend) => backend.getItem(key));
      if (!read.ok) {
        states.set(key, 'error');
        return draft ?? '';
      }
      if (draft !== undefined && observed.get(key) === read.value) return draft;
      drafts.delete(key);
      observed.set(key, read.value);
      if (draft !== undefined) states.delete(key);
      return boundMemo(read.value);
    },
    write,
    restore(key, original) {
      const draft = drafts.get(key);
      if (draft === undefined) return undefined;
      const read = access.attempt((backend) => backend.getItem(key));
      if (!read.ok) {
        drafts.set(key, boundMemo(original));
        states.set(key, 'error');
        return 'error';
      }
      if (read.value !== observed.get(key)) {
        drafts.delete(key);
        observed.set(key, read.value);
        states.delete(key);
        return undefined;
      }
      return draft === original ? undefined : write(key, original);
    },
    state: (key) => states.get(key),
  };
}

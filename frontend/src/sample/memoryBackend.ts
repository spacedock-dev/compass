import type { StorageBackend } from '../storage';

/* The sample's own storage: in memory, so nothing the reader does in it reaches the real page's browser
   storage. The live level is on for the sample without a key: it draws as though the switch were on and
   never holds a lease (`isSampleSession`). */
export function createSampleBackend(): () => StorageBackend {
  const data = new Map<string, string>();
  const backend: StorageBackend = {
    getItem: (key) => data.get(key) ?? null,
    setItem: (key, value) => {
      data.set(key, value);
    },
    removeItem: (key) => {
      data.delete(key);
    },
  };
  return () => backend;
}

import { useSyncExternalStore } from 'react';
import type { Row } from '../observed';
import type { Shell } from '../shell/context';
import { createIntentLog, type IntentLog, type LogSnapshot } from './logStore';

/* One Goal history store per shell, made on first use and kept for the document's life, so a view that unmounts and
   returns finds the rows and the retry deadline it left. It is subscribed to the board's STORE and not to
   what the reader is shown: an accepted board whose token moved must withhold retained words at once,
   not after a paint an open option list or a toggle's motion is holding back. */
const logs = new WeakMap<Shell, IntentLog>();

export function intentLogFor(shell: Shell): IntentLog {
  let log = logs.get(shell);
  if (log) return log;
  const { store } = shell.runtime;
  log = createIntentLog({ client: shell.runtime.client, clock: shell.clock });
  const owned = log;
  const sync = () => owned.sync(store.getSnapshot().data as unknown as Row | null);
  sync();
  store.subscribe(sync);
  logs.set(shell, log);
  return log;
}

export function useIntentLogState(log: IntentLog): LogSnapshot {
  return useSyncExternalStore(log.subscribe, log.getSnapshot);
}

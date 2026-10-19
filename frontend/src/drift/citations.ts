import { contextKey } from '../api/identity';
import { isRecord, type Row } from '../observed';
import type { BoardSnapshot } from '../store/board';
import { recordPastWindow, workSource } from '../intent/work';

/* Every id a stored reading cites, whichever criterion cites it. The list the reader's own press may send the
   page to read older record pages for. */
export function citedIdsOf(assessment: Row | null | undefined): string[] {
  const criteria = isRecord(assessment?.['criteria']) ? assessment['criteria'] : {};
  const ids = new Set<string>();
  for (const row of Object.values(criteria)) {
    if (!isRecord(row) || !Array.isArray(row['cites'])) continue;
    for (const id of row['cites']) if (id !== '') ids.add(String(id));
  }
  return [...ids];
}

/* When the pages read for a finished press have done their work: every cited id is one the page holds, or
   the record holds an entry from before the intent's window opened, so nothing in the window is unlisted.
   Read from the store on each call, so a page the reader's own Show more loaded in between counts. */
export function citationsHeld(
  snapshot: BoardSnapshot,
  scope: {
    readonly projectKey: string;
    readonly session: Row;
    readonly cited: readonly string[];
    readonly opened: number | null;
  },
): boolean {
  const record = snapshot.records.get(contextKey(scope.projectKey, scope.session as never));
  if (recordPastWindow(record, scope.opened)) return true;
  const source = workSource(snapshot.contexts, scope.projectKey, scope.session, record);
  const held = new Set((source.all ?? source.entries).map((entry) => entry.id));
  return scope.cited.every((id) => held.has(id));
}

/* The ids one stored criterion cites, loaded or not, in its order: what Show cited entries asks the record for.
   The shape's own `citedIds` are only the ones the page holds. */
export function citesOf(assessment: Row | null | undefined, key: string): string[] {
  const criteria = isRecord(assessment?.['criteria']) ? assessment['criteria'] : {};
  const row = criteria[key];
  if (!isRecord(row) || !Array.isArray(row['cites'])) return [];
  return [...new Set(row['cites'].map(String).filter(Boolean))];
}

/* Every entry id the page holds for a session: the record's pages and the board's context together. */
export function heldIds(
  snapshot: BoardSnapshot,
  scope: { readonly projectKey: string; readonly session: Row },
): Set<string> {
  const record = snapshot.records.get(contextKey(scope.projectKey, scope.session as never));
  const source = workSource(snapshot.contexts, scope.projectKey, scope.session, record);
  return new Set((source.all ?? source.entries).map((entry) => entry.id));
}

/* Whether every id one finding cites is an entry the page holds, with no window shortcut: a press of Show
   cited entries asks for these exact entries, and an entry from before the window still has a row to go to. */
export function entriesHeld(
  snapshot: BoardSnapshot,
  scope: { readonly projectKey: string; readonly session: Row; readonly cited: readonly string[] },
): boolean {
  const held = heldIds(snapshot, scope);
  return scope.cited.every((id) => held.has(id));
}

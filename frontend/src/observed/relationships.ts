import { isRecord, payloadSessionRows, trimmed, type Row } from './values';
import type { RouteInput } from '../router/grammar';

const NOT_LINKED = 'Declared parent is not on the board; not linked.';

export interface SessionLink {
  readonly key: string;
  readonly title: string;
  readonly route: RouteInput & { readonly view: 'session' };
  readonly source: Row;
}

const identity = (source: Row): string => `${String(source['harness'])}:${String(source['sid'])}`;
function linkTo(source: Row): SessionLink {
  return {
    key: identity(source),
    title: trimmed(source['title']) || String(source['sid']),
    route: {
      view: 'session',
      project: String(source['project'] ?? ''),
      harness: String(source['harness']),
      session: String(source['sid']),
    },
    source,
  };
}

interface LinkIndex {
  readonly byIdentity: ReadonlyMap<string, SessionLink>;
  readonly children: ReadonlyMap<string, readonly SessionLink[]>;
}
const indices = new WeakMap<Row, LinkIndex>();
function linksFor(payload: Row): LinkIndex {
  const held = indices.get(payload);
  if (held) return held;
  const rows = payloadSessionRows(payload);
  const byIdentity = new Map(rows.map((row) => [identity(row), linkTo(row)]));
  const children = new Map<string, SessionLink[]>();
  for (const row of rows) {
    const reference = row['declared_parent'];
    if (row['declared_parent_state'] !== 'linked' || !isRecord(reference)) continue;
    const parent = byIdentity.get(identity(reference));
    if (!parent) continue;
    const siblings = children.get(parent.key) ?? [];
    siblings.push(linkTo(row));
    children.set(parent.key, siblings);
  }
  const index = { byIdentity, children };
  indices.set(payload, index);
  return index;
}

/* The producer alone establishes links. A missing target never becomes a route guessed from an id. */
export function declaredRelations(payload: Row, source: Row | undefined) {
  const index = linksFor(payload);
  const find = (reference: unknown): SessionLink | null =>
    isRecord(reference) ? (index.byIdentity.get(identity(reference)) ?? null) : null;
  const parent =
    source?.['declared_parent_state'] === 'linked' ? find(source['declared_parent']) : null;
  const declared =
    source?.['declared_parent_state'] === 'linked' ||
    source?.['declared_parent_state'] === 'not_linked';
  const waiting = find(source?.['waiting_on_child']);
  const children = source ? (index.children.get(identity(source)) ?? []) : [];
  return {
    parent,
    parentText: parent ? `Child of ${parent.title}` : declared ? NOT_LINKED : '',
    waiting,
    waitingText: waiting
      ? `Waiting on child "${waiting.title}"`
      : source?.['waiting_on_child']
        ? 'Waiting on child not on the board'
        : '',
    children,
  };
}

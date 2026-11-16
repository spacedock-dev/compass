import { nativeSession } from './native';
import { endedAt, sessionKey, trimmed, type Row } from './values';

/* A label fallback carries no location evidence. The two measured sources already hide their paths
   behind keys, so neither a warning nor a filter needs to publish a directory. */
export function measuredLocation(row: Row): string {
  return ['git common directory', 'working directory path'].includes(
    String(row['project_identity_source']),
  )
    ? trimmed(row['project_key'])
    : '';
}

export function locationNote(rows: readonly Row[]): string {
  if (rows.length < 2) return '';
  const keys = new Set(rows.map(measuredLocation).filter(Boolean));
  const notes: string[] = [];
  if (keys.size > 1)
    notes.push(
      `${String(rows.filter((row) => measuredLocation(row)).length)} sessions share this display label across ${String(keys.size)} measured locations`,
    );
  const unknown = unmeasuredLocationNote(rows);
  if (unknown) notes.push(unknown);
  return notes.join('. ');
}

/* What one Sessions row says about its label. A row whose own location was measured does not carry
   the unmeasured count: on a board where 25 old worktrees were deleted, every measured row read
   "Location not measured for 25 sessions", as if it were about that row. */
export function rowLocationNote(rows: readonly Row[], row: Row): string {
  if (!measuredLocation(row)) return locationNote(rows);
  const keys = new Set(rows.map(measuredLocation).filter(Boolean));
  return keys.size > 1
    ? `${String(rows.filter((member) => measuredLocation(member)).length)} sessions share this display label across ${String(keys.size)} measured locations`
    : '';
}

export function unmeasuredLocationNote(rows: readonly Row[]): string {
  if (rows.length < 2) return '';
  const unknown = rows.filter((row) => !measuredLocation(row)).length;
  return unknown
    ? `Location not measured for ${String(unknown)} ${unknown === 1 ? 'session' : 'sessions'} with this display label`
    : '';
}

export interface LocationWarning {
  readonly kind: 'collision' | 'checkout';
  readonly title: string;
  readonly text: string;
  readonly members: readonly Row[];
}

export function locationWarnings(rows: readonly Row[]): LocationWarning[] {
  const warnings: LocationWarning[] = [];
  const note = locationNote(rows);
  if (note)
    warnings.push({
      kind: 'collision',
      title:
        new Set(rows.map(measuredLocation).filter(Boolean)).size > 1
          ? 'Label shared across locations'
          : 'Location not measured',
      text: note,
      members: rows,
    });
  const checkouts = new Map<string, Map<string, Row>>();
  for (const row of rows) {
    const checkout = trimmed(row['checkout_key']);
    const key = measuredLocation(row);
    if (
      !key ||
      !checkout ||
      endedAt(row) !== null ||
      !['working', 'needs_input'].includes(String(nativeSession(row)['state']))
    )
      continue;
    const members = checkouts.get(checkout) ?? new Map<string, Row>();
    members.set(sessionKey(row), row);
    checkouts.set(checkout, members);
  }
  const shared = [...checkouts.values()].filter((members) => members.size > 1);
  const members = shared.flatMap((group) => [...group.values()]);
  if (members.length)
    warnings.push({
      kind: 'checkout',
      title:
        shared.length === 1
          ? 'Concurrent sessions in one checkout'
          : 'Concurrent sessions in shared checkouts',
      text:
        shared.length === 1
          ? `${String(members.length)} sessions working or waiting in the same checkout`
          : `${String(members.length)} sessions working or waiting across ${String(shared.length)} shared checkouts`,
      members,
    });
  return warnings;
}

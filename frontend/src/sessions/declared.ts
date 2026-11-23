import { trimmed, type Row } from '../observed';
import type { SessionRow } from './rows';

export { declaredRelations } from '../observed/relationships';
export const groupOf = (source: Row | undefined): string => trimmed(source?.['group']);
/* Quoting names reserves the unquoted absence label even when a launcher uses those exact words. */
export const groupName = (value: string): string => (value ? JSON.stringify(value) : 'No group');
export const groupLabel = (source: Row | undefined): string => {
  const group = groupOf(source);
  return group
    ? `Group: ${group}${source?.['group_source'] === 'parent' ? ' (from parent)' : ''}`
    : '';
};

/* Work only with already-kept rows: hierarchy never widens a filter or moves history into active work. */
export function nestRows(rows: readonly SessionRow[]): { row: SessionRow; depth: number }[] {
  const keys = new Set(rows.map((row) => `${row.session.harness}:${row.session.sid}`));
  const parentKey = (row: SessionRow) => row.relations.parent?.key;
  const children = new Map<string, SessionRow[]>();
  for (const row of rows) {
    const key = parentKey(row);
    if (!key) continue;
    const siblings = children.get(key) ?? [];
    siblings.push(row);
    children.set(key, siblings);
  }
  const output: { row: SessionRow; depth: number }[] = [];
  const seen = new Set<string>();
  const visit = (row: SessionRow, depth: number) => {
    if (seen.has(row.key)) return;
    seen.add(row.key);
    output.push({ row, depth });
    for (const child of children.get(`${row.session.harness}:${row.session.sid}`) ?? [])
      visit(child, depth + 1);
  };
  for (const row of rows) if (!keys.has(parentKey(row) ?? '')) visit(row, 0);
  for (const row of rows) visit(row, 0);
  return output;
}

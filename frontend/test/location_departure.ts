import type { AttentionModel, Subject } from '../src/attention/model';
import type { Row } from '../src/observed';

/* Recorded generated boards have no measured location sources. Change only their UI-owned
   disclosures; never rewrite published session titles or evidence that happens to quote them. */
const unknownNote = (text: string) =>
  text.replace(
    /^(\d+) sessions share this display label; shared location is not established$/,
    'Location not measured for $1 sessions with this display label',
  );

export function recordedLocationNotes<T>(value: T): T {
  if (Array.isArray(value)) return value.map(recordedLocationNotes) as T;
  if (!value || typeof value !== 'object') return value;
  const row = value as Row;
  if (row['scope'] === 'board' && row['kind'] === 'collision')
    return {
      ...row,
      title: 'Location not measured',
      src: 'Published project location evidence',
      nowText: unknownNote(String(row['nowText'])),
      nextText: 'Compare title, worktree, id and start time below',
      nextKnown: true,
    } as T;
  return Object.fromEntries(
    Object.entries(value).map(([key, item]) => [
      key,
      key === 'sharedLabelText' && typeof item === 'string'
        ? unknownNote(item)
        : recordedLocationNotes(item),
    ]),
  ) as T;
}

export function restateRecordedLocationNotes(root: ParentNode): void {
  for (const note of root.querySelectorAll(
    '.next-operation-collision,.next-project-collision,.next-project-detail-collision',
  )) {
    note.textContent = unknownNote(note.textContent ?? '');
  }
}

/* Location subjects, and the stops/tasks they used to absorb, now have their own behavioural tests
   in attention/location.test.tsx and Storybook. Keep the recorded comparison over every unaffected
   subject, all of its signals, and coverage. The excluded keys come only from the recorded model. */
export function restoredMemberKeys(recorded: AttentionModel): Set<string> {
  const existing = new Set(
    [...recorded.needs, ...recorded.risk.filter((row) => row.kind !== 'collision')].map(
      (row) => row.key,
    ),
  );
  return new Set(
    recorded.risk
      .filter((row) => row.kind === 'collision')
      .flatMap((row) => row.memberKeys ?? [])
      .filter((key) => !existing.has(key)),
  );
}

export function unchangedAttention(model: AttentionModel, restored: Set<string>): unknown {
  const keep = (subject: Subject) => subject.kind !== 'collision' && !restored.has(subject.key);
  const keyOf = (row: Row) =>
    `session:${JSON.stringify([String(row['harness'] || ''), String(row['sid'] || '')])}`;
  const removed = model.healthy.sessions.filter((row) => restored.has(keyOf(row)));
  const moving = removed.filter((row) => row['state'] === 'working').length;
  const quiet = removed.filter((row) => row['state'] === 'idle').length;
  return {
    ...model,
    needs: model.needs.filter(keep),
    risk: model.risk.filter(keep),
    close: model.close.filter(keep),
    next: model.next.filter(keep),
    healthy: {
      ...model.healthy,
      sessions: model.healthy.sessions.filter((row) => !restored.has(keyOf(row))),
      moving: model.healthy.moving - moving,
      quiet: model.healthy.quiet - quiet,
      unknown: model.healthy.unknown - (removed.length - moving - quiet),
      partial:
        model.healthy.partial -
        removed.filter((row) => Array.isArray(row['source_gaps']) && row['source_gaps'].length)
          .length,
    },
    counts: {
      ...model.counts,
      risk: model.counts.risk - model.risk.filter((row) => !keep(row)).length,
      close: model.counts.close - model.close.filter((row) => !keep(row)).length,
      next: model.counts.next - model.next.filter((row) => !keep(row)).length,
      moving: model.counts.moving - moving,
      quiet: model.counts.quiet - quiet,
      unknown: model.counts.unknown - (removed.length - moving - quiet),
    },
    representedSessionKeys: model.representedSessionKeys.filter((key) => !restored.has(key)).sort(),
  };
}

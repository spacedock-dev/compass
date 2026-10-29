import { nextNumber } from '../api/bootstrap';
import { contextKey } from '../api/identity';
import { parseFocusedSummary, type StoredSummary } from '../api/summary';
import { useDrift } from '../drift/context';
import { constraintName, driftAnswer, resultStale } from '../drift/result';
import { CLAIMS } from '../drift/sentences';
import { isOutcomeLine } from '../drift/shape';
import { useDisplayed } from '../shell/context';
import { placeDeparture, recordPositions, type Placement } from './summary';

export interface DepartureMark {
  readonly key: string;
  /** The constraint's name, as the departure card labels it. */
  readonly name: string;
  readonly placement: Placement;
}

export interface SummaryMarks {
  readonly summary: StoredSummary | null;
  /** Each current departure, by its constraint key, and where its evidence sits against the summary. */
  readonly departures: ReadonlyMap<string, DepartureMark>;
  /** Each marked phase, `block:phase`, and the departures whose evidence it holds. */
  readonly phases: ReadonlyMap<string, readonly DepartureMark[]>;
  /** When the reading behind the marks was made, where work has arrived since it; null while it is current. */
  readonly before: number | null;
}

const NONE: SummaryMarks = {
  summary: null,
  departures: new Map(),
  phases: new Map(),
  before: null,
};

/* Which summary phases hold evidence for a departure the current reading raised, read by both cards so each
   links to the other from one derivation. A reading marked not accurate, or one read against words since
   replaced, marks nothing: its departures are not the current account. Work since the reading does not clear
   them: the Drift card still draws the departure, and the entries it cites still sit in the same phases, so
   the two cards would otherwise disagree on every session that kept working after Analyze. */
export function useSummaryMarks(): SummaryMarks {
  const { model } = useDrift();
  const entry = useDisplayed((snapshot) =>
    snapshot.contexts.get(contextKey(model.projectKey, model.session as never)),
  );
  const focused = parseFocusedSummary(entry?.data);
  const summary = focused?.summary ?? null;
  const { shape, raw, annotation, entries } = model;
  if (!summary || !shape || !raw || !annotation || !model.annotate) return { ...NONE, summary };
  if (annotation['not_accurate'] === true) return { ...NONE, summary };
  const stale = resultStale(shape, raw, annotation, entries);
  if (stale?.superseded) return { ...NONE, summary };
  const answer = driftAnswer(shape, entries, model.source.scan);
  if (answer.kind !== 'departs') return { ...NONE, summary };
  const outcomes = shape.criteria.filter(
    (row) => row.key !== CLAIMS && isOutcomeLine(row.key),
  ).length;
  const positions = recordPositions(
    entries.map((row) => ({ id: String(row.id || ''), at: nextNumber(row.at) })),
    model.numbers,
  );
  const departures = new Map<string, DepartureMark>();
  const phases = new Map<string, DepartureMark[]>();
  for (const row of answer.departures) {
    const mark = {
      key: row.key,
      name: constraintName(row.key, outcomes),
      placement: placeDeparture(summary, row.citedIds, positions),
    };
    departures.set(row.key, mark);
    for (const place of mark.placement.phases)
      phases.set(place, [...(phases.get(place) ?? []), mark]);
  }
  const readAt = nextNumber(raw['read_at']);
  /* No stamp for an unreadable time, as the Drift card draws none for it. */
  return { summary, departures, phases, before: stale && readAt && readAt > 0 ? readAt : null };
}

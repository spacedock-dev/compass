import { nextNumber } from '../api/bootstrap';
import type { WorkEntry } from '../intent/work';
import { isRecord } from '../observed';
import { resultState } from './result';
import { CONSISTENT, DEPARTURE, type PriorAnswer } from './sentences';
import { criterion, isOutcomeLine, type Criterion, type Shape } from './shape';

/* An earlier departure the store kept beside the reading that replaced it, listed under that later reading
   unless the later one answers the line on the record. The store keeps every departure the next reading
   stopped finding; the page decides which to draw, because which entries a line rests on is resolved against
   the record here and not in the producer. A check, a written file or another departure answers the line on
   the record, and words the reader has since changed are not what it departed from. A line the later reading
   rests on the agent's message, or cannot tell about or has not reached, answers nothing, so it stays listed.
   Owner, 2026-10-30 and 2026-11-01: a re-reading keeps an earlier departure visible beside the later one. */

export interface PriorDeparture {
  readonly key: string;
  /** When the reading that found it was taken. */
  readonly readAt: number;
  /** The earlier departure, parsed by the same rules a reading's own row is. */
  readonly row: Criterion;
  /** Every id it cites, held or not: what a press of its citation asks the record for. */
  readonly cites: readonly string[];
  /** The standing reading's row for the same line. */
  readonly later: Criterion;
  /** How that row leaves the departure: resting on the agent's message, or unable to tell. */
  readonly answer: PriorAnswer;
}

/* The finding key a press on an earlier departure's card carries, kept apart from the standing reading's own key
   for the same line, which resolves against the standing row and its citations. */
export const PRIOR_FINDING = 'prior:';

export function priorDepartures(
  stored: unknown,
  shape: Shape | null,
  entries: readonly WorkEntry[],
): PriorDeparture[] {
  if (!shape || shape.malformed || !Array.isArray(stored)) return [];
  const newest = new Map<string, PriorDeparture>();
  for (const item of stored as unknown[]) {
    if (!isRecord(item) || !isRecord(item['criterion'])) continue;
    const key = String(item['key'] ?? '');
    const readAt = nextNumber(item['read_at']);
    if ((key !== 'goal' && !isOutcomeLine(key)) || readAt === null || readAt <= 0) continue;
    const later = shape.criteria.find((row) => row.key === key);
    if (!later?.clauseKnown) continue;
    const state = resultState(later);
    const answer: PriorAnswer | null =
      later.result === CONSISTENT && later.restsOn === 'message'
        ? 'said'
        : state === 'cant-tell' || state === 'not-reached'
          ? state
          : null;
    if (!answer) continue;
    const raw = item['criterion'];
    const clause = String(raw['clause'] ?? '').trim();
    if (!clause || clause !== later.clause.trim()) continue;
    const row = criterion(key, later.label, clause, raw, entries, '', false, shape.windowStart);
    /* A departure none of whose cited entries the page holds is demoted by the shape, as a reading's own is:
       a card has to reach at least one number. */
    if (row.result !== DEPARTURE) continue;
    const held = newest.get(key);
    const cites = Array.isArray(raw['cites'])
      ? [...new Set(raw['cites'].map(String).filter(Boolean))]
      : [];
    if (!held || readAt > held.readAt) newest.set(key, { key, readAt, row, cites, later, answer });
  }
  /* In the reading's own order: the goal, then each line. */
  return shape.criteria.flatMap((row) => {
    const prior = newest.get(row.key);
    return prior ? [prior] : [];
  });
}

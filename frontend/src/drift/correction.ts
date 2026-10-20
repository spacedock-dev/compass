import { nextNumber } from '../api/bootstrap';
import { annotationLines, type Annotation } from '../intent/annotation';
import { laterDirections, type WorkEntry, type WorkSource } from '../intent/work';
import type { Row } from '../observed';
import {
  CORRECTION_CAP,
  CLAIMS,
  DEPARTURE,
  STEER_HARNESSES,
  STEER_LEAVES_MARKED,
  STEER_LEAVES_OLDER,
  STEER_OFF_MARKED,
  STEER_OFF_OLDER,
  UNSUPPORTED,
} from './sentences';
import { failedChecksAfterPerson } from './result';
import { fmtDur } from './route';
import { evidenceAt, type Shape } from './shape';

/* Steer back: the server's correction, composed from the reader's words, each line's state and the cited
   entries' times (`correction.py`), shown for the reader to edit and copy. Copy only, and nothing goes to the
   session
   ([DEC-24](../../../docs/design-reading-a-session.md#dec-24-your-intent-is-a-drafted-goal-and-a-checklist-and-a-correction-is-yours-to-copy)
   item 7). Everything here is pure; the held state and the native editor are in `correctionState.ts` and
   `CorrectionEditor.tsx`. The legacy cockpit's `nextCockpitCorrection*` functions are the oracle. */

export type CorrectionPart = string | { readonly entry: string };

/* Characters as the server counts them (`correction._width`, the copy route's cap): code points, never
   UTF-16 units, so a correction of astral characters is neither refused nor cut on one side only. */
export function correctionLength(text: unknown): number {
  return [...String(text || '')].length;
}

export interface Edit {
  readonly head: string;
  readonly run: readonly string[];
  readonly tail: string;
}

/* The run of code points an edit inserted into `before` to give `typed`: the common head and tail, with the
   caret, where the field has one, deciding which of two equal runs moved. */
export function correctionEdit(before: string, typed: string, caret?: number | null): Edit {
  const was = [...before];
  const now = [...typed];
  let tail = 0;
  if (typeof caret === 'number' && caret >= 0 && caret <= typed.length) {
    const after = [...typed.slice(caret)];
    if (after.length <= was.length && before.endsWith(after.join(''))) tail = after.length;
  }
  let head = 0;
  const most = Math.min(was.length, now.length) - tail;
  while (head < most && was[head] === now[head]) head += 1;
  if (typeof caret !== 'number') {
    while (
      tail < Math.min(was.length, now.length) - head &&
      was[was.length - 1 - tail] === now[now.length - 1 - tail]
    ) {
      tail += 1;
    }
  }
  return {
    head: now.slice(0, head).join(''),
    run: now.slice(head, now.length - tail),
    tail: now.slice(now.length - tail).join(''),
  };
}

const JOINED = new RegExp(String.raw`^(?:\p{M}|\u200d|\ufe0e|\ufe0f)$`, 'u');

/* The leading whole characters of `run` that fit in `room` code points: by grapheme where the platform
   segments text, and otherwise never ending on a base whose combining mark or joined character is left
   behind. */
export function correctionWhole(run: readonly string[], room: number): string {
  if (room <= 0) return '';
  const text = run.join('');
  if (typeof Intl === 'object' && typeof Intl.Segmenter === 'function') {
    let kept = '';
    let count = 0;
    for (const { segment } of new Intl.Segmenter(undefined, { granularity: 'grapheme' }).segment(
      text,
    )) {
      const width = [...segment].length;
      if (count + width > room) break;
      kept += segment;
      count += width;
    }
    return kept;
  }
  let cut = Math.min(room, run.length);
  while (cut > 0 && cut < run.length && (JOINED.test(run[cut] ?? '') || run[cut - 1] === '‍')) {
    cut -= 1;
  }
  return run.slice(0, cut).join('');
}

/* An edit past the cap keeps the reader's existing text and cuts the inserted run, or null when the edit
   fits. A first version kept the first 2,000 code points of the whole value, so a paste in the middle cut
   the text's end and left a bare "e" where "é" had been split. */
export function correctionFit(
  before: string,
  typed: string,
  caret?: number | null,
  cap: number = CORRECTION_CAP,
): { readonly value: string; readonly caret: number } | null {
  if (correctionLength(typed) <= cap) return null;
  const edit = correctionEdit(before, typed, caret);
  const kept = correctionLength(edit.head) + correctionLength(edit.tail);
  const run = correctionWhole(edit.run, cap - kept);
  return { value: edit.head + run + edit.tail, caret: edit.head.length + run.length };
}

/* The parts as text: a placeholder is drawn as nothing. It read "(entry #n in Compass's activity list)" until
   the owner's ruling of 2026-10-20, which dropped it because the agent the text is pasted into never saw that
   list; the server now writes the reader's local time and, at the agent's own message, its words
   ([the amendment](../../../docs/design-reading-a-session.md#amended-2026-10-20-owner-local-time-and-quoted-words)).
   Placeholders stay in the parts, where `correctionStale` reads the cited ids. */
export function correctionText(parts: readonly CorrectionPart[] | null | undefined): string {
  return (parts || []).map((part) => (typeof part === 'string' ? part : '')).join('');
}

/* The reader's zone, minutes east of UTC, which the server draws the correction's times in rather than its own
   clock's: the page shows every other time in this zone. */
export function readerUtcOffset(at: Date = new Date()): number {
  return 0 - at.getTimezoneOffset() || 0;
}

export function correctionParts(parts: unknown): CorrectionPart[] | null {
  return Array.isArray(parts) &&
    parts.every(
      (part) =>
        typeof part === 'string' ||
        (part !== null && typeof part === 'object' && typeof (part as Row)['entry'] === 'string'),
    )
    ? (parts as CorrectionPart[])
    : null;
}

/* What composition read, as this page holds it at the press: the saved words' revision, how far a Keep
   settled, and when the stored reading was read. A change in any of them means the text may claim what the
   panel no longer does. A reading marked Not accurate adds a fourth element, since marking changes none of
   the three and a held correction would still carry the withdrawn departure and its explanation (review,
   2026-10-20); it is added only when marked, so every other stamp is the legacy page's. */
export function correctionStamp(annotation: Annotation | null | undefined): string {
  const assessment = annotation?.['assessment'];
  return JSON.stringify([
    nextNumber(annotation?.['revision']),
    nextNumber(annotation?.['settled_through']),
    assessment && typeof assessment === 'object'
      ? nextNumber((assessment as Row)['read_at'])
      : null,
    ...(annotation?.['not_accurate'] === true ? [true] : []),
  ]);
}

function recordRead(source: Pick<WorkSource, 'state'> | null | undefined): boolean {
  return Boolean(source && (source.state === 'read' || source.state === 'empty'));
}

export function correctionIds(
  source: Pick<WorkSource, 'state' | 'all' | 'entries'> | null | undefined,
): Set<string> | null {
  return recordRead(source)
    ? new Set((source?.all || source?.entries || []).map((entry) => String(entry.id || '')))
    : null;
}

/* The failed checks after the words, by the server's rule: the correction's "A check failed at" names the
   latest of them. */
export function failedChecks(
  session: Row,
  entries: readonly WorkEntry[],
  scan: Row | null | undefined = null,
): WorkEntry[] {
  return failedChecksAfterPerson(
    entries,
    scan?.['last_user_at'],
    nextNumber(session['annotation_window_start']) || 0,
  );
}

export function correctionFailedIds(
  session: Row,
  source: Pick<WorkSource, 'state' | 'all' | 'entries' | 'scan'> | null | undefined,
): string[] | null {
  return recordRead(source)
    ? failedChecks(session, source?.all || source?.entries || [], source?.scan).map((entry) =>
        String(entry.id || ''),
      )
    : null;
}

export interface HeldCorrection {
  /** Which composition this is, so a new one remounts the editor and an edit to one never does. */
  readonly id: number;
  open: boolean;
  pending: boolean;
  parts: CorrectionPart[] | null;
  text: string | null;
  edited: boolean;
  why: string;
  cue: '' | 'copied' | 'failed';
  stamp: string | null;
  cited: string[] | null;
  failed: string[] | null;
  stale?: boolean;
  recomposing?: boolean;
  recomposeText?: string;
  shownText?: string;
  copying?: boolean;
  restoring?: boolean;
  editWhy?: string;
  paintWhy?: string;
  compositionRefused?: string;
}

/* Whether the held correction was composed from a record that no longer holds: a stamp that moved, a cited
   entry gone, or a failed check it did not see, which would leave "A check failed at" naming an older one.
   An unread record says nothing either way, so it never marks one stale. */
export function correctionStale(
  held: HeldCorrection | null | undefined,
  annotation: Annotation | null | undefined,
  source: Pick<WorkSource, 'state' | 'all' | 'entries' | 'scan'> | null | undefined,
  session: Row | null,
): boolean {
  if (!held || !Array.isArray(held.parts)) return false;
  if (held.stale) return true;
  if (held.stamp !== null && held.stamp !== correctionStamp(annotation)) return true;
  const ids = correctionIds(source);
  if (ids && Array.isArray(held.cited) && held.cited.some((id) => !ids.has(id))) return true;
  const failed = session ? correctionFailedIds(session, source) : null;
  const seen = held.failed;
  return Boolean(failed && Array.isArray(seen) && failed.some((id) => !seen.includes(id)));
}

export interface SteerOffer {
  readonly departed: boolean;
  readonly claimed: boolean;
  readonly failed: boolean;
}

/* Whether there is anything to steer from, by the server's own rule (`correction.compose`) over what this
   page holds, or null: saved words, and a departure that survives in a reading of those words, a failed
   check after them, or a later direction. Claude Code only, as the copy route is, so a paste of it can be
   recognised coming back. A claim alone is a question and always secondary. */
export function steerOffer(input: {
  readonly session: Row;
  readonly annotation: Annotation | null | undefined;
  readonly source: WorkSource | null;
  readonly shape: Shape | null;
  readonly annotate: boolean;
  readonly drafted: boolean;
}): SteerOffer | null {
  const { session, annotation, source, shape } = input;
  if (!STEER_HARNESSES.includes(String(session['harness'] || ''))) return null;
  if (!input.annotate || input.drafted) return null;
  if (!String(annotation?.['goal'] || '').trim() && !annotationLines(annotation).length)
    return null;
  if (!source || (source.state !== 'read' && source.state !== 'empty')) return null;
  const entries = source.all || source.entries || [];
  const current = Boolean(
    annotation &&
      annotation['not_accurate'] !== true &&
      shape &&
      !shape.malformed &&
      shape.revisionRead !== null &&
      shape.revisionRead === nextNumber(annotation['revision']),
  );
  const departed = current && Boolean(shape) && (shape?.departures.length ?? 0) > 0;
  /* A claim the record contradicts or does not show is something to steer from too (`correction._claim_line`),
     read from the claims row itself: it is not a departure from the intent, so it never offers "Update
     intent instead". */
  const claimed =
    current &&
    Boolean(
      shape?.criteria.some(
        (row) => row.key === CLAIMS && [DEPARTURE, UNSUPPORTED].includes(row.result),
      ),
    );
  const failed = failedChecks(session, entries, source.scan).length > 0;
  return departed || claimed || failed ? { departed, claimed, failed } : null;
}

/* Why Steer back does not carry the departures the result lists, or "" where it does or the harness never
   offers it: the reading was marked inaccurate, or it read an earlier version of the intent. `steerOffer`
   keeps both rules; this only says them where the reader is looking. */
export function steerWithheld(input: {
  readonly session: Row;
  readonly annotation: Annotation | null | undefined;
  readonly shape: Shape | null;
  readonly offer: SteerOffer | null;
}): string {
  const { session, annotation, shape, offer } = input;
  if (!STEER_HARNESSES.includes(String(session['harness'] || ''))) return '';
  if (!annotation || !shape || shape.malformed || !shape.departures.length) return '';
  if (offer?.departed) return '';
  const marked = annotation['not_accurate'] === true;
  const older =
    shape.revisionRead !== null && shape.revisionRead !== nextNumber(annotation['revision']);
  if (!marked && !older) return '';
  if (offer) return marked ? STEER_LEAVES_MARKED : STEER_LEAVES_OLDER;
  return marked ? STEER_OFF_MARKED : STEER_OFF_OLDER;
}

/* The direction Update intent instead offers: the later direction a surviving departure cites, else the
   latest, else none. One already saved as a line is never offered again: adding it twice wrote a typed line
   away for a copy of one kept. */
export function offeredDirection(
  annotation: Annotation | null | undefined,
  entries: readonly WorkEntry[],
  session: Row,
  shape: Shape | null,
  draft: { readonly at: number | null } | null,
): string {
  const saved = new Set(
    annotationLines(annotation)
      .map((line) => line.sourceId)
      .filter(Boolean),
  );
  const later = laterDirections(annotation, entries, session, draft).filter(
    (entry) => !saved.has(String(entry.id || '')),
  );
  const ids = new Set(later.map((entry) => String(entry.id || '')));
  const cited = shape
    ? shape.departures.flatMap((row) => row.citedIds || []).find((id) => ids.has(String(id)))
    : null;
  if (cited) return String(cited);
  const last = later[later.length - 1];
  return last ? String(last.id || '') : '';
}

/* Whose check failed, said: under "Not checked yet" a bare "Check failed at #2.2" read as the drift check having
   failed. */
export const CHECK_FAILED_TRIGGER = 'A check the agent ran failed';

/* What put Steer back on offer, in one line: the entry, its number and its age. */
export function steerTrigger(input: {
  readonly offer: SteerOffer | null;
  readonly shape: Shape | null;
  readonly session: Row;
  readonly entries: readonly WorkEntry[];
  readonly numbers: ReadonlyMap<string, string>;
  readonly scan: Row | null | undefined;
  readonly generated: number;
}): string {
  const { offer, shape, session, entries, numbers, scan } = input;
  if (!offer) return '';
  /* A departure's first cited entry, which its result row and its reason line name: taking the latest of all
     its citations named "#4" here beside "Departs; evidence #3" on the same card. */
  const ids =
    offer.departed && shape
      ? shape.departures.flatMap((row) => (row.citedIds || []).slice(0, 1))
      : offer.claimed && shape
        ? shape.criteria.filter((row) => row.key === CLAIMS).flatMap((row) => row.citedIds || [])
        : [];
  const candidates =
    offer.failed && !ids.length
      ? failedChecks(session, entries, scan)
      : entries.filter((entry) => ids.includes(String(entry.id || '')));
  const fact = candidates.reduce<WorkEntry | null>(
    (last, entry) => (!last || (evidenceAt(entry) || 0) > (evidenceAt(last) || 0) ? entry : last),
    null,
  );
  if (!fact) return '';
  const at = evidenceAt(fact) || 0;
  const n = numbers.get(String(fact.id || ''));
  const age = at > 0 ? `${fmtDur(Math.max(0, input.generated - at))} ago` : 'time not recorded';
  const trigger = offer.departed
    ? 'Departure evidence'
    : offer.claimed
      ? 'Claim to check'
      : CHECK_FAILED_TRIGGER;
  return `${trigger}${n !== undefined ? ` at #${String(n)}` : ''} · ${age}`;
}

import { nextNumber } from '../api/bootstrap';
import { isRecord, type Row } from '../observed';
import { formatDuration } from '../shell/format';
import { SLOT_LABELS, SLOTS, type Slot } from '../delegation/capacityRows';

/* The capacity strip's facts, ported from `next-capacity.js` and held to it by the differential test. Every
   figure here is either measured or null, and a null stays null all the way to the column, which prints its
   absence: an unmeasured pace is never a zero, a window with no clock draws no tick, and a measured zero is
   kept apart from an absent reading. Nothing here reads the browser's clock; every instant is anchored on
   the payload's own `generated`, so the columns of one row cannot disagree by the age of the payload. */

export { SLOT_LABELS, SLOTS, type Slot };

/* How many rows the strip shows before the rest are counted. Three, matching the Attention sections'
   initial size, because a reader scanning two surfaces should not learn two different "and N more" rules. */
export const INITIAL_ROWS = 3;
/* Below this much of a window elapsed, a projection is arithmetic on almost no time: at 2% elapsed one point
   of drift moves the end time by hours. The row still shows it and states the basis beside it. */
export const THIN_BASIS = 0.1;
/* Mirrors of `quota.MAX_SCOPED_LIMITS` and `quota.MODEL_LABEL_CAP_CHARS`, re-applied here rather than
   trusted: `usage` reaches the page as untrusted collector output. */
export const MODEL_ROWS = 8;
export const MODEL_LABEL_CHARS = 40;

export interface ModelLimit {
  readonly label: string;
  readonly pct: number;
}

export interface StripRow {
  readonly harness: string;
  readonly slot: Slot;
  readonly pct: number;
  readonly elapsed: number | null;
  readonly windowSec: number | null;
  readonly resetAt: number | null;
  readonly remainingSec: number | null;
  readonly asOf: number | null;
  readonly thinBasis: boolean;
  readonly paceRatio: number | null;
  readonly windowPacePerMin: number | null;
  readonly recentPacePerMin: number | null;
  /** Measured at zero, as opposed to not measured at all. */
  readonly recentFlat: boolean;
  readonly recentSamples: number | null;
  readonly recentSpanSec: number | null;
  readonly windowMinutesLeft: number | null;
  readonly endsAt: number | null;
  readonly recentMinutesLeft: number | null;
  readonly left: number;
  readonly models: readonly ModelLimit[];
}

export const rowKey = (row: Pick<StripRow, 'harness' | 'slot'>): string =>
  `${row.harness}:${row.slot}`;

/* Per-model sub-limits as a label and a level, and deliberately nothing else. `quota._scoped_limits`
   publishes them with no `windowSec`, no `resetAt` and no `recent`, so every figure derived below is
   undefined for them, and borrowing the weekly row's clock would compose the reading the usage-quota ruling
   refuses ([DEC-12](docs/design-usage-quota.md#q-12)). A row with no usable label is dropped rather than
   published under a placeholder: an unnamed bar beneath the weekly one reads as a second weekly figure
   disagreeing with the first. An integer level, so a measured 0 is kept and a string or a fraction is
   refused rather than coerced into a percentage nobody published. */
export function modelLimits(raw: unknown): ModelLimit[] {
  if (!Array.isArray(raw)) return [];
  const models: ModelLimit[] = [];
  for (const entry of raw) {
    if (!isRecord(entry)) continue;
    const pct = entry['pct'];
    if (typeof pct !== 'number' || !Number.isInteger(pct)) continue;
    const label =
      typeof entry['label'] === 'string' ? entry['label'].trim().slice(0, MODEL_LABEL_CHARS) : '';
    if (!label) continue;
    models.push({ label, pct });
    if (models.length >= MODEL_ROWS) break;
  }
  return models;
}

function windowRow(entry: unknown, slot: Slot, generated: number): StripRow | null {
  if (!isRecord(entry) || entry['state'] !== 'ok') return null;
  const window = entry[slot];
  if (!isRecord(window)) return null;
  const pct = window['pct'];
  if (typeof pct !== 'number' || !Number.isInteger(pct)) return null;
  const windowSec = nextNumber(window['windowSec']);
  const resetAt = nextNumber(window['resetAt']);
  const remainingSec = resetAt === null ? null : resetAt - generated;
  /* A reset already in the past leaves the window UNTIMED, and that guard is the whole of what stops this
     surface publishing a false all-clear: a stale disk snapshot describes a window that has since rolled,
     and clamping `elapsed` to 1 there made the pace look tiny and the projected end enormous, rendered as
     "lasts, ~123% spare" over evidence that had expired. The inner clamp serves the other case: a vendor
     clock running ahead of ours puts `remainingSec` above `windowSec`, and pinning that to 0 keeps the tick
     on the bar. */
  let elapsed: number | null = null;
  if (windowSec !== null && windowSec > 0 && remainingSec !== null && remainingSec > 0) {
    elapsed = Math.max(0, Math.min(1, (windowSec - remainingSec) / windowSec));
  }
  const recent = isRecord(window['recent']) ? window['recent'] : null;
  const windowPacePerMin =
    elapsed !== null && elapsed > 0 && windowSec !== null && windowSec > 0
      ? pct / ((elapsed * windowSec) / 60)
      : null;
  /* The raw reading is kept beside the clamped one so a measured zero can be told from an absent one:
     "nothing was spent over the last half hour" is evidence, and the page must not print it as "not
     measured". */
  const recentRaw = recent ? nextNumber(recent['pctPerMin']) : null;
  const recentPacePerMin = recentRaw === null ? null : Math.max(0, recentRaw);
  const left = Math.max(0, 100 - pct);
  const minutesAt = (rate: number | null): number | null =>
    rate === null || rate <= 0 ? null : left / rate;
  const windowMinutesLeft = minutesAt(windowPacePerMin);
  const samples = recent?.['samples'];
  return {
    harness: String(entry['harness'] || ''),
    slot,
    pct,
    elapsed,
    windowSec,
    resetAt,
    remainingSec,
    asOf: nextNumber(entry['asOf']),
    thinBasis: elapsed !== null && elapsed < THIN_BASIS,
    paceRatio: elapsed !== null && elapsed > 0 ? pct / (elapsed * 100) : null,
    windowPacePerMin,
    recentPacePerMin,
    recentFlat: recentRaw === 0,
    recentSamples: typeof samples === 'number' && Number.isInteger(samples) ? samples : null,
    recentSpanSec: recent ? nextNumber(recent['spanSec']) : null,
    windowMinutesLeft,
    /* An instant on the payload's own clock rather than the browser's: every other time figure on the
       board is anchored on `generated`, and mixing anchors makes two columns of one row disagree. */
    endsAt: windowMinutesLeft === null ? null : generated + windowMinutesLeft * 60,
    recentMinutesLeft: minutesAt(recentPacePerMin),
    left,
    /* Only on the weekly row, because that is the window they are sub-limits of. Hanging them under
       `fiveH` would make them a fraction of a figure they were never measured against. */
    models: slot === 'week' && isRecord(entry) ? modelLimits(entry['models']) : [],
  };
}

/* Ranked by when the budget ends, earliest first, because that is the binding constraint and it is not the
   largest percentage: a window at 34% used with 12% elapsed runs dry before one at 88% used with 91%
   elapsed, and ranking on level would put them the wrong way round, which is the whole reason this surface
   exists rather than a sorted list of percentages. Windows that cannot be timed sort last, by level. */
export function stripRows(payload: unknown): StripRow[] {
  const source: Row = isRecord(payload) ? payload : {};
  const usage = Array.isArray(source['usage']) ? source['usage'] : [];
  const generated = nextNumber(source['generated']);
  if (generated === null) return [];
  const rows: StripRow[] = [];
  for (const entry of usage) {
    for (const slot of SLOTS) {
      const row = windowRow(entry, slot, generated);
      if (row) rows.push(row);
    }
  }
  rows.sort((left, right) => {
    const leftEnd = left.windowMinutesLeft;
    const rightEnd = right.windowMinutesLeft;
    if (leftEnd !== null && rightEnd !== null && leftEnd !== rightEnd) return leftEnd - rightEnd;
    if (leftEnd !== null && rightEnd === null) return -1;
    if (leftEnd === null && rightEnd !== null) return 1;
    if (left.pct !== right.pct) return right.pct - left.pct;
    return left.harness.localeCompare(right.harness) || left.slot.localeCompare(right.slot);
  });
  return rows;
}

/* `nextFormatDuration` answers null for anything it cannot format, and no sentence on this surface may
   print that. Callers guard the value first, so the fallback is a backstop rather than a rendering path. */
export function duration(seconds: unknown): string {
  return formatDuration(seconds) || 'an unmeasured span';
}

export function allowanceSentence(row: StripRow, source: string): string {
  const window = `${source} ${SLOT_LABELS[row.slot]} plan`;
  if (row.remainingSec === null) return `${window} · reset time not published.`;
  if (row.remainingSec <= 0) return `${window} · the published reset has passed.`;
  return `${window} · resets in ${duration(row.remainingSec)}.`;
}

const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'] as const;
const MONTHS = [
  'Jan',
  'Feb',
  'Mar',
  'Apr',
  'May',
  'Jun',
  'Jul',
  'Aug',
  'Sep',
  'Oct',
  'Nov',
  'Dec',
] as const;

/* Wall-clock words for an absolute instant, day-qualified for the reason `sessions.format_reset` is: a
   weekly window's budget can end days out, and an hour-of-day alone names the wrong day. Anchored on the
   payload's `generated` rather than on the browser clock, so this column and the countdown beside it cannot
   disagree by the age of the payload. */
export function clockWords(stamp: number | null, generated: number | null): string {
  if (stamp === null || generated === null) return '';
  const at = new Date(stamp * 1000);
  const ref = new Date(generated * 1000);
  const hhmm = `${String(at.getHours()).padStart(2, '0')}:${String(at.getMinutes()).padStart(2, '0')}`;
  if (at.toDateString() === ref.toDateString()) return hhmm;
  const ahead = stamp - generated;
  if (ahead >= 0 && ahead < 7 * 86400) return `${DAYS[at.getDay()] ?? ''} ${hhmm}`;
  return `${MONTHS[at.getMonth()] ?? ''} ${String(at.getDate()).padStart(2, '0')}`;
}

export type FillInk = 'unknown' | 'crit' | 'warn' | 'ok';

export function fillInk(row: Pick<StripRow, 'paceRatio'>): FillInk {
  if (row.paceRatio === null) return 'unknown';
  if (row.paceRatio >= 1.5) return 'crit';
  if (row.paceRatio >= 1) return 'warn';
  return 'ok';
}

export type Ends =
  | { readonly kind: 'spent' }
  | { readonly kind: 'not-projected' }
  | {
      readonly kind: 'projected';
      readonly clock: string;
      /** The observed span a thin projection rests on, said on both verdicts. */
      readonly basis: string | null;
      /** What the window turns over with, as an annotation on the time and never a replacement for it. */
      readonly spare: number | null;
    };

/* A spent budget is a measurement, not a missing projection. Without its own branch it fell through to the
   clock, and zero minutes left prints the present minute, which reads as a deadline still ahead. The thin
   basis is stated on both verdicts, not only the alarming one: a reassurance resting on six minutes of a
   five-hour window is the half a reader acts on. The instant is printed in every projected shape: where the
   budget outlasts the window this column once returned the spare INSTEAD of the time, and the reader then
   could not compare the budget's end with the reset. */
export function endsOf(row: StripRow, generated: number | null): Ends {
  if (row.left === 0) return { kind: 'spent' };
  if (row.windowMinutesLeft === null || row.windowPacePerMin === null)
    return { kind: 'not-projected' };
  const basis =
    row.thinBasis && row.elapsed !== null && row.windowSec !== null
      ? duration(row.elapsed * row.windowSec)
      : null;
  const spare =
    row.remainingSec !== null && row.windowMinutesLeft * 60 >= row.remainingSec
      ? Math.max(0, Math.round(row.left - row.windowPacePerMin * (row.remainingSec / 60)))
      : null;
  return { kind: 'projected', clock: clockWords(row.endsAt, generated), basis, spare };
}

export interface Spread {
  readonly project: string;
  readonly low: number;
  readonly high: number;
  readonly median: number;
  readonly count: number;
  /** Observed sessions with no closed working interval, which are not in the figure above. */
  readonly unmeasured: number;
}

/* How long this harness's sessions have actually run in the project that consumed the most measured working
   time, from the state transitions the history store already keeps. It is keyed on project and duration
   rather than on a prompt: sizing an unstarted task from its text was the issue's original mechanism and the
   part nobody does well. Publishing the spread with its count refuses to claim the next session will match.

   Scoped to one harness because the sentence above it is about one harness's budget, and a median drawn
   from another vendor's sessions invites a division nobody measured.

   Working time, not wall time. The store records what CHANGED, so a session's span is the sum of the
   intervals that OPENED with a `working` record and were closed by that session's next record: first-to-last
   would count every idle gap as run time. A session's last record closes nothing, so a trailing `working`
   contributes no span and the figure is biased low rather than invented. */
export function projectSpread(payload: unknown, harness: string): Spread | null {
  const source: Row = isRecord(payload) ? payload : {};
  const history = Array.isArray(source['history']) ? source['history'] : [];
  if (!history.length) return null;
  const bySid = new Map<
    string,
    { readonly project: string; readonly records: { at: number; state: string }[] }
  >();
  for (const record of history) {
    const row: Row = isRecord(record) ? record : {};
    const at = nextNumber(row['last_activity']);
    const sid = String(row['sid'] || '');
    const project = String(row['project'] || '');
    const from = String(row['harness'] || '');
    if (at === null || !sid || !project || from !== harness) continue;
    let session = bySid.get(sid);
    if (!session) {
      session = { project, records: [] };
      bySid.set(sid, session);
    }
    session.records.push({ at, state: String(row['state'] || '') });
  }
  const byProject = new Map<string, number[]>();
  const unmeasured = new Map<string, number>();
  for (const session of bySid.values()) {
    const ordered = session.records.sort((left, right) => left.at - right.at);
    let worked = 0;
    for (let index = 0; index < ordered.length - 1; index += 1) {
      const here = ordered[index];
      const next = ordered[index + 1];
      if (here && next && here.state === 'working') worked += next.at - here.at;
    }
    if (worked > 0) {
      const list = byProject.get(session.project) ?? [];
      list.push(worked);
      byProject.set(session.project, list);
    } else {
      /* Observed, but with no closed working interval inside the retained window. Counted rather than
         dropped: silently excluding these made the range and the median describe a subset while "from N
         observed" named only that subset. */
      unmeasured.set(session.project, (unmeasured.get(session.project) ?? 0) + 1);
    }
  }
  /* Selected on the SUM of a project's measured intervals, not on how many it has: this line helps the
     reader judge whether a project's typical session fits the budget left, so the project that consumed the
     most measured time answers it, and a sum is a measurement where a tally of sessions is not. The
     two-session floor stays on the SELECTED project rather than filtering the candidates, so a project that
     leads on one session publishes nothing at all: a range of one is the figure this line must never print,
     and the runner-up is not an answer to which project worked most. */
  let best: { project: string; list: number[]; worked: number } | null = null;
  for (const [project, list] of byProject) {
    const worked = list.reduce((total, span) => total + span, 0);
    if (best === null || worked > best.worked) best = { project, list, worked };
  }
  if (best === null || best.list.length < 2) return null;
  const sorted = [...best.list].sort((a, b) => a - b);
  /* Averaged for an even count, because the floor index returns the upper of the two middles and for
     exactly two sessions that is the maximum: the row then printed the same figure as its own range end and
     called it a median. */
  const mid = Math.floor(sorted.length / 2);
  const median =
    sorted.length % 2 ? (sorted[mid] ?? 0) : ((sorted[mid - 1] ?? 0) + (sorted[mid] ?? 0)) / 2;
  return {
    project: best.project,
    low: sorted[0] ?? 0,
    high: sorted[sorted.length - 1] ?? 0,
    median,
    count: sorted.length,
    unmeasured: unmeasured.get(best.project) ?? 0,
  };
}

/* How many of the withheld rows cannot be timed, over the withheld rows only, which is what the sentence
   beside it claims. Counting across every row described the hidden ones with a total that included the
   visible ones. */
export function untimedCount(rows: readonly StripRow[], shown: readonly StripRow[]): number {
  return rows.filter((row) => !shown.includes(row) && row.windowMinutesLeft === null).length;
}

/* The rows the strip draws and the one that is selected. The selected window keeps its identity by vendor
   and window key even when its rank falls below the initial rows (it takes the last visible place); it falls
   back to the first row only when its key is no longer published ([reader state](docs/design-reader-state.md#the-inventory)). */
export function selectRows(
  rows: readonly StripRow[],
  key: string,
): { readonly selected: StripRow; readonly shown: StripRow[] } | null {
  const first = rows[0];
  if (!first) return null;
  const selected = rows.find((row) => rowKey(row) === key) ?? first;
  const shown = rows.slice(0, INITIAL_ROWS);
  if (!shown.includes(selected)) shown[shown.length - 1] = selected;
  return { selected, shown };
}

/* `nextHarnessLabels`: the label each published harness goes by, falling back to its key. */
export function harnessLabels(payload: unknown): Map<string, string> {
  const source: Row = isRecord(payload) ? payload : {};
  const labels = new Map<string, string>();
  for (const harness of Array.isArray(source['harnesses']) ? source['harnesses'] : []) {
    const row: Row = isRecord(harness) ? harness : {};
    const key = String(row['key'] || '');
    if (key) labels.set(key, String(row['label'] || key));
  }
  return labels;
}

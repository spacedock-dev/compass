import { nextNumber } from '../api/bootstrap';
import { compatSessKey, contextKey } from '../api/identity';
import type { Annotation } from '../intent/annotation';
import type { WorkEntry, WorkSource } from '../intent/work';
import { entryNumbers, labelOrder } from '../intent/work';
import { clock, isRecord, type Row } from '../observed';
import type { ContextEntry } from '../store/board';
import { localRecordedTime, recordedTime } from './result';
import { fmtDur } from './route';
import {
  BLOCKER_LINES,
  CLAIMS,
  CONSISTENT,
  DEPARTURE,
  LEVEL_SCALE,
  LIVE_LEVEL_NAMES,
  REASON_LINES,
  UNSUPPORTED,
} from './sentences';
import { agentMessage, evidenceAt, type Shape } from './shape';

/* The Drift level: the live estimate (deterministic, from checks and file paths, never a model) and the
   analysis-derived level (the server's `levels.analysis_level` over the stored reading and the record as it
   is now, recomputed on every fetch and never stored). Each is drawn with its own source line, because "None
   or low" from a model and from a path count are different claims
   ([DEC-26](../../../docs/design-reading-a-session.md#dec-26-four-drift-levels-and-a-live-estimate-after-every-turn)).
   The legacy cockpit's `nextDrift*` functions are the oracle (`level.differential.test.ts`). */

/* The levels that read as a finding of drift: each needs a departure behind it. */
const ABOVE_LOW: readonly string[] = ['medium', 'high', 'extreme'];

export type Contexts = ReadonlyMap<string, ContextEntry>;

function workOf(
  contexts: Contexts,
  projectKey: string,
  session: Row,
  field: string,
): readonly Row[] {
  const entry = contexts.get(contextKey(projectKey, session as never));
  const data = entry?.data as unknown as Row | null | undefined;
  const sources = isRecord(data?.['sources']) ? data['sources'] : null;
  const work = sources && isRecord(sources['work']) ? sources['work'] : null;
  const rows = work?.[field];
  return Array.isArray(rows) ? (rows as Row[]) : [];
}

/* The focused context's live row for this session. A level measured against an earlier revision is about
   words the panel no longer shows, which `estimate` checks. */
export function liveRow(contexts: Contexts, projectKey: string, session: Row): Row | null {
  return (
    workOf(contexts, projectKey, session, 'live_levels').find(
      (row) => Boolean(row) && compatSessKey(row) === compatSessKey(session),
    ) ?? null
  );
}

export function analysisRow(contexts: Contexts, projectKey: string, session: Row): Row | null {
  return (
    workOf(contexts, projectKey, session, 'analysis_levels').find(
      (row) => Boolean(row) && compatSessKey(row) === compatSessKey(session),
    ) ?? null
  );
}

/* Whether any cited entry arrived after the reader's latest message: only then does the level point at
   something the reader has not already seen. */
function signalAnchored(row: Row, work: Pick<WorkSource, 'all' | 'entries' | 'scan'>): boolean {
  const entries = work.all || work.entries || [];
  const times = entries
    .filter((entry) => entry.type === 'user_message')
    .map((entry) => nextNumber(entry.at))
    .filter((at): at is number => at !== null && at > 0);
  const lastUser = nextNumber(work.scan?.['last_user_at']);
  if (lastUser !== null && lastUser > 0) times.push(lastUser);
  if (!times.length) return false;
  const anchor = Math.max(...times);
  const cites = Array.isArray(row['cites']) ? (row['cites'] as unknown[]) : [];
  return entries.some(
    (entry) => cites.includes(String(entry.id || '')) && (evidenceAt(entry) || 0) > anchor,
  );
}

/* "#a to #b": the first and last entries the activity list numbers inside the window the reading read, "#a"
   alone when they are one entry, and nothing when the list numbers none of them: "#n", never "turn n". */
export function driftRange(
  entries: readonly WorkEntry[],
  numbers: ReadonlyMap<string, string>,
  start: number | null,
  through: number | null,
): string {
  const inside = entries
    .map((entry) => {
      const at = nextNumber(entry?.at);
      const n = numbers.get(String(entry?.id || ''));
      return n !== undefined &&
        at !== null &&
        (start === null || at >= start) &&
        (through === null || at <= through)
        ? n
        : null;
    })
    .filter((n): n is string => n !== null)
    .sort(labelOrder);
  const first = inside[0];
  const last = inside.at(-1);
  if (first === undefined || last === undefined) return '';
  return first === last ? `#${first}` : `#${first} to #${last}`;
}

export interface Reasons {
  readonly first: string;
  readonly blockers: readonly string[];
}

/* Why a level is what it is, one page-owned sentence per closed token from `levels.REASONS`. A reason the
   level rests on reads first under the meter; what holds a level back from None or low reads behind "Why
   not None or low". A later direction is said as yours and unsettled, never as drift. An unknown token
   renders nothing: no producer text reaches the page through this field. */
export function driftReasons(
  level: string,
  tokens: unknown,
  cites: unknown,
  entries: readonly WorkEntry[],
  numbers: ReadonlyMap<string, string>,
  departing: ReadonlySet<string>,
  generated: number,
): Reasons {
  const said = Array.isArray(tokens) ? (tokens as unknown[]).map(String) : [];
  const cited = (Array.isArray(cites) ? (cites as unknown[]) : []).map(String);
  const byId = new Map(entries.map((entry) => [String(entry?.id || ''), entry]));
  const number = (test: (entry: WorkEntry | undefined, id: string) => boolean): string => {
    const id = cited.find((fid) => numbers.has(fid) && test(byId.get(fid), fid));
    return id ? `#${String(numbers.get(id))}` : '';
  };
  const failureLine = (): string => {
    const fid = cited.find((id) => {
      const fact = byId.get(id);
      return Boolean(fact) && fact?.subject === 'check' && fact?.result === 'failed';
    });
    const fact = fid ? byId.get(fid) : undefined;
    if (!fact) return 'A failed check is counted but its entry is not listed.';
    const at = evidenceAt(fact) || 0;
    const age = at > 0 ? `${fmtDur(Math.max(0, generated - at))} ago` : 'time not recorded';
    const n = fid ? numbers.get(fid) : undefined;
    return `${String(fact.summary || 'A check')} failed ${age}${n !== undefined ? ` at #${String(n)}` : ''}${fact.beforeLastChange ? '; files changed after it' : '; no passing re-run recorded'}.`;
  };
  const finders: Record<string, (entry: WorkEntry | undefined, id: string) => boolean> = {
    'failed-check': (entry) => entry?.subject === 'check' && entry?.result === 'failed',
    departure: (_entry, fid) => departing.has(fid),
    'claim-contradicted': (entry) => agentMessage(entry),
    'claim-not-shown': (entry) => agentMessage(entry),
  };
  const reasonLine = (token: string, n: string): string | undefined =>
    Object.hasOwn(REASON_LINES, token) ? REASON_LINES[token]?.(n) : undefined;
  if (level === 'not_enough') {
    const held = said
      .filter((token) => token !== 'intent-names-no-folder')
      .map((token) =>
        token === 'failed-check'
          ? failureLine()
          : (Object.hasOwn(BLOCKER_LINES, token) ? BLOCKER_LINES[token] : undefined) ||
            reasonLine(token, '') ||
            '',
      )
      .filter(Boolean);
    return { first: '', blockers: [...new Set(held)] };
  }
  const token = said.find((name) => Object.hasOwn(REASON_LINES, name));
  const finder = token && Object.hasOwn(finders, token) ? finders[token] : undefined;
  return {
    first:
      token === 'failed-check'
        ? failureLine()
        : token
          ? (reasonLine(token, finder ? number(finder) : '') ?? '')
          : '',
    blockers: [],
  };
}

const LIVE_TOKENS = [
  'failed-check',
  'pass-then-write',
  'writes-outside-folders',
  'most-writes-outside-folders',
  'scan-incomplete',
  'no-passing-check',
  'check-not-recorded',
  'background-run',
  'command-after-pass',
  'pass-older-than-read',
  'later-direction',
  'entries-not-listed',
  'intent-names-no-folder',
];

export function liveTokens(tokens: unknown): string[] {
  return [...new Set((Array.isArray(tokens) ? (tokens as unknown[]) : []).map(String))].filter(
    (token) => LIVE_TOKENS.includes(token),
  );
}

export interface EvidenceRow {
  readonly id: string;
  readonly label: string;
  readonly kind: string;
  readonly who: string;
  readonly eventLabel: string;
  readonly at: string;
  readonly result: string;
  readonly source: string;
  /** The row as the page draws it, in the reader's local time; the fields above are the retired page's. */
  readonly shown: {
    readonly head: string;
    readonly summary: string;
    readonly at: string;
    readonly result: string;
  };
}

/* The cited entries' own rows: what each is, who recorded it, and when, with the source one click away. A
   check carries the time its result arrived, or says it was not recorded. */
export function evidenceRows(
  ids: unknown,
  numbers: ReadonlyMap<string, string>,
  byId: ReadonlyMap<string, WorkEntry>,
): EvidenceRow[] {
  const held = [...new Set((Array.isArray(ids) ? (ids as unknown[]) : []).map(String))]
    .map((id) => byId.get(id))
    .filter((entry): entry is WorkEntry => Boolean(entry));
  return held.map((entry) => {
    const n = numbers.get(String(entry.id || ''));
    const harness = isRecord(entry.sourceSession) ? entry.sourceSession['harness'] : undefined;
    const check = entry.subject === 'check';
    const result = check
      ? recordedTime(entry.resultAt) === 'time not recorded'
        ? 'Result time not recorded.'
        : `Result recorded at ${recordedTime(entry.resultAt)}`
      : '';
    const at = nextNumber(entry.at);
    const kind = check
      ? `${entry.result || 'Recorded'} check`
      : entry.subject === 'write'
        ? 'File write'
        : agentMessage(entry)
          ? 'Agent message'
          : String(entry.type || 'Recorded entry');
    return {
      id: String(entry.id || ''),
      label: [
        n === undefined ? 'Entry not numbered in this view' : `#${String(n)}`,
        String(entry.summary || 'Recorded entry'),
      ].join(' · '),
      kind,
      who: [harness || 'Harness not recorded', entry.workerKind].filter(Boolean).join(' · '),
      eventLabel:
        entry.type === 'tool_report' && check && harness === 'claude'
          ? 'Call recorded at'
          : 'Evidence recorded at',
      at: recordedTime(entry.at),
      result,
      source: String(entry.source || 'Source not recorded'),
      shown: {
        head: [
          n === undefined ? 'Entry not numbered in this view' : `#${String(n)}`,
          kind,
          ...(at !== null && at > 0 ? [clock(at)] : []),
        ].join(' · '),
        summary: String(entry.summary || ''),
        at: localRecordedTime(entry.at),
        result: check
          ? localRecordedTime(entry.resultAt) === 'time not recorded'
            ? 'Result time not recorded.'
            : `Result recorded at ${localRecordedTime(entry.resultAt)}`
          : '',
      },
    };
  });
}

export interface Signals {
  readonly lines: readonly string[];
  readonly evidence: readonly EvidenceRow[];
  readonly limits: readonly string[];
}

/* The recorded signals a live estimate rests on, and the limits of it, from the closed token sets. */
function recordedSignals(
  row: Row,
  work: Pick<WorkSource, 'all' | 'entries'>,
  numbers: ReadonlyMap<string, string>,
  generated: number,
): Signals | null {
  const entries = work.all || work.entries || [];
  const byId = new Map(entries.map((entry) => [String(entry.id || ''), entry]));
  const tokens = liveTokens(row['reasons']);
  const level = String(row['level'] || '');
  const lines =
    level === 'not_enough'
      ? []
      : tokens
          .filter((token) => Object.hasOwn(REASON_LINES, token))
          .map((token) =>
            token === 'failed-check'
              ? driftReasons(level, [token], row['cites'], entries, numbers, new Set(), generated)
                  .first
              : (REASON_LINES[token]?.('') ?? ''),
          );
  const limits = tokens
    .filter(
      (token) =>
        Object.hasOwn(BLOCKER_LINES, token) &&
        (level !== 'not_enough' || token === 'intent-names-no-folder'),
    )
    .map((token) => BLOCKER_LINES[token] ?? '');
  const cites = Array.isArray(row['cites']) ? (row['cites'] as unknown[]) : [];
  if (cites.some((id) => !byId.has(String(id)))) limits.push('Some cited entries are not listed.');
  const evidence = evidenceRows(row['cites'], numbers, byId);
  if (!lines.length && !evidence.length && !limits.length) return null;
  return { lines, evidence, limits };
}

export interface DriftLevel {
  readonly level: string;
  readonly label: string;
  readonly source: string;
  readonly rose: string;
  readonly anchored: boolean;
  readonly signals: Signals | null;
  readonly reasons: Reasons;
  readonly analysis: boolean;
  /** The analysis line, "Intent against cited checks and messages."; the read time is the card header's. */
  readonly line: string;
  readonly range: string;
}

export interface LiveInput {
  readonly on: boolean;
  readonly harness: string;
  readonly contexts: Contexts;
  readonly projectKey: string;
  readonly session: Row;
  readonly annotation: Annotation | null;
  readonly work: WorkSource;
  readonly payload: Row;
  readonly generated: number;
}

/* "Rose from <level> at #<n>" is the server's replay with the number filled from this page's own list, and
   withheld where the list does not number that entry: recomputed, never stored. A level measured against a
   revision the panel no longer shows is not drawn. */
export function liveEstimate(input: LiveInput): DriftLevel | { readonly save: true } | null {
  if (input.harness !== 'claude' || !input.on) return null;
  const row = liveRow(input.contexts, input.projectKey, input.session);
  if (!row) return null;
  const level = String(row['level'] || '');
  if (level === 'no_live_level') return { save: true };
  const label = Object.hasOwn(LIVE_LEVEL_NAMES, level) ? LIVE_LEVEL_NAMES[level] : undefined;
  if (!label || nextNumber(row['revision']) !== (nextNumber(input.annotation?.['revision']) || 0)) {
    return null;
  }
  const at = nextNumber(row['computed_at']);
  const numbers = entryNumbers(input.session, input.work, input.payload);
  const n = numbers.get(String(row['rose_at'] || ''));
  const fromKey = String(row['rose_from'] || '');
  const from = Object.hasOwn(LIVE_LEVEL_NAMES, fromKey) ? LIVE_LEVEL_NAMES[fromKey] : undefined;
  const held = input.work.all || input.work.entries || [];
  return {
    level,
    label,
    source: at !== null ? `Live estimate · ${clock(at)}` : 'Live estimate',
    rose:
      from && n !== undefined && row['rose_from'] !== 'not_enough'
        ? `Rose from ${from} at #${String(n)}.`
        : '',
    anchored: signalAnchored(row, input.work),
    signals: recordedSignals(row, input.work, numbers, input.generated),
    reasons: driftReasons(
      level,
      liveTokens(row['reasons']),
      row['cites'],
      held,
      numbers,
      new Set(),
      input.generated,
    ),
    analysis: false,
    line: '',
    range: '',
  };
}

/* Whether every row of the intent stands consistent on what it names. The intent's rows only: the claims row
   is not the intent, and holding it to a consistent made None or low unreachable. */
export function analysisShown(shape: Shape): boolean {
  const intent = shape.criteria.filter((line) => line.key !== CLAIMS);
  return (
    intent.length > 0 &&
    intent.every((line) => line.result === CONSISTENT && Boolean(line.restsOn)) &&
    !shape.criteria.some((line) => line.key === CLAIMS && line.result === UNSUPPORTED)
  );
}

export interface AnalysisInput {
  readonly contexts: Contexts;
  readonly projectKey: string;
  readonly session: Row;
  readonly annotation: Annotation | null;
  readonly shape: Shape | null;
  readonly work: WorkSource;
  readonly payload: Row;
  readonly generated: number;
}

/* The analysis-derived level, drawn only for the reading the panel shows, only while that reading read the
   saved revision, and with its own source line. The page holds "None or low" to its own rows as well: a
   level of None or low beside a line the panel cannot show as consistent would reassure past what the rows
   say, so it reads "Not enough recorded yet" instead. */
export function analysisLevel(input: AnalysisInput): DriftLevel | null {
  const { annotation, shape } = input;
  const raw = annotation?.['assessment'];
  if (
    !raw ||
    !isRecord(raw) ||
    !shape ||
    shape.malformed ||
    annotation?.['not_accurate'] === true
  ) {
    return null;
  }
  const readAt = nextNumber(raw['read_at']);
  const row = analysisRow(input.contexts, input.projectKey, input.session);
  if (
    readAt === null ||
    !row ||
    nextNumber(row['read_at']) !== readAt ||
    nextNumber(row['revision_read']) !== nextNumber(raw['revision_read'])
  ) {
    return null;
  }
  /* A level for words the reader has replaced yields to the live estimate, as the live one does for a
     revision the panel does not show. */
  const current = nextNumber(annotation?.['revision']);
  if (current !== null && nextNumber(raw['revision_read']) !== current) return null;
  let level = String(row['level'] || '');
  if (!Object.hasOwn(LIVE_LEVEL_NAMES, level)) return null;
  /* The tokens the level is explained from: the server's, and the page's own where it withholds a level the
     server drew, so the sentence that says why none is drawn has something to say. */
  const tokens: unknown[] = Array.isArray(row['reasons']) ? [...(row['reasons'] as unknown[])] : [];
  if (level === 'none_or_low' && !analysisShown(shape)) {
    level = 'not_enough';
    tokens.push(
      shape.criteria.some((line) => line.key === CLAIMS && line.result === UNSUPPORTED)
        ? 'claim-not-shown'
        : 'line-not-shown-by-a-check',
    );
  } else if (ABOVE_LOW.includes(level) && shape.departures.length === 0) {
    /* A level above None or low is set from a departure the reading carries. The server also reads Medium
       from a contradicted claim or a pass followed by a change, and High from a failed check, and the page
       will not draw any of them beside a reading that found no departure: the level stood on nothing the
       reading said
       ([the amendment](../../../docs/design-reading-a-session.md#amended-2026-10-21-a-level-needs-a-departure)).
       What it did find is said in the verdict sentence instead. */
    level = 'not_enough';
  }
  const numbers = entryNumbers(input.session, input.work, input.payload);
  const held = input.work.all || input.work.entries || [];
  return {
    level,
    label: LIVE_LEVEL_NAMES[level] as string,
    source: 'Analysis',
    /* The read time is the card header's, once ("Analysis last run HH:MM"); this line says only what the
       analysis was made against. */
    line: 'Intent against cited checks and messages.',
    analysis: true,
    rose: '',
    anchored: false,
    signals: null,
    range: driftRange(
      held,
      numbers,
      nextNumber(raw['window_start']),
      nextNumber(raw['evidence_through']) ?? readAt,
    ),
    reasons: driftReasons(
      level,
      tokens,
      row['cites'],
      held,
      numbers,
      new Set(
        shape.criteria
          .filter((line) => line.result === DEPARTURE && line.key !== CLAIMS)
          .flatMap((line) => line.citedIds || [])
          .map(String),
      ),
      input.generated,
    ),
  };
}

/* A reading is stored once one was spent, including one this build refused to read: the validator nulls a
   refused assessment, so the assessment alone would call a checked session unchecked. */
export function readingStored(annotation: Annotation | null | undefined): boolean {
  return Boolean(
    annotation &&
      (annotation['assessment'] ||
        annotation['reading_refused'] === true ||
        (nextNumber(annotation['reading_count']) || 0) > 0),
  );
}

export function meterSegments(
  level: string,
): readonly { readonly level: string; readonly on: boolean }[] {
  const on = LEVEL_SCALE.indexOf(level);
  return LEVEL_SCALE.map((_name, index) => ({ level, on: on >= 0 && index <= on }));
}

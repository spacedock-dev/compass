/* The session summary as the server publishes it: the board's `summaries` grant block, a row's `summary.job`,
   and the focused `sources.summary` answer on `/api/project-context`
   ([the job and grant contract](../../../docs/design-session-summary.md#job-and-grant-contract),
   [the store contract](../../../docs/design-session-summary.md#store-contract)).

   Parsed rather than cast. Every string a model wrote stays a plain string here and is drawn as text, never as
   markup; a withheld string keeps its place as a marker with no text. A field the card does not draw is not
   kept. */

type Raw = Readonly<Record<string, unknown>>;

const record = (value: unknown): Raw | null =>
  value !== null && typeof value === 'object' && !Array.isArray(value) ? (value as Raw) : null;
const text = (value: unknown): string => (typeof value === 'string' ? value : '');
const count = (value: unknown): number =>
  typeof value === 'number' && Number.isInteger(value) && value >= 0 ? value : 0;
const time = (value: unknown): number | null =>
  typeof value === 'number' && Number.isFinite(value) && value > 0 ? value : null;
const ids = (value: unknown): readonly string[] =>
  Array.isArray(value)
    ? value.filter((id): id is string => typeof id === 'string' && id !== '')
    : [];
const list = (value: unknown): readonly Raw[] =>
  Array.isArray(value) ? value.map(record).filter((row): row is Raw => row !== null) : [];

export interface SummaryGrant {
  readonly consent: boolean;
  readonly off: boolean;
  readonly used: number;
  readonly limit: number;
  readonly retryAt: number | null;
  readonly reason: string;
  readonly noticeDue: boolean;
  readonly provider: string;
  readonly destination: string;
  readonly disclosure: string;
}

/** The board's `summaries` block, or null where this server publishes none. */
export function parseGrant(value: unknown): SummaryGrant | null {
  const raw = record(value);
  if (!raw || typeof raw['consent'] !== 'boolean') return null;
  return {
    consent: raw['consent'],
    off: raw['off'] === true,
    used: count(raw['used']),
    limit: count(raw['limit']),
    retryAt: time(raw['retry_at']),
    reason: text(raw['reason']),
    noticeDue: raw['notice_due'] === true,
    provider: text(raw['provider']),
    destination: text(raw['destination']),
    disclosure: text(raw['disclosure']),
  };
}

export type JobState =
  | 'running'
  | 'stopping'
  | 'complete'
  | 'partial'
  | 'cancelled'
  | 'refused'
  | 'interrupted';
const JOB_STATES: readonly string[] = [
  'running',
  'stopping',
  'complete',
  'partial',
  'cancelled',
  'refused',
  'interrupted',
];

export interface SummaryJob {
  readonly id: string;
  readonly state: JobState;
  /** The one-based part in flight, or zero before work. */
  readonly part: number;
  readonly parts: number;
  readonly reason: string;
  readonly finishedParts: readonly number[];
  readonly notice: Raw | null;
}

export function parseJob(value: unknown): SummaryJob | null {
  const raw = record(value);
  const state = text(raw?.['state']);
  if (!raw || !text(raw['id']) || !JOB_STATES.includes(state)) return null;
  return {
    id: text(raw['id']),
    state: state as JobState,
    part: count(raw['part']),
    parts: count(raw['parts']),
    reason: text(raw['reason']),
    finishedParts: Array.isArray(raw['finished_parts'])
      ? raw['finished_parts'].filter((n): n is number => typeof n === 'number' && n > 0)
      : [],
    notice: record(raw['notice']),
  };
}

export const jobActive = (job: SummaryJob | null): boolean =>
  job !== null && (job.state === 'running' || job.state === 'stopping');

/** Admitted text, or the place a withheld string held, with why. */
export type Shown =
  | { readonly text: string; readonly cut: boolean }
  | { readonly withheld: string };

/* The producer withholds a string holding a tick; one that reaches the page anyway is withheld here too,
   because a result is never a check mark
   ([No completion words](../../../docs/design-session-summary.md#no-completion-words)). */
const CHECK_GLYPH = /[\u221a\u2611\u2705\u2713\u2714\u{1f5f8}\u{1f5f9}]/u;

function shown(value: unknown, cut = false): Shown {
  const raw = record(value);
  if (raw) return { withheld: text(raw['reason']) || 'shape_fault' };
  const words = text(value);
  if (!words) return { withheld: 'shape_fault' };
  return CHECK_GLYPH.test(words.normalize('NFKC'))
    ? { withheld: 'completion_claim' }
    : { text: words, cut };
}

export type BulletKind = 'did' | 'said' | 'asked' | 'failed';
const KINDS: readonly string[] = ['did', 'said', 'asked', 'failed'];

export interface SummaryBullet {
  readonly text: Shown;
  /** Set by the server from what the citations are, never the model's proposal. */
  readonly kind: BulletKind;
  readonly cites: readonly string[];
  readonly citesCut: number;
}

export interface SummaryPhase {
  readonly title: Shown;
  readonly bullets: readonly SummaryBullet[];
  readonly bulletsCut: number;
}

export interface SummaryBlock {
  readonly first: string;
  readonly last: string;
  readonly entries: number;
  /** A part that could not be summarized: why, or null for a summarized part. */
  readonly gap: string | null;
  readonly phases: readonly SummaryPhase[];
  readonly withheldPhases: number;
  readonly phasesCut: number;
  readonly replyCut: boolean;
}

export interface OutOfDate {
  readonly kind: string;
  readonly reason: string | null;
  readonly affectedBlocks: readonly number[];
  readonly newEntries: number;
  readonly action: 'update' | 'summarize_again' | null;
}

export interface StoredSummary {
  readonly state: string;
  readonly reason: string | null;
  readonly startsAt: string | null;
  readonly lede: Shown | null;
  readonly ledeCites: readonly string[];
  readonly ledeReason: string | null;
  readonly blocks: readonly SummaryBlock[];
  /** The read behind the summary, as the source saw it. */
  readonly coverage: {
    readonly complete: boolean;
    readonly startOffset: number;
    readonly unread: readonly string[];
    readonly agentReplies: string;
  } | null;
  readonly madeAt: number | null;
  /** `claude:<model>:<prompt digest>`, informational. */
  readonly modelStamp: string;
  readonly outOfDate: OutOfDate | null;
}

/* `sources.summary.plan`: what a start would cost, planned from the outline's own read
   (docs/design-session-summary.md#the-focused-plan). Off a partial read the parts are a floor. */
export interface SummaryPlan {
  readonly reason: string;
  readonly complete: boolean;
  readonly parts: number;
  readonly windows: number;
  readonly calls: number;
  readonly minutes: number;
}

function parsePlan(value: unknown): SummaryPlan | null {
  const raw = record(value);
  if (!raw || typeof raw['complete'] !== 'boolean') return null;
  const counts = ['parts', 'windows', 'calls', 'minutes'];
  if (!counts.every((key) => Number.isSafeInteger(raw[key]) && Number(raw[key]) >= 0)) return null;
  return {
    reason: text(raw['reason']),
    complete: raw['complete'],
    parts: count(raw['parts']),
    windows: count(raw['windows']),
    calls: count(raw['calls']),
    minutes: count(raw['minutes']),
  };
}

export interface FocusedSummary {
  /** `ok` with a summary, `absent` with none, `unavailable` when the store or the match could not be read. */
  readonly state: 'ok' | 'absent' | 'unavailable';
  readonly reason: string;
  readonly summary: StoredSummary | null;
  readonly plan: SummaryPlan | null;
  readonly job: SummaryJob | null;
}

/* A kind the card does not know is withheld rather than drawn as plain work: text the server admitted under
   the said or asked speech licence would otherwise lose the speaker it was admitted for. */
function bullet(row: Raw): SummaryBullet {
  const kind = text(row['kind']);
  const known = KINDS.includes(kind);
  return {
    text: known ? shown(row['text'], row['cut'] === true) : { withheld: 'shape_fault' },
    kind: (known ? kind : 'did') as BulletKind,
    cites: ids(row['cites']),
    citesCut: count(row['cites_cut']),
  };
}

function phase(row: Raw): SummaryPhase {
  const cut = record(row['cut']);
  return {
    title: shown(row['title'], cut?.['title'] === true),
    bullets: list(row['bullets']).map(bullet),
    bulletsCut: count(cut?.['bullets']),
  };
}

function block(row: Raw): SummaryBlock | null {
  const first = text(row['first']);
  const last = text(row['last']);
  if (!first || !last) return null;
  const cut = record(row['cut']);
  const gap = row['gap'] === true ? text(row['reason']) || 'stopped' : null;
  return {
    first,
    last,
    entries: count(row['entries']),
    gap,
    phases: gap ? [] : list(row['phases']).map(phase),
    withheldPhases: count(record(row['withheld_phases'])?.['shape_fault']),
    phasesCut: count(cut?.['phases']),
    replyCut: cut?.['reply'] === true,
  };
}

function outOfDate(value: unknown): OutOfDate | null {
  const raw = record(value);
  if (!raw || !text(raw['kind'])) return null;
  const action = text(raw['action']);
  return {
    kind: text(raw['kind']),
    reason: text(raw['reason']) || null,
    affectedBlocks: Array.isArray(raw['affected_blocks'])
      ? raw['affected_blocks'].filter((n): n is number => typeof n === 'number' && n >= 0)
      : [],
    newEntries: count(raw['new_entries']),
    action: action === 'update' || action === 'summarize_again' ? action : null,
  };
}

function coverage(value: unknown): StoredSummary['coverage'] {
  const raw = record(value);
  if (!raw) return null;
  return {
    complete: raw['complete'] === true,
    startOffset: count(raw['start_offset']),
    unread: list(raw['unread']).map((region) => text(region['reason'])),
    agentReplies: text(raw['agent_replies']),
  };
}

function stored(raw: Raw): StoredSummary {
  const lede = record(raw['lede']);
  return {
    state: text(raw['state']),
    reason: text(raw['reason']) || null,
    startsAt: text(raw['starts_at']) || null,
    lede: lede
      ? lede['withheld'] === true
        ? { withheld: text(lede['reason']) || 'shape_fault' }
        : shown(lede['text'], lede['cut'] === true)
      : null,
    ledeCites: ids(lede?.['cites']),
    ledeReason: text(raw['lede_reason']) || null,
    blocks: list(raw['blocks'])
      .map(block)
      .filter((row): row is SummaryBlock => row !== null),
    coverage: coverage(raw['coverage']),
    madeAt: time(raw['made_at']),
    modelStamp: text(raw['model_stamp']),
    outOfDate: outOfDate(raw['out_of_date']),
  };
}

/** The focused answer's `sources.summary`, or null when the context carries none. */
export function parseFocusedSummary(context: unknown): FocusedSummary | null {
  const sources = record(record(context)?.['sources']);
  const raw = record(sources?.['summary']);
  if (!raw) return null;
  const job = parseJob(raw['job']);
  if (raw['exists'] === true)
    return { state: 'ok', reason: '', summary: stored(raw), job, plan: null };
  return {
    state: text(raw['state']) === 'absent' ? 'absent' : 'unavailable',
    reason: text(raw['reason']),
    summary: null,
    plan: raw['state'] === 'absent' ? parsePlan(raw['plan']) : null,
    job,
  };
}

/** The model a stored summary names, from its stamp; empty where the stamp names none. */
export function stampModel(stamp: string): string {
  const parts = stamp.split(':');
  return parts.length >= 3 ? (parts[1] ?? '') : '';
}

export interface LargestRead {
  readonly windows: number;
  readonly windowBytes: number;
  readonly calls: number;
  readonly seconds: number;
}

export function parseLargestRead(value: unknown): LargestRead | null {
  const raw = record(value);
  if (!raw) return null;
  return {
    windows: count(raw['windows']),
    windowBytes: count(raw['window_bytes']),
    calls: count(raw['calls']),
    seconds: count(raw['seconds']),
  };
}

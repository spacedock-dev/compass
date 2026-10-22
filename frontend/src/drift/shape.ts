import { nextNumber } from '../api/bootstrap';
import { annotationLines, OUTCOME_LINES_MAX, type Annotation } from '../intent/annotation';
import { conflictCandidates, type WorkEntry } from '../intent/work';
import { isRecord, type Row } from '../observed';
import { PROMPT_SOURCES } from '../sessions/intent';
import {
  ASSISTANT_ONLY,
  BASELINE_OPEN,
  CHECK_DOES_NOT_SHOW_IT,
  CHECK_READ_INCOMPLETE,
  CLAIM_UNCITED,
  CLAIMS,
  CLAUSE_UNRETAINED,
  CONSISTENT,
  CRITERION_KEYS,
  DEPARTURE,
  DERIVED_ONLY,
  FAILED_CHECK_ON_RECORD,
  FAILED_CHECK_UNREAD,
  GOAL_UNCLEAR_RESULT,
  GOAL_VERDICT_CHECKS,
  GOAL_VERDICT_KEYS,
  GOAL_VERDICT_WHY,
  MALFORMED,
  NOT_REACHED,
  OWN_WORDS_ONLY,
  RESULTS,
  RECORDED_WRITE,
  STORED_WHY,
  UNCITED,
  UNSUPPORTED,
  UNVERIFIABLE,
} from './sentences';

/* The shape contract, as a producer rather than a checklist. A reader-requested reading is held to seven
   rules that remove failure classes rather than measure a rate, built into `criterion` so the three worst
   outputs are unrenderable rather than rare: the word "met", a departure citing nothing, and a deliverable
   claim on a harness that publishes no work evidence. Every demotion lands on `not verifiable from
   available evidence`, which the ruling names as the safe direction
   ([DEC-17](../../../docs/design-reading-a-session.md#dec-17-the-shape-contract)). The legacy cockpit's
   `nextCockpitReadingCriterion` is the oracle (`shape.differential.test.ts`). */

const OUTCOME_LINE = /^line_([1-9][0-9]*)$/;

export function isOutcomeLine(key: string): boolean {
  const match = OUTCOME_LINE.exec(String(key));
  return key === 'output' || Boolean(match && Number(match[1]) <= OUTCOME_LINES_MAX);
}

export function namesConstraint(key: string): boolean {
  return key === 'goal' || key === CLAIMS || isOutcomeLine(key);
}

/* The constraints a reading's rows are drawn for, goal first and then each line in order: the constraints
   the READING read, from its own criteria, and never today's lines. A line typed after the reading was
   never asked, and drawing it made the row say the reading failed on it. `current` is a reading of the
   words shown now: then every line typed now was a line it read, and one it returned no result for is drawn
   as missing rather than left out. */
export function readingConstraints(
  rows: Row | null | undefined,
  annotation: Annotation | null | undefined,
  current = false,
): [string, string][] {
  const typed = current ? annotationLines(annotation).map((line) => `line_${String(line.k)}`) : [];
  const keys = new Set<string>([
    'goal',
    ...Object.keys(rows || {}).filter(namesConstraint),
    ...typed.filter((key) => !(rows?.['output'] && key === 'line_1')),
  ]);
  const order = (key: string): number =>
    key === 'goal'
      ? 0
      : key === 'output'
        ? 1
        : key === CLAIMS
          ? OUTCOME_LINES_MAX + 1
          : Number((OUTCOME_LINE.exec(key) ?? [])[1]);
  return [...keys]
    .sort((left, right) => order(left) - order(right))
    .filter((key) => Boolean(rows?.[key]) || String(annotation?.[key] || '').trim())
    .map((key): [string, string] => [
      key,
      key === 'goal'
        ? 'TYPED GOAL'
        : key === 'output'
          ? 'EXPECTED OUTCOME'
          : key === CLAIMS
            ? 'WHAT THE AGENT CLAIMED'
            : `EXPECTED OUTCOME · LINE ${String(order(key))}`,
    ]);
}

/* A message the server recognised as a correction the reader copied from Compass is Compass's words. */
export function readingCopied(entry: WorkEntry | null | undefined): boolean {
  return String(entry?.type || '') === 'user_message' && entry?.copied === true;
}

export function agentMessage(entry: WorkEntry | null | undefined): boolean {
  return String(entry?.type || '') === 'agent_message';
}

export function demonstratesWork(entry: WorkEntry | null | undefined): boolean {
  return Boolean(entry && entry.work === true);
}

/* `reading.evidence_at`: a check's result time where one was recorded, and its call time otherwise. It
   decides the window only; the numbering and every change comparison keep the call time. */
export function evidenceAt(
  entry: Pick<WorkEntry, 'resultAt' | 'at'> | null | undefined,
): number | null {
  const resultAt = nextNumber(entry?.resultAt);
  return resultAt !== null && resultAt > 0 ? resultAt : nextNumber(entry?.at);
}

/* `reading._before_window`: an entry whose evidence cannot be placed at or after the window's start. */
function beforeWindow(entry: WorkEntry, windowStart: number | null): boolean {
  const at = evidenceAt(entry) || 0;
  const start = windowStart === null ? 0 : windowStart;
  return at < start || (start > 0 && at <= 0);
}

/* Who wrote an evidence entry. A closed set on the person side, because the asymmetry in rule 7 turns on it
   and a truthy check would count every unfamiliar type as a person's words. An observer snapshot is
   Compass's own paraphrase of the session, so it is a third author. */
export function readingAuthor(entry: WorkEntry): 'person' | 'derived' | 'agent' {
  const type = String(entry.type || '');
  if (type === 'user_message' && entry.copied !== true) return 'person';
  if (type === 'gate_decision' && String(entry.by || '').startsWith('person:')) return 'person';
  if (readingCopied(entry)) return 'derived';
  return type === 'observer_snapshot' ? 'derived' : 'agent';
}

/* The page joins the server's private source binding to the current revision and the unique, non-copied
   parent entry. */
export function lineRequestFloors(
  session: Row,
  annotation: Annotation | null | undefined,
  source: {
    readonly lineRequests?: Row | null;
    readonly all?: readonly WorkEntry[];
    readonly entries?: readonly WorkEntry[];
  } | null,
): Record<string, number> {
  const bound = source?.lineRequests;
  if (
    !bound ||
    !annotation ||
    bound['harness'] !== session['harness'] ||
    bound['sid'] !== session['sid'] ||
    nextNumber(bound['revision']) !== nextNumber(annotation['revision'])
  ) {
    return {};
  }
  const entries = source.all || source.entries || [];
  const floors: Record<string, number> = {};
  const lines = isRecord(bound['lines']) ? bound['lines'] : {};
  for (let i = 1; i <= 6; i += 1) {
    const key = `line_${String(i)}`;
    const request = isRecord(lines[key]) ? lines[key] : null;
    const at = nextNumber(request?.['at']);
    const id = String(request?.['source_id'] || '');
    if (
      !(at !== null && at > 0) ||
      at > 253402300799 ||
      !id ||
      annotation[`${key}_source`] !== 'entry' ||
      annotation[`${key}_source_id`] !== id
    ) {
      continue;
    }
    const parents = entries.filter((entry) => String(entry.id || '') === id);
    const parent = parents[0];
    if (
      parents.length === 1 &&
      parent &&
      parent.type === 'user_message' &&
      !parent.copied &&
      nextNumber(parent.at) === at
    ) {
      floors[key] = at;
    }
  }
  return floors;
}

const PI_CHECK_SOURCE = 'Pi bash tool call';

function subjectlessPiCheck(entry: WorkEntry): boolean {
  return (
    String(entry.type || '') === 'result' && String(entry.source || '').startsWith(PI_CHECK_SOURCE)
  );
}

/* `reading.check_supports`, spelt for the entries the page holds: a check, on any harness, carries a verdict
   only as a run whose result arrived in the window, failed for a departure, passed, not before the last
   change and with no changing command after it for a consistent. A written path shows a write and no
   result, so it carries neither, and a subjectless Pi result an older build stored carries none. The one
   exception is a row the producer stored as `recorded-write`: the code, not the model, found that write
   inside or outside a folder the line names, so it carries that departure and no other verdict. */
export function checkSupports(
  entry: WorkEntry,
  result: string,
  windowStart: number | null,
  recordedWrite = false,
): boolean {
  const report = String(entry.type || '') === 'tool_report';
  if (!report && entry.subject !== 'check') return !subjectlessPiCheck(entry);
  if (entry.subject !== 'check') {
    const at = evidenceAt(entry);
    return (
      recordedWrite &&
      result === DEPARTURE &&
      entry.subject === 'write' &&
      at !== null &&
      at > 0 &&
      !beforeWindow(entry, windowStart)
    );
  }
  const at = evidenceAt(entry);
  if (at === null || at <= 0 || (windowStart !== null && at < windowStart)) return false;
  if (result === DEPARTURE) return entry.result === 'failed';
  if (result === CONSISTENT) {
    return (
      entry.result === 'passed' &&
      !entry.beforeLastChange &&
      !entry.changedAfter &&
      !entry.readIncomplete
    );
  }
  return false;
}

/* Rule 3: a citation resolves only when it names an entry the page holds AND that entry carries both a type
   and a source. A citation to nothing is the shape an invented departure takes. */
function citations(raw: Row | null | undefined, entries: readonly WorkEntry[]): WorkEntry[] {
  const byId = new Map(entries.map((entry) => [String(entry.id || ''), entry]));
  const cited = Array.isArray(raw?.['cites']) ? (raw['cites'] as unknown[]) : [];
  return cited
    .map((id) => byId.get(String(id)))
    .filter(
      (entry): entry is WorkEntry =>
        Boolean(entry) &&
        Boolean(String(entry?.type || '').trim()) &&
        Boolean(String(entry?.source || '').trim()),
    );
}

/* The cited ids no entry the page holds carries. Counted from the stored row, before any window or limit
   filter, because the question is only whether the page has the entry, not whether it counts. */
function countUnloaded(raw: Row | null | undefined, entries: readonly WorkEntry[]): number {
  const held = new Set(entries.map((entry) => String(entry.id || '')));
  const cited = Array.isArray(raw?.['cites']) ? (raw['cites'] as unknown[]) : [];
  return new Set(cited.map(String).filter((id) => !held.has(id))).size;
}

export interface Criterion {
  readonly key: string;
  readonly label: string;
  readonly clause: string;
  readonly clauseKnown: boolean;
  readonly claimEntry: WorkEntry | null;
  readonly recordEntry: WorkEntry | null;
  readonly result: string;
  readonly declared: boolean;
  readonly detail: string;
  readonly why: string;
  readonly restsOn: '' | 'tool' | 'message' | 'agent';
  readonly restsOnEntry: WorkEntry | null;
  readonly limit: string;
  readonly evidence: readonly string[];
  readonly citedIds: readonly string[];
  /* Cited ids the page holds no entry for. A press can read further back than the board's own record, so
     this is what a reader's Show more may resolve; it is a count, never a reason to change the result. */
  readonly unloaded: number;
  readonly coverage?: string;
}

function hasOwn(table: object, key: string): boolean {
  return Object.hasOwn(table, key);
}

export function criterion(
  key: string,
  label: string,
  clause: string,
  raw: Row | null | undefined,
  entries: readonly WorkEntry[],
  limit: string,
  unsettled: boolean,
  windowStart: number | null = null,
  scope = '',
  requestAt: number | null = null,
): Criterion {
  /* Refused like any citation that does not resolve. The producer never numbers such an entry, so this holds
     only for a reading stored before it stopped. */
  let cited = citations(raw, entries).filter(
    (entry) =>
      !beforeWindow(entry, windowStart) &&
      (requestAt === null || (nextNumber(entry.at) || 0) > requestAt),
  );
  const object = raw !== null && raw !== undefined && typeof raw === 'object';
  const declared = object ? String(raw['result'] || '') : '';
  const stored = object ? String(raw['why'] || '') : '';
  let limitText = limit || '';
  const claims = key === CLAIMS;
  /* `unsupported` is the claims row's alone; anywhere else it is a result outside the row's set. */
  const known = (
    claims
      ? RESULTS.filter((name) => name !== NOT_REACHED)
      : RESULTS.filter((name) => name !== UNSUPPORTED)
  ).filter((name) => name !== GOAL_UNCLEAR_RESULT || key === 'goal');
  let result = known.includes(declared) ? declared : UNVERIFIABLE;
  /* Rule 2, and the reason the default above is not `consistent`: silence is not a pass. */
  let why = result === declared ? '' : MALFORMED;
  if (result === NOT_REACHED && !['last-turn', 'mid-flight'].includes(scope)) {
    result = UNVERIFIABLE;
    why = MALFORMED;
  }
  /* The refusal takes no citation and no limit, and a later direction does not unsettle it: it is about the
     words alone, which the producer judged before it read the record. */
  const refused = result === GOAL_UNCLEAR_RESULT;
  if (result !== UNVERIFIABLE && !refused && !cited.length) {
    result = UNVERIFIABLE;
    why = UNCITED;
  }
  if (result !== UNVERIFIABLE && !refused && limit) {
    /* Rule 5. A departure is demoted too, which is stricter than the letter and the direction the ruling
       calls safe. `why` stays empty: the limit has its own row, and setting both printed the same sentence
       twice. */
    result = UNVERIFIABLE;
    why = '';
  }
  /* The claims row is independent of the intent, so an unsettled later direction never demotes it. */
  if (result !== UNVERIFIABLE && !refused && unsettled && !claims) {
    result = UNVERIFIABLE;
    why = BASELINE_OPEN;
  }
  if (object && Object.keys(raw).some((name) => !CRITERION_KEYS.includes(name))) {
    result = UNVERIFIABLE;
    why = MALFORMED;
  }
  if (stored && !hasOwn(STORED_WHY, stored)) {
    result = UNVERIFIABLE;
    why = MALFORMED;
  }
  if (result === GOAL_UNCLEAR_RESULT) {
    return {
      key,
      label,
      clause: clause || CLAUSE_UNRETAINED,
      clauseKnown: Boolean(clause),
      claimEntry: null,
      recordEntry: null,
      result,
      declared: true,
      detail: '',
      why: '',
      restsOn: '',
      restsOnEntry: null,
      limit: '',
      evidence: [],
      citedIds: [],
      unloaded: 0,
    };
  }
  let droppedCheck = false;
  let failedCited = false;
  if (result !== UNVERIFIABLE) {
    failedCited = cited.some(
      (entry) => entry.subject === 'check' && checkSupports(entry, DEPARTURE, windowStart),
    );
    const incompletePass =
      result === CONSISTENT &&
      cited.some(
        (entry) =>
          entry.readIncomplete &&
          checkSupports({ ...entry, readIncomplete: false }, result, windowStart),
      );
    const supporting = cited.filter((entry) =>
      checkSupports(entry, result, windowStart, stored === RECORDED_WRITE),
    );
    droppedCheck = supporting.length < cited.length;
    cited = supporting;
    if (!cited.length) {
      result = UNVERIFIABLE;
      why = incompletePass ? CHECK_READ_INCOMPLETE : CHECK_DOES_NOT_SHOW_IT;
    }
  }
  /* The claims row, as `reading._claims_rule` reads it: every result names the agent's message making the
     claim; a departure or a consistent also the entry contradicting or showing it, and that entry not only
     Compass's paraphrase. An `unsupported` is about absence, so the message is all it can cite. */
  const claimSaid = claims ? cited.filter(agentMessage) : [];
  const claimRecord = claims ? cited.filter((entry) => !agentMessage(entry)) : [];
  if (claims && result !== UNVERIFIABLE) {
    let token = '';
    if (!claimSaid.length) token = CLAIM_UNCITED;
    else if (result !== UNSUPPORTED && !claimRecord.length) {
      token = droppedCheck ? CHECK_DOES_NOT_SHOW_IT : CLAIM_UNCITED;
    } else if (
      result !== UNSUPPORTED &&
      claimRecord.every((entry) => readingAuthor(entry) === 'derived')
    ) {
      token = DERIVED_ONLY;
    } else if (
      result === CONSISTENT &&
      !claimRecord.some(
        (entry) => demonstratesWork(entry) || String(entry.type || '') === 'tool_report',
      )
    ) {
      /* `reading._claims_compared`: shown means shown by the work. */
      token = CLAIM_UNCITED;
    } else if (
      result === DEPARTURE &&
      !claimRecord.some(
        (entry) =>
          entry.subject === 'check' ||
          (nextNumber(entry.at) || 0) >=
            Math.min(...claimSaid.map((said) => nextNumber(said.at) || 0)),
      )
    ) {
      /* A contradiction at or after the claim; a check is its latest run. */
      token = CLAIM_UNCITED;
    }
    if (token) {
      result = UNVERIFIABLE;
      why = token;
    }
  }
  const shows = cited.filter(demonstratesWork);
  const authors = cited.map(readingAuthor);
  const derivedOnly = authors.length > 0 && authors.every((name) => name === 'derived');
  const agentSaid = cited.some(agentMessage);
  if (isOutcomeLine(key) && result !== UNVERIFIABLE && !shows.length && !agentSaid) {
    /* Rule 7, the Expected Output half: a verdict about the deliverable needs an entry that DEMONSTRATES
       work, or one of the agent's own messages. The reader's own request is neither. */
    result = UNVERIFIABLE;
    why = droppedCheck ? CHECK_DOES_NOT_SHOW_IT : ASSISTANT_ONLY;
  }
  if (result !== UNVERIFIABLE && derivedOnly) {
    /* A verdict resting only on Compass's own paraphrase is this board quoting itself. */
    result = UNVERIFIABLE;
    why = DERIVED_ONLY;
  }
  if (
    result === CONSISTENT &&
    !cited.some((entry) => readingAuthor(entry) === 'agent' || demonstratesWork(entry))
  ) {
    /* The reader restating what she wanted is the constraint, not the work, so agreeing with it is circular.
       A DEPARTURE on her own words is different and stays. */
    result = UNVERIFIABLE;
    why = droppedCheck ? CHECK_DOES_NOT_SHOW_IT : OWN_WORDS_ONLY;
  }
  if (result === CONSISTENT && failedCited && !shows.length) {
    result = UNVERIFIABLE;
    why = CHECK_DOES_NOT_SHOW_IT;
  }
  if (
    result === CONSISTENT &&
    (isOutcomeLine(key) || claims) &&
    !shows.length &&
    entries.some(
      (entry) => entry && entry.subject === 'check' && checkSupports(entry, DEPARTURE, windowStart),
    )
  ) {
    /* A line's consistent resting on no work beside a failed check this page holds, cited or not and sent or
       not. The producer said `failed-check-unread` where the prompt had no room for it. */
    result = UNVERIFIABLE;
    why = stored === 'failed-check-unread' ? FAILED_CHECK_UNREAD : FAILED_CHECK_ON_RECORD;
  }
  if (result === UNVERIFIABLE && !why && !limitText && hasOwn(STORED_WHY, stored)) {
    /* Only the gap the page's own derivation left. Rule 5's token draws the limit row; every other token is
       a reason under the result. Today's limit wins where both exist, because it describes the harness the
       reader is looking at now. */
    const sentence = STORED_WHY[stored] ?? '';
    if (stored === 'not-asked') limitText = sentence;
    else why = sentence;
  }
  /* What a consistent row names as its source, by the cited entry's type: a tool outcome is what the tool
     reported, never an inspection; otherwise what the session said, and where every agent-authored entry
     is one of the agent's messages, what the agent said. */
  const tool =
    result === CONSISTENT
      ? (cited.find(
          (entry) => String(entry.type || '') === 'tool_report' || entry.subject === 'check',
        ) ?? null)
      : null;
  const accounts =
    result === CONSISTENT && !tool ? cited.filter((entry) => readingAuthor(entry) === 'agent') : [];
  const said = accounts.find(agentMessage) ?? accounts[0] ?? null;
  const restsOn: Criterion['restsOn'] = tool
    ? 'tool'
    : said && accounts.every(agentMessage)
      ? 'message'
      : said
        ? 'agent'
        : '';
  const restsOnEntry = tool || said || null;
  return {
    key,
    label,
    /* The claims question carries no words of the reader's, and its heading names it, so it has no clause. */
    clause: claims ? '' : clause || CLAUSE_UNRETAINED,
    clauseKnown: !claims && Boolean(clause),
    claimEntry: claims && result !== UNVERIFIABLE ? (claimSaid[0] ?? null) : null,
    recordEntry:
      claims && result !== UNVERIFIABLE
        ? (claimRecord.find(
            (entry) => String(entry.type || '') === 'tool_report' || entry.subject === 'check',
          ) ??
          claimRecord[0] ??
          null)
        : null,
    result,
    /* Whether the stored row itself declared a verdict, before any limit. */
    declared: Boolean(declared) && declared !== UNVERIFIABLE,
    /* Only under a departure that survived every rule above: a demoted departure must not print its prose
       under the refusal of it. */
    detail: [DEPARTURE, NOT_REACHED].includes(result) ? String(raw?.['detail'] || '') : '',
    why,
    restsOn,
    restsOnEntry,
    limit: limitText,
    /* Mutually exclusive with `limit`, and never both blank: a row states its evidence or why it has none. */
    evidence: limitText ? [] : cited.map((entry) => `${entry.type} · ${entry.source}`),
    /* The ids behind `evidence`, after every filter above, so the activity list flags exactly what this row
       still rests on. */
    citedIds: limitText ? [] : cited.map((entry) => String(entry.id || '')),
    unloaded: countUnloaded(raw, entries),
  };
}

const COVERAGE_KEYS = ['tail_truncated', 'tail_start', 'unlisted', 'unread_checks', 'goal_source'];
const COVERAGE_GOALS = ['typed', 'whole', 'excerpt', 'unroomed', 'unknown'];

export interface Coverage {
  readonly tail_truncated: boolean | null;
  readonly tail_start: number | null;
  readonly unlisted: number;
  readonly unread_checks: number;
  readonly goal_source: string;
}

export function readingCoverage(raw: unknown): Coverage | null {
  if (
    !isRecord(raw) ||
    Object.keys(raw).length !== COVERAGE_KEYS.length ||
    COVERAGE_KEYS.some((key) => !Object.hasOwn(raw, key))
  ) {
    return null;
  }
  const truncated = raw['tail_truncated'];
  if (truncated !== null && typeof truncated !== 'boolean') return null;
  const start = raw['tail_start'];
  if (
    start !== null &&
    (typeof start !== 'number' || !Number.isFinite(start) || start <= 0 || start > 253402300799)
  ) {
    return null;
  }
  const counts = [raw['unlisted'], raw['unread_checks']];
  if (counts.some((n) => !Number.isSafeInteger(n) || (n as number) < 0)) return null;
  return COVERAGE_GOALS.includes(raw['goal_source'] as string)
    ? (raw as unknown as Coverage)
    : null;
}

/* Compass's test of the harness's goal verdict, as a reading stored it: the verdict's own time and two closed
   tokens. Anything else is a reading this build cannot read, not one with a check missing. */
export interface GoalVerdictCheck {
  readonly at: number;
  readonly check: string;
  readonly why: string;
  readonly cites: readonly string[];
}

export function readingGoalVerdict(raw: unknown): GoalVerdictCheck | null {
  if (
    !isRecord(raw) ||
    Object.keys(raw).length !== GOAL_VERDICT_KEYS.length ||
    GOAL_VERDICT_KEYS.some((key) => !Object.hasOwn(raw, key))
  ) {
    return null;
  }
  const at = raw['at'];
  const cites = raw['cites'];
  if (
    typeof at !== 'number' ||
    !Number.isFinite(at) ||
    at <= 0 ||
    !GOAL_VERDICT_CHECKS.includes(raw['check'] as string) ||
    !Object.hasOwn(GOAL_VERDICT_WHY, raw['why'] as string) ||
    !Array.isArray(cites) ||
    cites.some((cite) => typeof cite !== 'string')
  ) {
    return null;
  }
  return raw as unknown as GoalVerdictCheck;
}

export function windowPartial(shape: {
  readonly coverage: Coverage | null;
  readonly windowStart: number | null;
}): boolean {
  const { coverage, windowStart } = shape;
  return Boolean(
    coverage &&
      coverage.tail_truncated === true &&
      coverage.tail_start !== null &&
      windowStart !== null &&
      windowStart > 0 &&
      coverage.tail_start > windowStart,
  );
}

/* A line's row names where the line came from, but only while the reading read the words shown now: under a
   reading of an older revision today's source would be a claim about words it never read. */
function lineLabel(
  key: string,
  label: string,
  row: Row | null | undefined,
  annotation: Annotation | null | undefined,
  historical: boolean,
  lineSource: (line: ReturnType<typeof annotationLines>[number]) => string,
): string {
  const match = OUTCOME_LINE.exec(String(key));
  if (!match || historical) return label;
  const line = annotationLines(annotation).find((item) => item.k === Number(match[1]));
  const clause = String(row?.['clause'] || '').trim();
  if (!line || (clause && clause !== line.text)) return label;
  return `${label} · ${lineSource(line).toUpperCase()}`;
}

/* The words the reading was read against. The producer carries them, because only it knows what the
   revision it read actually said; the current annotation is a legitimate fallback only while the reading
   read the current revision. */
function readingClause(
  key: string,
  row: Row | null | undefined,
  annotation: Annotation | null | undefined,
  historical: boolean,
): string {
  const carried = String(row?.['clause'] || '').trim();
  if (carried) return carried;
  if (historical) return '';
  return String(annotation?.[key === 'output' ? 'line_1' : key] || '').trim();
}

export interface Shape {
  readonly criteria: readonly Criterion[];
  readonly departures: readonly Criterion[];
  readonly revisionRead: number | null;
  readonly revisionReadAt: number | null;
  readonly windowStart: number | null;
  readonly coverage: Coverage | null;
  readonly promptSource: boolean;
  /** Compass's test of the harness's goal verdict, where the reading made one. */
  readonly goalVerdict: GoalVerdictCheck | null;
  readonly readClauses: readonly (readonly [string, string])[];
  readonly stamp: string;
  readonly cutoff: string;
  readonly scopeText: string;
  readonly scope: string;
  readonly malformed: string;
}

export const ASSESSMENT_KEYS = [
  'goal_source',
  'goal_source_at',
  'revision_read',
  'revision_read_at',
  'window_start',
  'read_at',
  'stamp',
  'cutoff',
  'scope',
  'scope_text',
  'ended_at_read',
  'evidence_through',
  'coverage',
  'goal_verdict',
  'criteria',
];

export function readingShape(
  raw: unknown,
  annotation: Annotation | null | undefined,
  entries: readonly WorkEntry[],
  limit: string,
  unsettledIn: boolean,
  lineSource: (line: ReturnType<typeof annotationLines>[number]) => string,
  lineRequests: Record<string, number> = {},
): Shape {
  const source: Row = isRecord(raw) ? raw : {};
  /* Unknown keys are fatal; MISSING keys are not. A producer that omits a field renders a reading with less
     in it, which is legible. One that emits a field this build does not know has diverged from the shape,
     and the measured way that fails is silent and confident. */
  const unknown = Object.keys(source).filter((name) => !ASSESSMENT_KEYS.includes(name));
  const coverage = readingCoverage(source['coverage']);
  if (source['coverage'] !== null && source['coverage'] !== undefined && !coverage) {
    unknown.push('coverage');
  }
  const goalVerdict = readingGoalVerdict(source['goal_verdict']);
  if (source['goal_verdict'] !== undefined && !goalVerdict) unknown.push('goal_verdict');
  if (unknown.length) {
    return {
      goalVerdict: null,
      criteria: [],
      departures: [],
      malformed: unknown.slice(0, 4).join(', '),
      revisionRead: null,
      revisionReadAt: null,
      windowStart: null,
      coverage: null,
      promptSource: false,
      readClauses: [],
      stamp: '',
      cutoff: '',
      scopeText: '',
      scope: '',
    };
  }
  const rows: Row = isRecord(source['criteria']) ? source['criteria'] : {};
  const revisionRead = nextNumber(source['revision_read']);
  const current = nextNumber(annotation?.['revision']);
  const historical = revisionRead !== null && current !== null && revisionRead !== current;
  /* Where the evidence window opened for the revision this reading read, so a check before the words cannot
     carry a verdict on either side. A reading stored before it carried one opened where the producer's
     `baseline_at` did. */
  const windowStart =
    nextNumber(source['window_start']) !== null
      ? nextNumber(source['window_start'])
      : nextNumber(
          PROMPT_SOURCES.includes(source['goal_source'] as string)
            ? source['goal_source_at']
            : source['revision_read_at'],
        );
  const readAt = nextNumber(source['read_at']);
  let unsettled = unsettledIn;
  if (readAt !== null && readAt > 0 && unsettled) {
    unsettled = conflictCandidates(annotation, entries, null, null).some(
      (entry) => (nextNumber(entry.at) || 0) <= readAt,
    );
  }
  const constraints = readingConstraints(
    rows,
    annotation,
    revisionRead !== null && current !== null && !historical,
  );
  const partial = windowPartial({ coverage, windowStart });
  const promptSource = PROMPT_SOURCES.includes(source['goal_source'] as string);
  const criteria = constraints
    .map(([key, label]) => {
      const row = rows[key] as Row | undefined;
      const floor = lineRequests[key];
      return criterion(
        key,
        key === 'goal' && promptSource
          ? 'GOAL FROM YOUR PROMPT'
          : lineLabel(key, label, row, annotation, historical, lineSource),
        readingClause(key, row, annotation, historical),
        row,
        entries,
        isOutcomeLine(key) || key === CLAIMS ? limit : '',
        unsettled,
        windowStart,
        String(source['scope'] ?? ''),
        !historical &&
          revisionRead === current &&
          readAt !== null &&
          readAt > 0 &&
          floor !== undefined &&
          floor > 0 &&
          floor <= readAt
          ? floor
          : null,
      );
    })
    .map(
      (row): Criterion => ({
        ...row,
        coverage: partial && row.key !== CLAIMS ? 'may be in the part not read' : '',
      }),
    );
  return {
    criteria,
    /* The intent's departures: a contradicted claim is not one, so it is in no count, flag or answer about
       the intent. */
    departures: criteria.filter((row) => row.result === DEPARTURE && row.key !== CLAIMS),
    revisionRead,
    revisionReadAt: nextNumber(source['revision_read_at']),
    windowStart,
    coverage,
    promptSource,
    goalVerdict,
    /* The reader's words only: the claims question has none to show. */
    readClauses: constraints
      .filter(([key]) => key !== CLAIMS)
      .map(([key, label]): readonly [string, string] => [
        key === 'goal' && promptSource ? 'GOAL FROM YOUR PROMPT' : label,
        readingClause(key, rows[key] as Row | undefined, annotation, historical),
      ]),
    stamp: String(source['stamp'] || ''),
    cutoff: String(source['cutoff'] || ''),
    /* From the READING, not from the live row: a stored reading describes the moment it was taken. */
    scopeText: String(source['scope_text'] || ''),
    scope: String(source['scope'] || ''),
    malformed: '',
  };
}

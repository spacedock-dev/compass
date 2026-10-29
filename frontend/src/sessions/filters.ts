import { nextNumber } from '../api/bootstrap';
import { isRecord, promptCopied, trimmed, type Row } from '../observed';
import { sessionInstruction } from './intent';
import {
  checkedAgainstCurrentWords,
  rowState,
  type SessionRow,
  type SessionsContext,
  type SessionsScreen,
} from './rows';
import { worktreeOf } from './worktree';

/* Sessions search and filters, as data: which drawn rows a reader's words and choices keep, how many each
   choice would keep, and what the choices hide. A pure function of the rows the screen draws, so every
   count is derived from the rows rendered and none is authored. The rules and their copy belong to
   docs/plans/2026-10-29-sessions-search.md (sections 2, 4 and 5). */

export type DateField = 'started' | 'active';
export type When = 'any' | 'hour' | 'today' | 'yesterday' | 'week' | 'unstamped';
export type Facet = 'project' | 'harness' | 'state' | 'drift' | 'goal';
export type DriftValue = 'recorded' | 'checked' | 'unchecked';
export type GoalValue = 'saved' | 'drafted' | 'none';

export interface FilterState {
  readonly query: string;
  readonly dateField: DateField;
  readonly when: When;
  readonly includeUnstamped: boolean;
  readonly project: readonly string[];
  readonly harness: readonly string[];
  readonly state: readonly string[];
  readonly drift: readonly string[];
  readonly goal: readonly string[];
}

export const EMPTY_FILTERS: FilterState = {
  query: '',
  dateField: 'started',
  when: 'any',
  includeUnstamped: false,
  project: [],
  harness: [],
  state: [],
  drift: [],
  goal: [],
};

export const FACETS: readonly Facet[] = ['project', 'harness', 'state', 'drift', 'goal'];
export const QUERY_LIMIT = 200;

/* Fixed orders, so a poll never moves an option under the pointer. */
export const STATE_VALUES = [
  'Waiting on you',
  'Working',
  'Idle',
  'Ended',
  'State not published',
] as const;
export const DRIFT_OPTIONS: readonly { readonly value: DriftValue; readonly label: string }[] = [
  { value: 'recorded', label: 'Drift recorded' },
  { value: 'checked', label: 'Checked against your current words, none recorded' },
  { value: 'unchecked', label: 'Not checked against your current words' },
];
export const GOAL_OPTIONS: readonly { readonly value: GoalValue; readonly label: string }[] = [
  { value: 'saved', label: 'Goal saved' },
  { value: 'drafted', label: 'Drafted from a prompt, not saved' },
  { value: 'none', label: 'No goal yet' },
];
export const WHENS: readonly When[] = ['any', 'hour', 'today', 'yesterday', 'week', 'unstamped'];
const WHEN_LABELS: Readonly<Record<Exclude<When, 'unstamped'>, string>> = {
  any: 'Any time',
  hour: 'Last hour',
  today: 'Today',
  yesterday: 'Yesterday',
  week: 'Last 7 days',
};

export function whenLabel(when: When, field: DateField): string {
  if (when === 'unstamped')
    return field === 'started' ? 'Start not published' : 'Activity time not published';
  return WHEN_LABELS[when];
}

export const dateFieldLabel = (field: DateField): string =>
  field === 'started' ? 'Started' : 'Last active';

export const collator = new Intl.Collator('en');

/* "A", "A and B", "A, B and C". */
export function joinNames(names: readonly string[]): string {
  if (names.length <= 1) return names[0] ?? '';
  return `${names.slice(0, -1).join(', ')} and ${names[names.length - 1] ?? ''}`;
}

const plural = (count: number, one: string, many: string): string =>
  `${String(count)} ${count === 1 ? one : many}`;

/* ---- Words ---- */

/* Case and accents fold away (NFKD with the combining marks removed), and runs of space read as one. */
export function normalize(text: string): string {
  return text.normalize('NFKD').replace(/\p{M}/gu, '').toLowerCase().replace(/\s+/g, ' ').trim();
}

/* The reader's words as terms: a "quoted phrase" is one term, and every term must match somewhere. */
export function queryTerms(query: string): string[] {
  const terms: string[] = [];
  for (const match of query.slice(0, QUERY_LIMIT).matchAll(/"([^"]*)"|(\S+)/g)) {
    const term = normalize((match[1] ?? match[2] ?? '').replace(/"/g, ''));
    if (term) terms.push(term);
  }
  return terms;
}

/* A run this long of id characters may be a pasted session id; a shorter one would match too many. */
const ID_TERM = /^[0-9a-z_-]{6,}$/;

interface Field {
  readonly name: string;
  readonly text: string;
  readonly folded: string;
}

const field = (name: string, value: unknown): Field | null => {
  const text = typeof value === 'string' ? value.replace(/\s+/g, ' ').trim() : '';
  return text ? { name, text, folded: normalize(text) } : null;
};

/* What a reader would have to open the session to see, named the way the hint says it. */
const HIDDEN = {
  first: 'your first prompt',
  latest: 'your latest prompt',
  slashGoal: 'its /goal',
  outcome: 'your expected outcome',
  task: 'a task',
  sid: 'the session id',
} as const;

export interface Stamp {
  readonly at: number;
  /** The first message's time stands in for a start the harness did not publish. */
  readonly fromFirstMessage: boolean;
}

/* The order `SessionAge` reads: the published start, then the first message. */
export function startStamp(source: Row | undefined): Stamp | null {
  const started = nextNumber(source?.['started_at']);
  if (started !== null && started > 0) return { at: started, fromFirstMessage: false };
  const first = nextNumber(source?.['first_prompt_at']);
  return first !== null && first > 0 ? { at: first, fromFirstMessage: true } : null;
}

export function activityStamp(source: Row | undefined): Stamp | null {
  const at = nextNumber(source?.['last_activity']);
  return at !== null && at > 0 ? { at, fromFirstMessage: false } : null;
}

export interface IndexedRow {
  readonly row: SessionRow;
  readonly shown: readonly Field[];
  readonly hidden: readonly Field[];
  readonly sid: string;
  readonly state: string;
  /** Null while the annotation store is off or unreadable: nothing is published to partition. */
  readonly drift: DriftValue | null;
  readonly goal: GoalValue | null;
  readonly started: Stamp | null;
  readonly active: Stamp | null;
}

/* Built once per payload, so a keystroke folds no text. Placeholder sentences ("Add a goal", "Title not
   published") are never fields, because a reader searching for them would match a fact nobody published. */
export function indexRow(row: SessionRow, context: SessionsContext): IndexedRow {
  const readable = context.annotate && !context.unreadable;
  const { session, source, goal } = row;
  const titleShown = session.titleKnown ? session.titleText : '';
  const fallback = !session.titleKnown && session.promptKnown ? session.promptText : '';
  const task = sessionInstruction(source, 'asked');
  const shown = [
    field('title', titleShown || fallback),
    field('goal', goal.known ? goal.text : ''),
    field('task', task ? task['text'] : ''),
    field('project', session.project),
    field('worktree', worktreeOf(source)),
    field('harness', row.harnessLabel),
  ].filter((one): one is Field => one !== null);
  const first =
    source && source['first_prompt_control'] !== true && !promptCopied(source, 'first_prompt')
      ? field(HIDDEN.first, source['first_prompt'])
      : null;
  const latest =
    source && session.titleKnown && !promptCopied(source, 'last_prompt')
      ? field(HIDDEN.latest, source['last_prompt'])
      : null;
  const stated = source?.['session_goal'];
  const outcome = [1, 2, 3, 4, 5, 6].map((n) =>
    field(HIDDEN.outcome, source?.[`annotation_line_${String(n)}`]),
  );
  const tasks = Array.isArray(source?.['tasks'])
    ? (source['tasks'] as unknown[]).map((one) =>
        field(HIDDEN.task, isRecord(one) ? one['subject'] : ''),
      )
    : [];
  const hidden = [
    first,
    latest,
    field(HIDDEN.slashGoal, isRecord(stated) ? stated['text'] : ''),
    ...outcome,
    ...tasks,
  ].filter((one): one is Field => one !== null);
  const typed = Boolean(trimmed(source?.['annotation_goal']));
  const checked = checkedAgainstCurrentWords(source, context);
  return {
    row,
    shown,
    hidden,
    sid: normalize(session.sid),
    state: rowState(session),
    drift: !readable ? null : row.drift ? 'recorded' : checked ? 'checked' : 'unchecked',
    goal: !readable ? null : typed ? 'saved' : goal.known ? 'drafted' : 'none',
    started: startStamp(source),
    active: activityStamp(source),
  };
}

export function indexScreen(screen: SessionsScreen): IndexedRow[] {
  return [...screen.active, ...screen.history].map((row) => indexRow(row, screen.context));
}

const EXCERPT = 80;

/* About eighty characters of the field around the match, so the reader can tell which prompt it was. */
export function excerpt(text: string, term: string): string {
  if (text.length <= EXCERPT) return text;
  const folded = normalize(text);
  // Folding keeps the length for most text; where it does not, the excerpt starts at the beginning.
  const at = folded.length === text.length ? Math.max(0, folded.indexOf(term)) : 0;
  const start = Math.max(0, Math.min(at - 20, text.length - EXCERPT));
  const end = Math.min(text.length, start + EXCERPT);
  return `${start > 0 ? '…' : ''}${text.slice(start, end).trim()}${end < text.length ? '…' : ''}`;
}

export interface SearchResult {
  readonly match: boolean;
  /** Set when a term matched only something the row does not show. */
  readonly hint: string;
}

export function searchRow(indexed: IndexedRow, terms: readonly string[]): SearchResult {
  let hint = '';
  for (const term of terms) {
    if (indexed.shown.some((one) => one.folded.includes(term))) continue;
    const hidden = indexed.hidden.find((one) => one.folded.includes(term));
    const byId = !hidden && ID_TERM.test(term) && indexed.sid.startsWith(term);
    if (!hidden && !byId) return { match: false, hint: '' };
    if (!hint)
      hint = hidden
        ? `Matched in ${hidden.name}: "${excerpt(hidden.text, term)}"`
        : `Matched in ${HIDDEN.sid}: "${indexed.row.session.sid}"`;
  }
  return { match: true, hint };
}

/* ---- Dates ---- */

export interface DayEdges {
  readonly generated: number;
  readonly hour: number;
  readonly today: number;
  readonly yesterday: number;
  readonly week: number;
}

/* Local midnights around the board's own clock, never the browser's. `setDate` walks calendar days, so a
   day that a daylight-saving change makes 23 or 25 hours long still starts at midnight. Last 7 days is
   today and the six days before it. */
export function dayEdges(generated: number): DayEdges {
  const midnight = new Date(generated * 1000);
  midnight.setHours(0, 0, 0, 0);
  const daysBack = (days: number) => {
    const day = new Date(midnight);
    day.setDate(day.getDate() - days);
    return day.getTime() / 1000;
  };
  return {
    generated,
    hour: generated - 3600,
    today: midnight.getTime() / 1000,
    yesterday: daysBack(1),
    week: daysBack(6),
  };
}

export function inWhen(at: number, when: When, edges: DayEdges): boolean {
  if (when === 'hour') return at >= edges.hour;
  if (when === 'today') return at >= edges.today;
  if (when === 'yesterday') return at >= edges.yesterday && at < edges.today;
  if (when === 'week') return at >= edges.week;
  return true;
}

/* Where a dated choice begins, for the sentence about sessions the board did not load. */
export function whenStart(when: When, edges: DayEdges): number | null {
  if (when === 'hour') return edges.hour;
  if (when === 'today') return edges.today;
  if (when === 'yesterday') return edges.yesterday;
  if (when === 'week') return edges.week;
  return null;
}

export const isDated = (when: When): boolean => when !== 'any' && when !== 'unstamped';

export const stampOf = (indexed: IndexedRow, dateField: DateField): Stamp | null =>
  dateField === 'started' ? indexed.started : indexed.active;

function datePasses(indexed: IndexedRow, filters: FilterState, edges: DayEdges | null): boolean {
  // With no published clock the control is disabled, and a choice made earlier filters nothing.
  if (filters.when === 'any' || edges === null) return true;
  const stamp = stampOf(indexed, filters.dateField);
  if (filters.when === 'unstamped') return stamp === null;
  if (stamp === null) return filters.includeUnstamped;
  return inWhen(stamp.at, filters.when, edges);
}

/* ---- Combining ---- */

export function facetValue(indexed: IndexedRow, facet: Facet): string | null {
  if (facet === 'project') return indexed.row.session.project;
  if (facet === 'harness') return indexed.row.session.harness;
  if (facet === 'state') return indexed.state;
  if (facet === 'drift') return indexed.drift;
  return indexed.goal;
}

type Part = 'search' | 'date' | Facet;

export interface Prepared {
  readonly filters: FilterState;
  readonly terms: readonly string[];
  readonly edges: DayEdges | null;
}

export function prepare(filters: FilterState, generated: number | null): Prepared {
  return {
    filters,
    terms: queryTerms(filters.query),
    edges: generated === null ? null : dayEdges(generated),
  };
}

/* Values inside one facet widen (OR); facets, the date and the words narrow each other (AND). A facet whose
   rows publish nothing to partition (drift and goal with annotations off) filters nothing. */
export function passes(indexed: IndexedRow, prepared: Prepared, skip: Part | null = null): boolean {
  const { filters, terms, edges } = prepared;
  if (skip !== 'search' && terms.length && !searchRow(indexed, terms).match) return false;
  if (skip !== 'date' && !datePasses(indexed, filters, edges)) return false;
  for (const facet of FACETS) {
    if (facet === skip) continue;
    const chosen = filters[facet];
    if (!chosen.length) continue;
    const value = facetValue(indexed, facet);
    if (value !== null && !chosen.includes(value)) return false;
  }
  return true;
}

export function filtersActive(filters: FilterState): boolean {
  return (
    queryTerms(filters.query).length > 0 ||
    filters.when !== 'any' ||
    FACETS.some((facet) => filters[facet].length > 0)
  );
}

export interface Filtered {
  readonly active: boolean;
  readonly keys: ReadonlySet<string>;
  /** Lines a kept row adds under its identity: where the words matched, and which time dated it. */
  readonly hints: ReadonlyMap<string, readonly string[]>;
  readonly shown: number;
  readonly total: number;
}

export function applyFilters(
  indexed: readonly IndexedRow[],
  prepared: Prepared,
  datedClock: (at: number) => string,
): Filtered {
  const active = filtersActive(prepared.filters);
  const keys = new Set<string>();
  const hints = new Map<string, string[]>();
  const { filters, terms, edges } = prepared;
  const dated = edges !== null && filters.when !== 'any' && filters.when !== 'unstamped';
  for (const one of indexed) {
    if (active && !passes(one, prepared)) continue;
    keys.add(one.row.key);
    const lines: string[] = [];
    const found = terms.length ? searchRow(one, terms).hint : '';
    if (found) lines.push(found);
    const stamp = dated ? stampOf(one, filters.dateField) : null;
    if (stamp)
      lines.push(
        `${dateFieldLabel(filters.dateField)} ${datedClock(stamp.at)}${stamp.fromFirstMessage ? ', from the first message' : ''}`,
      );
    if (lines.length) hints.set(one.row.key, lines);
  }
  return { active, keys, hints, shown: keys.size, total: indexed.length };
}

/* ---- Counts ---- */

/* Faceted: how many rows would show with this value chosen in its facet and every other choice kept. */
export function facetCounts(
  indexed: readonly IndexedRow[],
  prepared: Prepared,
  facet: Facet,
): Map<string, number> {
  const counts = new Map<string, number>();
  for (const one of indexed) {
    if (!passes(one, prepared, facet)) continue;
    const value = facetValue(one, facet);
    if (value === null) continue;
    counts.set(value, (counts.get(value) ?? 0) + 1);
  }
  return counts;
}

export interface DateCounts {
  readonly byWhen: ReadonlyMap<When, number>;
  /** Rows with no stamp in the chosen field that every other choice keeps. */
  readonly unstamped: number;
  /** Their harness labels, for the sentence that names who publishes no stamp. */
  readonly unstampedHarnesses: readonly string[];
}

export function dateCounts(indexed: readonly IndexedRow[], prepared: Prepared): DateCounts {
  const { filters, edges } = prepared;
  const kept = indexed.filter((one) => passes(one, prepared, 'date'));
  const byWhen = new Map<When, number>();
  for (const when of WHENS)
    byWhen.set(when, kept.filter((one) => datePasses(one, { ...filters, when }, edges)).length);
  const missing = kept.filter((one) => stampOf(one, filters.dateField) === null);
  return {
    byWhen,
    unstamped: missing.length,
    unstampedHarnesses: [...new Set(missing.map((one) => one.row.harnessLabel))].sort(
      collator.compare,
    ),
  };
}

/* The rows a dated choice is hiding only because they publish no stamp. Zero unless a dated choice stands
   and the reader has not asked for them. */
export function unstampedHidden(dates: DateCounts, prepared: Prepared): number {
  const { filters, edges } = prepared;
  return edges !== null && isDated(filters.when) && !filters.includeUnstamped ? dates.unstamped : 0;
}

/* ---- Options ---- */

export interface Option {
  readonly value: string;
  readonly label: string;
  /** Null where no count can be stated, as for a store that could not be read. */
  readonly count: number | null;
  readonly note: string;
  readonly disabled: boolean;
}

export function projectLabel(value: string): string {
  if (value === '') return 'No project published';
  return value.trim() ? value : 'Blank project label';
}

/* A label the rows of two or more locations carry. The row's own "N sessions share this display label"
   counts sessions and never establishes a location; two distinct published `project_key` values do. */
export function sharedLocationLabels(indexed: readonly IndexedRow[]): Set<string> {
  const keys = new Map<string, Set<string>>();
  for (const one of indexed) {
    const key = trimmed(one.row.source?.['project_key']);
    if (!key) continue;
    const label = one.row.session.project;
    const found = keys.get(label) ?? new Set<string>();
    found.add(key);
    keys.set(label, found);
  }
  return new Set([...keys].filter(([, found]) => found.size >= 2).map(([label]) => label));
}

/* Collator order, the blank label after the named ones and the empty label last, and a chosen label the
   board no longer carries kept where the reader can still clear it. */
export function projectOptions(indexed: readonly IndexedRow[], prepared: Prepared): Option[] {
  const counts = facetCounts(indexed, prepared, 'project');
  const shared = sharedLocationLabels(indexed);
  const labels = [...new Set(indexed.map((one) => one.row.session.project))];
  const rank = (label: string) => (label === '' ? 2 : label.trim() ? 0 : 1);
  labels.sort((a, b) => rank(a) - rank(b) || collator.compare(a, b));
  const options: Option[] = labels.map((value) => ({
    value,
    label: projectLabel(value),
    count: counts.get(value) ?? 0,
    note: shared.has(value) ? 'Label shared by more than one location' : '',
    disabled: false,
  }));
  for (const value of prepared.filters.project)
    if (!labels.includes(value))
      options.push({
        value,
        label: projectLabel(value),
        count: null,
        note: 'Not on the board now',
        disabled: false,
      });
  return options;
}

export interface HarnessMeta {
  readonly key: string;
  readonly label: string;
  readonly discovered: boolean;
  readonly error: boolean;
  /** What the harness's wait reporting depends on, where it depends on anything. */
  readonly waitWhen: string;
  readonly reportsWait: boolean;
}

export function harnessMeta(payload: Row): HarnessMeta[] {
  const rows = Array.isArray(payload['harnesses']) ? payload['harnesses'].filter(isRecord) : [];
  return rows
    .map((row) => ({
      key: trimmed(row['key']),
      label: trimmed(row['label']) || trimmed(row['key']),
      discovered: row['discovered'] === true,
      error: Boolean(row['error']),
      waitWhen: trimmed(row['reports_needs_input_when']),
      reportsWait: row['reports_needs_input'] === true,
    }))
    .filter((row) => row.key);
}

/* Only harnesses whose store was found are listed: ten options at zero would read as ten stores searched. */
export function harnessOptions(
  indexed: readonly IndexedRow[],
  prepared: Prepared,
  harnesses: readonly HarnessMeta[],
): Option[] {
  const counts = facetCounts(indexed, prepared, 'harness');
  return harnesses
    .filter((one) => one.discovered)
    .map((one) => ({
      value: one.key,
      label: one.label,
      count: one.error ? null : (counts.get(one.key) ?? 0),
      note: one.error ? 'Store could not be read' : '',
      disabled: one.error,
    }));
}

export function fixedOptions(
  indexed: readonly IndexedRow[],
  prepared: Prepared,
  facet: 'state' | 'drift' | 'goal',
): Option[] {
  const counts = facetCounts(indexed, prepared, facet);
  const list =
    facet === 'state'
      ? STATE_VALUES.map((value) => ({ value, label: value }))
      : facet === 'drift'
        ? DRIFT_OPTIONS
        : GOAL_OPTIONS;
  return list.map((one) => ({
    value: one.value,
    label: one.label,
    count: counts.get(one.value) ?? 0,
    note: '',
    disabled: false,
  }));
}

export function optionLabel(
  facet: Facet,
  value: string,
  harnesses: readonly HarnessMeta[],
): string {
  if (facet === 'project') return projectLabel(value);
  if (facet === 'harness') return harnesses.find((one) => one.key === value)?.label ?? value;
  if (facet === 'drift') return DRIFT_OPTIONS.find((one) => one.value === value)?.label ?? value;
  if (facet === 'goal') return GOAL_OPTIONS.find((one) => one.value === value)?.label ?? value;
  return value;
}

/* The "Find a project" field narrows the list it is above; it never chooses. */
export function narrowOptions(options: readonly Option[], text: string): Option[] {
  const terms = queryTerms(text);
  if (!terms.length) return [...options];
  return options.filter((one) => terms.every((term) => normalize(one.label).includes(term)));
}

/* ---- Guards ---- */

export function hiddenWaiting(
  indexed: readonly IndexedRow[],
  filtered: Filtered,
): readonly IndexedRow[] {
  if (!filtered.active) return [];
  return indexed.filter((one) => one.state === 'Waiting on you' && !filtered.keys.has(one.row.key));
}

/* Who could be waiting without the page knowing: rows whose harness cannot report a wait, and the harnesses
   on the board whose wait reporting holds only in some setups. */
export function waitCoverage(
  indexed: readonly IndexedRow[],
  harnesses: readonly HarnessMeta[],
): string[] {
  const silent = indexed.filter((one) => !one.row.session.blockKnown);
  const names = [...new Set(silent.map((one) => one.row.harnessLabel))].sort(collator.compare);
  const onBoard = new Set(indexed.map((one) => one.row.session.harness));
  const qualified = harnesses
    .filter((one) => onBoard.has(one.key) && !one.error && one.reportsWait && one.waitWhen)
    .map((one) => one.label)
    .sort(collator.compare);
  const lines: string[] = [];
  if (names.length)
    lines.push(
      `${joinNames(names)} ${names.length === 1 ? 'does' : 'do'} not report when a session is waiting, so ${
        silent.length === 1
          ? `${names.length === 1 ? 'its' : 'their'} 1 session`
          : `${String(silent.length)} of ${names.length === 1 ? 'its' : 'their'} sessions`
      } could be waiting without showing here.`,
    );
  if (qualified.length)
    lines.push(
      `${joinNames(qualified)} ${qualified.length === 1 ? 'reports' : 'report'} a wait only in some setups; Attention's coverage says which.`,
    );
  return lines;
}

/* ---- Sentences ---- */

export function resultLine(
  filtered: Filtered,
  board: { readonly showAll: boolean; readonly hours: number | null },
): string {
  if (filtered.active)
    return `Showing ${String(filtered.shown)} of ${plural(filtered.total, 'session', 'sessions')}. ACTIVE NOW and WORKING above count the whole board.`;
  if (board.showAll) return `${plural(filtered.total, 'stored session', 'stored sessions')}.`;
  if (board.hours !== null && board.hours > 0)
    return `${plural(filtered.total, 'session', 'sessions')} active in the last ${plural(board.hours, 'hour', 'hours')}.`;
  return `${plural(filtered.total, 'session', 'sessions')} on this board.`;
}

/* What the cue region says after the reader's own change. Never the words they typed. */
export function announcement(filtered: Filtered): string {
  if (!filtered.active) return `Filters cleared. Showing all ${String(filtered.total)} sessions.`;
  if (filtered.shown === 0) return 'No session matches these filters.';
  return `Showing ${String(filtered.shown)} of ${String(filtered.total)} sessions.`;
}

export function unstampedLine(count: number, dateField: DateField): string {
  if (count === 0) return '';
  const what = dateField === 'started' ? 'start time' : 'activity time';
  return count === 1
    ? `1 session has no published ${what} and is not shown.`
    : `${String(count)} sessions have no published ${what} and are not shown.`;
}

export function waitingLine(count: number): string {
  return count === 1
    ? '1 session waiting on you is hidden by these filters.'
    : `${String(count)} sessions waiting on you are hidden by these filters.`;
}

export function groupEmptyLine(total: number, group: string): string {
  return total === 1
    ? `The 1 session in ${group} does not match these filters.`
    : `None of the ${String(total)} sessions in ${group} match these filters.`;
}

/* The chip's words, and a shorter form for a long list. */
export function chipText(name: string, values: readonly string[]): { full: string; short: string } {
  const full = `${name}: ${values.join(', ')}`;
  const short =
    full.length > 40 && values.length > 1
      ? `${name}: ${values[0] ?? ''} +${String(values.length - 1)} more`
      : full;
  return { full, short };
}

export function dateChip(filters: FilterState, unstamped: number): string {
  if (filters.when === 'any') return '';
  if (filters.when === 'unstamped') return whenLabel('unstamped', filters.dateField);
  const base = `${dateFieldLabel(filters.dateField)}: ${whenLabel(filters.when, filters.dateField)}`;
  if (!filters.includeUnstamped) return base;
  const what = filters.dateField === 'started' ? 'start time' : 'activity time';
  return `${base}, plus ${String(unstamped)} with no ${what}`;
}

export function toggled(list: readonly string[], value: string): string[] {
  return list.includes(value) ? list.filter((one) => one !== value) : [...list, value];
}

import { nextNumber } from '../api/bootstrap';
import { stableProjectKey } from '../api/identity';
import type { RouteInput } from '../router/grammar';
import {
  durationSince,
  endedAt,
  exactAskOwner,
  isRecord,
  payloadAskRows,
  payloadSessionRows,
  sessionKey,
  type Observed,
  type ObservedSession,
  type Row,
} from '../observed';
import {
  intentDraft,
  openedWithControl,
  PROMPT_CHOSEN,
  SESSION_GOAL,
  PROMPT_SOURCES,
  READING_ASSESSMENT_KEYS,
  READING_CLAIMS,
  readingNamesConstraint,
  sessionInstruction,
  type PromptCandidate,
} from './intent';
import { datedClock } from '../observed/values';

/* What the Sessions screen draws, as data: a pure function of one payload and the model read from it, so
   every sentence is testable without a DOM and the screen cannot say something the rows do not. The
   legacy page's `next-sessions.js` is the oracle; its rendered text is compared to this screen's over
   generated payloads. */

/* Whether the payload published the exact-request capability and the annotation store. Both are read as
   exactly `true`: a payload that says "yes" is not one that said true. */
export interface SessionsContext {
  readonly annotate: boolean;
  readonly unreadable: string;
  readonly ask: boolean;
  readonly generated: number | null;
}

export function sessionsContext(payload: Row): SessionsContext {
  return {
    annotate: payload['annotate'] === true,
    unreadable: String(payload['annotate_unreadable'] || ''),
    ask: payload['ask'] === true,
    generated: nextNumber(payload['generated']),
  };
}

export function analysisAvailable(payload: Row): boolean {
  const context = sessionsContext(payload);
  const routes = payload['reading_routes'];
  return (
    context.annotate &&
    !context.unreadable &&
    isRecord(routes) &&
    Object.values(routes).some((route) => isRecord(route) && Boolean(route['provider']))
  );
}

/* The label each harness publishes about itself, by key. */
export function harnessLabels(payload: Row): Map<string, string> {
  const labels = new Map<string, string>();
  const harnesses = Array.isArray(payload['harnesses']) ? (payload['harnesses'] as unknown[]) : [];
  for (const harness of harnesses) {
    const record: Row = isRecord(harness) ? harness : {};
    const key = String(record['key'] || '');
    if (key) labels.set(key, String(record['label'] || key));
  }
  return labels;
}

/* Exact requests whose owner is among `rows`, in payload order. A request with a blank question is kept
   here: the row's "needs you" label follows the request, and whether its words are known is the model's
   question (`askKnown`), asked separately. */
export function operationsAsks(payload: Row, rows: readonly Row[]): Row[] {
  if (payload['ask'] !== true) return [];
  const identities = new Set(rows.map(sessionKey));
  return payloadAskRows(payload).filter((ask) => {
    const owner = exactAskOwner(payload, ask);
    return owner !== null && identities.has(sessionKey(owner));
  });
}

export function askFor(payload: Row, session: Row, asks: readonly Row[]): Row | null {
  const key = sessionKey(session);
  return (
    asks.find((ask) => {
      const owner = exactAskOwner(payload, ask);
      return owner !== null && sessionKey(owner) === key;
    }) ?? null
  );
}

/* Who the request is addressed to: a Spacedock session answers to its captain, any other to the reader. */
export function askResponsibility(payload: Row, ask: Row): 'CAPTAIN' | 'NEEDS YOU' {
  const owner = exactAskOwner(payload, ask);
  return owner && isRecord(owner['spacedock']) ? 'CAPTAIN' : 'NEEDS YOU';
}

/* The cell the rest of the row rests on: a raise the session was asked about, and nothing it merely
   checked. Neither the annotation's presence nor its press count establishes a departure. */
export interface DriftRecord {
  readonly at: number | null;
  readonly revision: number | null;
  readonly subject: 'This raise' | 'This reading';
}

/** The stored reading itself departs: an intent line found a departure and cites what it rests on. */
export function readingDeparts(source: Row | undefined): boolean {
  const raw = source?.['annotation_assessment'];
  if (!isRecord(raw) || !Object.keys(raw).every((key) => READING_ASSESSMENT_KEYS.includes(key)))
    return false;
  const criteria = isRecord(raw['criteria']) ? raw['criteria'] : {};
  return Object.keys(criteria)
    .filter((key) => readingNamesConstraint(key) && key !== READING_CLAIMS)
    .some((key) => {
      const criterion = criteria[key];
      return (
        isRecord(criterion) &&
        criterion['result'] === 'departure' &&
        Array.isArray(criterion['cites']) &&
        criterion['cites'].some((cite) => typeof cite === 'string' && cite.trim())
      );
    });
}

export function drift(source: Row | undefined, context: SessionsContext): DriftRecord[] {
  if (!context.annotate || !source) return [];
  const rows: DriftRecord[] = (
    Array.isArray(source['departures']) ? (source['departures'] as unknown[]) : []
  )
    .filter((row) => typeof row === 'object' && row !== null)
    .map((row) => ({
      at: nextNumber((row as Row)['at']),
      revision: nextNumber((row as Row)['revision']),
      subject: 'This raise' as const,
    }));
  const raw = source['annotation_assessment'];
  // A contradicted claim is not drift from the intent.
  if (isRecord(raw) && readingDeparts(source))
    rows.push({
      at: nextNumber(raw['read_at']),
      revision: nextNumber(raw['revision_read']),
      subject: 'This reading',
    });
  return rows;
}

/* One reading, or one raise, against words that have moved on. The sentence is owned here for the
   reason the legacy page owns it once: a second wording would be a second promise. It names the two
   moments the reader has seen on this page (when the reading was made, when they changed the words) and
   never a revision number, which appears nowhere else. The numbers still decide whether the words moved;
   they are not printed. Silence on either absence rather than a placeholder: a moment the record did not
   keep is left out of the sentence, never replaced by today's. */
export function revisionSuperseded(
  subject: string,
  read: number | null,
  current: number | null,
  madeAt: number | null = null,
  changedAt: number | null = null,
): string {
  if (read === null || current === null || read === current) return '';
  const made = madeAt !== null && madeAt > 0 ? ` at ${datedClock(madeAt)}` : '';
  const changed = changedAt !== null && changedAt > 0 ? ` at ${datedClock(changedAt)}` : '';
  return `${subject} was made${made} against an earlier version of your intent. You changed it${changed}, so it does not describe what you are asking for now.`;
}

export interface DriftMark {
  /** "age unknown", or "<duration> ago" */
  readonly age: string;
  /** Some recorded departure ages are unknown. */
  readonly someUnknown: boolean;
  readonly stale: readonly string[];
}

export function driftMark(source: Row | undefined, context: SessionsContext): DriftMark | null {
  const records = drift(source, context);
  if (!records.length || !source) return null;
  const dated = records.map((row) => row.at).filter((at): at is number => at !== null && at > 0);
  const age = dated.length ? durationSince(context.generated, Math.max(...dated)) : null;
  const current = nextNumber(source['annotation_revision']);
  const changedAt = nextNumber(source['annotation_at']);
  const stale = [
    ...new Set(
      records
        .map((row) => revisionSuperseded(row.subject, row.revision, current, row.at, changedAt))
        .filter(Boolean),
    ),
  ];
  return {
    age: age === null ? 'age unknown' : `${age} ago`,
    someUnknown: records.some((row) => row.at === null || row.at <= 0) && dated.length > 0,
    stale,
  };
}

/* Whether any session carries a check: a stored reading, a reading counted against its words, an unasked
   check, or a departure on record. Read off the rows rather than a flag, and only while the annotation
   store is on, because with it off a stored reading is not published and "none" would be a claim about
   something the page cannot see. Null for that case. */
export function anyChecked(rows: readonly Row[], context: SessionsContext): boolean | null {
  if (!context.annotate) return null;
  return rows.some((session) => {
    if (session['departure_checked'] === true) return true;
    const assessment = session['annotation_assessment'];
    if (assessment !== undefined && assessment !== null && assessment !== '') return true;
    if ((nextNumber(session['annotation_reading_count']) ?? 0) > 0) return true;
    return Array.isArray(session['departures']) && session['departures'].length > 0;
  });
}

/* One row's check against the words the reader holds now: an unasked check that found no departure, or a
   stored reading made against the current revision. A reading made against earlier words is not one. Null
   while annotations are off, for the reason `anyChecked` is. Drift outranks it where a row has both. */
export function checkedAgainstCurrentWords(
  source: Row | undefined,
  context: SessionsContext,
): boolean | null {
  if (!context.annotate) return null;
  if (!source) return false;
  if (source['departure_checked'] === true) return true;
  const assessment = source['annotation_assessment'];
  if (!isRecord(assessment)) return false;
  const read = nextNumber(assessment['revision_read']);
  return read !== null && read === nextNumber(source['annotation_revision']);
}

export const NOT_CHECKED = 'No session has been checked for drift yet; open one to check it.';

export interface GoalCell {
  readonly label: string;
  /** Every available goal opens the session at its goal, including saved words. */
  readonly kind: 'off' | 'link';
  readonly text: string;
  readonly known: boolean;
}

/* Admitted by [DEC-22](docs/design-reading-a-session.md#dec-22-your-own-prompt-may-become-your-goal): the
   collector's asked Claude instruction and the classified Codex title, never a workflow or observer
   paraphrase. Displaying it saves nothing. */
export function goalCell(
  source: Row | undefined,
  context: SessionsContext,
  chosen: PromptCandidate | null = null,
): GoalCell {
  if (!context.annotate)
    return { label: 'GOAL', kind: 'off', text: 'Annotations off', known: false };
  const typed = String(source?.['annotation_goal'] || '').trim();
  const asked = source?.['harness'] === 'claude' ? sessionInstruction(source, 'asked') : null;
  const prompt = asked
    ? String(asked['text'] || '').trim()
    : source?.['harness'] === 'codex' && source['prompt_states_work'] === true
      ? String(source['title'] || '').trim()
      : '';
  /* The words the session page drafts, so the link lands on the words the cell named: the first prompt, or
     the latest where no first one with a time is published. Over a session that opened with a harness
     control the page drafts nothing, so the cell names nothing either. */
  const draft =
    typed || !source
      ? null
      : intentDraft(source, { annotate: context.annotate, unreadable: context.unreadable }, chosen);
  const text = typed || (draft ? draft.text : openedWithControl(source) ? '' : prompt);
  const label = typed
    ? String(source?.['annotation_goal_source']) === SESSION_GOAL
      ? 'GOAL · FROM /GOAL'
      : PROMPT_SOURCES.includes(String(source?.['annotation_goal_source']))
        ? 'GOAL · FROM YOUR PROMPT'
        : 'GOAL · YOUR WORDS'
    : draft && draft.source === 'first-prompt'
      ? 'GOAL · YOUR FIRST PROMPT'
      : draft && draft.source === SESSION_GOAL
        ? 'GOAL · YOUR /GOAL'
        : draft && draft.source === PROMPT_CHOSEN
          ? 'GOAL · YOUR CHOSEN PROMPT'
          : text
            ? 'GOAL · YOUR LATEST PROMPT'
            : 'GOAL';
  return typed
    ? { label, kind: 'link', text, known: true }
    : { label, kind: 'link', text: text || 'Add a goal', known: Boolean(text) };
}

export interface SessionRow {
  /** Unique within the screen, so two rows that carry one identity (a payload can) still draw. */
  readonly key: string;
  readonly session: ObservedSession;
  readonly source: Row | undefined;
  readonly route: RouteInput & { readonly view: 'session' };
  readonly harnessLabel: string;
  /** The project's stable key, which the drift context rows are held under. */
  readonly projectKey: string;
  readonly goal: GoalCell;
  readonly drift: DriftMark | null;
  /** "ended <duration> ago", or empty. */
  readonly endedSince: string;
  readonly responsibility: string;
  readonly history: boolean;
}

export interface SessionsScreen {
  readonly context: SessionsContext;
  readonly counters: Observed['counters'];
  readonly lede: boolean;
  readonly active: readonly SessionRow[];
  readonly history: readonly SessionRow[];
}

/* The two groups. Promote only this screen's rows: changing the shared `isActive` or the model's active
   list would turn a stored reading into running evidence and inflate its counter. A held request outranks
   a recorded departure, which outranks a working session; the sort is stable, so within a rank the lanes'
   own order stands. */
export function groupSessions(
  model: Observed,
  sources: ReadonlyMap<string, Row>,
  context: SessionsContext,
): { active: ObservedSession[]; history: ObservedSession[] } {
  const ordered = [...model.active, ...model.history];
  const rank = (session: ObservedSession) =>
    session.isNeeds || session.askKnown
      ? 0
      : drift(sources.get(sessionKey(session)), context).length
        ? 1
        : 2;
  const active = ordered.filter((session) => session.isActive || rank(session) < 2);
  const activeKeys = new Set(active.map(sessionKey));
  active.sort((left, right) => rank(left) - rank(right));
  return { active, history: ordered.filter((session) => !activeKeys.has(sessionKey(session))) };
}

export function buildSessionsScreen(
  payload: Row,
  model: Observed,
  chosenFor?: (session: Row) => PromptCandidate | null,
): SessionsScreen {
  const context = sessionsContext(payload);
  const rows = payloadSessionRows(payload);
  const sources = new Map(rows.map((session) => [sessionKey(session), session] as const));
  const asks = operationsAsks(payload, rows);
  const labels = harnessLabels(payload);
  const groups = groupSessions(model, sources, context);
  const projectKeys = new Map<string, string>();
  const projectKey = (project: string): string => {
    let key = projectKeys.get(project);
    if (key === undefined) {
      key = stableProjectKey({
        label: project,
        sessions: rows.filter((one) => String(one['project'] ?? '') === project),
      });
      projectKeys.set(project, key);
    }
    return key;
  };
  const seen = new Map<string, number>();
  const unique = (session: ObservedSession): string => {
    const base = `${sessionKey(session)}\u0000${session.project}`;
    const count = seen.get(base) ?? 0;
    seen.set(base, count + 1);
    return count ? `${base}#${String(count)}` : base;
  };
  const row = (session: ObservedSession, history: boolean): SessionRow => {
    const source = sources.get(sessionKey(session));
    const ask = source ? askFor(payload, source, asks) : null;
    const since =
      session.isEnded && source ? durationSince(context.generated, endedAt(source)) : '';
    return {
      key: unique(session),
      session,
      source,
      route: {
        view: 'session',
        project: session.project,
        harness: session.harness,
        session: session.sid,
      },
      harnessLabel: labels.get(session.harness) || session.harness,
      projectKey: projectKey(String(source?.['project'] ?? '')),
      goal: goalCell(source, context, source && chosenFor ? chosenFor(source) : null),
      drift: driftMark(source, context),
      endedSince: since ? `ended ${since} ago` : '',
      responsibility: ask ? ` · ${askResponsibility(payload, ask)}` : '',
      history,
    };
  };
  return {
    context,
    // The count under "Active now" counts the cards listed there, which include recorded drift. The model's
    // count is the board's and has no drift, so it read 0 above a listed drift card.
    counters: model.counters.map((counter) =>
      counter.label === 'ACTIVE NOW' ? { ...counter, value: groups.active.length } : counter,
    ),
    lede: anyChecked(rows, context) === false,
    active: groups.active.map((session) => row(session, false)),
    history: groups.history.map((session) => row(session, true)),
  };
}

/* One state word leads each row (usability review, 2026-10-20): the row once said "NOW · IDLE" and "QUIET"
   under "Active now", three words for one fact that read as a contradiction. Ended outranks the rest because
   an ended session waits on nobody. */
export function rowState(session: ObservedSession): string {
  if (session.isEnded) return 'Ended';
  if (session.isNeeds || session.askKnown) return 'Waiting on you';
  if (session.isWorking) return 'Working';
  // Only a published idle reads Idle: a missing or unknown state is not observed quiet.
  return session.isQuiet ? 'Idle' : 'State not published';
}

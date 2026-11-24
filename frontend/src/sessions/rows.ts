import { declaredRelations } from './declared';
import { nextNumber } from '../api/bootstrap';
import { stableProjectKey } from '../api/identity';
import type { RouteInput } from '../router/grammar';
import { formatDurationWords, observationAge } from '../shell/format';
import {
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
import { GLOSSARY, SESSION_ROW_WORDS } from '../language/glossary';

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
  /** The harnesses the board published a reading route for. A word that points at a check names it only
      where one could run. */
  readonly routes: ReadonlySet<string>;
}

export function sessionsContext(payload: Row): SessionsContext {
  return {
    annotate: payload['annotate'] === true,
    unreadable: String(payload['annotate_unreadable'] || ''),
    ask: payload['ask'] === true,
    generated: nextNumber(payload['generated']),
    routes: new Set(
      isRecord(payload['reading_routes'])
        ? Object.entries(payload['reading_routes'])
            .filter(([, route]) => isRecord(route))
            .map(([harness]) => harness)
        : [],
    ),
  };
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
  const age = dated.length
    ? formatDurationWords(observationAge(context.generated, Math.max(...dated)))
    : null;
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

/* One row's check against the words the reader holds now: an unasked check that found no departure, or a
   stored reading made against the current revision. A reading made against earlier words is not one. Null
   while annotations are off because the store's readings are not published. */
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

export interface GoalCell {
  readonly label: string;
  /** Every available goal opens the session at its goal, including saved words. A row with no goal says
      so in plain words and offers no action: the goal is added on the session page (owner, 2026-11-24). */
  readonly kind: 'off' | 'link' | 'none';
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
    return { label: 'Goal', kind: 'off', text: 'Annotations off', known: false };
  /* Words that exist but cannot be read are not words nobody typed: no "No goal yet", and no prompt offered
     as the goal over them. The store as a whole, or this session's own entry. */
  if (context.unreadable || source?.['annotation_goal_unreadable'] === true)
    return {
      label: 'Goal',
      kind: 'off',
      text: SESSION_ROW_WORDS.savedGoalUnavailable,
      known: false,
    };
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
      ? 'Goal · from /goal'
      : PROMPT_SOURCES.includes(String(source?.['annotation_goal_source']))
        ? 'Goal · from your prompt'
        : 'Goal · your words'
    : draft && draft.source === 'first-prompt'
      ? 'Goal · your first prompt'
      : draft && draft.source === SESSION_GOAL
        ? 'Goal · your /goal'
        : draft && draft.source === PROMPT_CHOSEN
          ? 'Goal · your chosen prompt'
          : text
            ? 'Goal · your latest prompt'
            : 'Goal';
  if (typed || text) return { label, kind: 'link', text, known: true };
  /* Saved outcome lines and no goal: the cell names what the reader wrote rather than "No goal yet", which
     would contradict words that exist. The session page reads such a row as having words to check. */
  const line = firstSavedLine(source);
  return line
    ? { label: GLOSSARY.doneLooksLike.plain, kind: 'link', text: line, known: true }
    : { label, kind: 'none', text: SESSION_ROW_WORDS.noGoalYet, known: false };
}

const hasText = (value: unknown): boolean => typeof value === 'string' && value.trim() !== '';

function firstSavedLine(source: Row | undefined): string {
  for (const n of [1, 2, 3, 4, 5, 6]) {
    const line = source?.[`annotation_line_${String(n)}`];
    if (hasText(line)) return String(line).trim();
  }
  return '';
}

/* Saved words the reader typed for this session: a goal, or any of the six expected-outcome lines. */
export function hasSavedWords(source: Row | undefined): boolean {
  return (
    hasText(source?.['annotation_goal']) ||
    [1, 2, 3, 4, 5, 6].some((n) => hasText(source?.[`annotation_line_${String(n)}`]))
  );
}

/* Whether the Goal cell's "No goal yet" is a statement the board can back: annotations on and readable, the
   store's own reason for the absence (never typed, or discarded), and nothing for the cell to show, neither
   saved words nor a draft. It is the one predicate both "No goal yet" filter chips read, so they keep the
   same rows. The store's reason is what separates an absence from the constructor's empty default, and a
   session whose entry could not be read publishes none and draws an unavailable goal instead. */
export function noGoalYet(
  source: Row | undefined,
  context: SessionsContext,
  goal: GoalCell,
): boolean {
  if (!context.annotate || context.unreadable || !source || goal.kind !== 'none') return false;
  if (source['annotation_goal_unreadable'] === true) return false;
  if (typeof source['annotation_goal'] !== 'string' || hasSavedWords(source)) return false;
  const discarded = nextNumber(source['annotation_discarded_at']);
  return hasText(source['annotation_goal_why']) || (discarded !== null && discarded > 0);
}

export type RowAbsence = 'notCheckedYet';

/* The one grey word at the right of the row, or none. Only Not checked yet: a goal the reader can check (saved
   words, or the draft Check progress would adopt, by the session page's own rule) and nothing in the
   published row recording any check: no stored reading, refusal, withheld reason, press, unasked check or
   raise. "No goal yet" is never drawn here: it lives in the Goal cell, once.
   Nothing for Codex (it shows no level), for a refused or withheld reading (a failed check is not "nothing
   departs"), for a harness with no reading route, or for a live estimate, which the list cannot see. */
export function rowAbsence(
  source: Row | undefined,
  context: SessionsContext,
  chosen: PromptCandidate | null = null,
): RowAbsence | null {
  if (!source || !context.annotate || context.unreadable) return null;
  if (source['annotation_goal_unreadable'] === true || source['harness'] === 'codex') return null;
  const draft = intentDraft(
    source,
    { annotate: context.annotate, unreadable: context.unreadable },
    chosen,
  );
  if (!hasSavedWords(source) && !draft) return null;
  const count = nextNumber(source['annotation_reading_count']);
  const checked =
    source['annotation_assessment'] != null ||
    source['annotation_reading_refused'] === true ||
    hasText(source['annotation_reading_withheld']) ||
    (count !== null && count > 0) ||
    source['departure_checked'] === true ||
    drift(source, context).length > 0;
  return checked || !context.routes.has(String(source['harness'] ?? '')) ? null : 'notCheckedYet';
}

/* A row's end and git facts, said once (owner, 2026-11-24). The model words them twice, as an outcome
   ("Stop observed; git state clean") and a git line ("Git state reported clean"), and adds a sentence
   saying git was not measured. The row keeps every measured fact and drops what only repeats one: an
   unmeasured git state, a git line the outcome already states, and a bare end the Now line ("Session
   reported its own end"), the tile and the descriptor's end age already carry. A changed-entry count is
   the one git fact the outcome lacks, so it follows. */
const GIT_NOT_MEASURED = '; git state not measured';
const ENDED_FACTS: Readonly<Record<string, string>> = {
  'Session ended': '',
  'Session ended; git state clean': 'Git state reported clean',
  'Session ended with uncommitted work': 'Ended with uncommitted work',
};
export function outcomeLine(outcome: string, git: string): string {
  const said = outcome.endsWith(GIT_NOT_MEASURED)
    ? outcome.slice(0, -GIT_NOT_MEASURED.length)
    : outcome;
  const end = ENDED_FACTS[said] ?? said;
  const changed = /^\d+ changed entries$/.test(git) ? git : '';
  return end && changed ? `${end} · ${changed}` : end || changed;
}

export type StateSegment = 'waiting' | 'working' | 'quiet' | 'ended';

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
  /** The grey word at the right of the row, or none. */
  readonly absence: RowAbsence | null;
  readonly drift: DriftMark | null;
  /** "started <duration> ago"; empty when a published start has no usable age. */
  readonly startedSince: string;
  /** Whether the session published a start at all. A row without one says so rather than leaving it out. */
  readonly startPublished: boolean;
  /** "ended <duration> ago", or empty. */
  readonly endedSince: string;
  readonly history: boolean;
  readonly worthALook: string | undefined;
  readonly showOutcome: boolean;
  readonly stateSegments: readonly StateSegment[] | undefined;
  readonly relations: ReturnType<typeof declaredRelations>;
}

export interface SessionsScreen {
  readonly context: SessionsContext;
  readonly active: readonly SessionRow[];
  readonly history: readonly SessionRow[];
}

/* The two groups. Promote only this screen's rows: changing the shared `isActive` would turn a stored
   reading into running evidence. A held request outranks
   a recorded departure, which outranks a working session; the sort is stable, so within a rank the lanes'
   own order stands. */
export function groupSessions(
  model: Observed,
  sources: ReadonlyMap<string, Row>,
  context: SessionsContext,
  evidenceRows: ReadonlySet<ObservedSession>,
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
  const activeRows = new Set(active);
  active.sort((left, right) => rank(left) - rank(right));
  return {
    active,
    history: ordered.filter(
      (session) =>
        !activeRows.has(session) &&
        (!activeKeys.has(sessionKey(session)) || evidenceRows.has(session)),
    ),
  };
}

export function buildSessionsScreen(
  payload: Row,
  model: Observed,
  chosenFor?: (session: Row) => PromptCandidate | null,
  selection?: AttentionSelection | null,
): SessionsScreen {
  const context = sessionsContext(payload);
  const rows = payloadSessionRows(payload);
  const sources = new Map(rows.map((session) => [sessionKey(session), session] as const));
  const labels = harnessLabels(payload);
  const worthALook = selection?.worthALook;
  const flaggedRows = [...(worthALook?.keys() ?? [])];
  const covered = new Set(flaggedRows.map(sessionKey));
  const dirtyOutcomes = new Set<ObservedSession>();
  for (const session of [...model.active, ...model.history]) {
    if (session.outcomeIcon !== 'worth-a-look') continue;
    const key = sessionKey(session);
    if (covered.has(key)) continue;
    covered.add(key);
    dirtyOutcomes.add(session);
  }
  // An active copy may hide a history copy of the same identity. Keep the occurrence that supplies
  // the flag or the dirty-end fact, so a stronger signal can still be traced to its row.
  const groups = groupSessions(
    model,
    sources,
    context,
    new Set([...flaggedRows, ...dirtyOutcomes]),
  );
  const segments = new Map<ObservedSession, StateSegment[]>();
  if (selection) {
    for (const [segment, members] of [
      ['waiting', selection.waitingOnYou],
      ['working', selection.working],
      ['quiet', selection.quiet],
      ['ended', selection.ended],
    ] as const) {
      for (const member of members) {
        const memberships = segments.get(member) ?? [];
        memberships.push(segment);
        segments.set(member, memberships);
      }
    }
  }
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
    const startedAt = nextNumber(source?.['started_at']);
    const started = formatDurationWords(observationAge(context.generated, startedAt));
    const chosen = source && chosenFor ? chosenFor(source) : null;
    const goal = goalCell(source, context, chosen);
    const since =
      session.isEnded && source
        ? formatDurationWords(observationAge(context.generated, endedAt(source)))
        : null;
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
      goal,
      absence: rowAbsence(source, context, chosen),
      drift: driftMark(source, context),
      startedSince: started ? `started ${started} ago` : '',
      startPublished: startedAt !== null && startedAt > 0,
      endedSince: since ? `ended ${since} ago` : '',
      worthALook: worthALook?.get(session),
      showOutcome:
        session.outcomeKnown &&
        (session.outcomeIcon !== 'worth-a-look' || dirtyOutcomes.has(session)),
      stateSegments: segments.get(session),
      history,
      relations: declaredRelations(payload, source),
    };
  };
  return {
    context,
    active: groups.active.map((session) => row(session, false)),
    history: groups.history.map((session) => row(session, true)),
  };
}

export { sessionState as rowState } from '../observed';
import type { AttentionSelection } from '../attention/select';

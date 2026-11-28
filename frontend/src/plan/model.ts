import {
  isTrackerSource,
  type PlanGroup,
  type PublishedLaneState,
  type PublishedPlanDate,
  type ReadyPlan,
} from '../api/plan';
import type { PayloadData } from '../api/types';
import { PLAN_WORDS } from '../language/glossary';
import { SESSION_TEXT_ORIGIN, sessionKey, sessionState, sessionTile, type Row } from '../observed';
import { observedFor } from '../observed/select';
import { harnessLabels } from '../sessions/rows';
import type { SessionRoute } from '../router/grammar';

export interface PlanModel {
  readonly asks: readonly PlanAsk[];
  readonly trackerAsks: ReadyPlan['trackerAsks'] | undefined;
  readonly waitingSessions: readonly PlanWaitingSession[];
  readonly goals: readonly PlanGoal[];
  readonly design: readonly PlanNote[];
  readonly tracker: readonly PlanTrackerItem[];
  readonly diagrams: readonly PlanNote[];
  readonly sources: readonly PlanSource[];
  readonly limits: string;
  readonly trackerIncomplete: boolean;
  readonly fileSections: {
    readonly design: boolean;
    readonly tracker: boolean;
    readonly diagrams: boolean;
  };
}

/* The published tracker words, kept as published. A lane with no measured state is null. */
export type PlanTrackerStatus = PlanGroup | 'Status not recognised';
export type PlanLaneState = PlanTrackerStatus | null;

export interface PlanSessionReference {
  readonly key: SessionRoute;
  readonly name: string;
  readonly state: 'working' | 'waiting' | 'quiet' | 'ended' | 'unknown';
}

export interface PlanGoal {
  readonly id: string;
  readonly title: string;
  readonly doneWhen: string | null;
  readonly proposal?: 'Proposed, not merged';
  readonly date?: PlanRepoDate | undefined;
  readonly lanes: readonly {
    readonly id: string;
    readonly title: string;
    readonly state: PlanLaneState;
    readonly sessions: readonly PlanSessionReference[] | null;
  }[];
}

export interface PlanAsk {
  readonly id: string;
  readonly text: string | null;
  readonly at: string | null;
  readonly timeLabel: 'from the log' | null;
  readonly source: string;
  readonly lane?: { readonly id: string; readonly title: string };
  readonly sessions: readonly PlanSessionReference[] | null;
}

interface PlanWaitingSession {
  readonly key: SessionRoute;
  readonly title: string;
  readonly harnessLabel: string;
  readonly request: string;
  /** False for the plain sentence Compass shows when the session published no request. */
  readonly requestAuthored: boolean;
}

export type PlanRepoDate = {
  readonly kind: 'changed' | 'proposed' | 'due';
  readonly at: string | null;
};

export interface PlanNote {
  readonly id: string;
  readonly title: string;
  readonly summary: string | null;
  readonly source: string;
  readonly date?: PlanRepoDate | undefined;
  readonly linkHosts?: readonly string[];
  /** Design notes only: false for a note the decision log has not marked decided. */
  readonly decided?: boolean;
}

interface PlanTrackerItem {
  readonly id: string;
  readonly title: string;
  readonly status: PlanTrackerStatus;
  readonly source: string;
  readonly date?: PlanRepoDate | undefined;
}

/* The closed reasons the server gives for a refused source, each with its plain sentence. The page
   shows the sentence and never the server's words; a reason not on this list reads as unreadable. */
export const SOURCE_REFUSALS = {
  missing: 'The file is missing.',
  unreadable: 'The source could not be read.',
  'not an owned regular file': 'The file is not a regular file you own.',
  'symbolic link': 'The file is a symbolic link.',
  'hard link': 'The same file has another name.',
  private: 'Marked private.',
  'over the byte cap': 'The file is larger than Compass reads.',
  'over the row cap': 'The file has more rows than Compass reads.',
  'over the brief folder entry cap': 'The lane-brief folder has more entries than Compass reads.',
  'guarded plan reads are unavailable on this platform':
    'Compass cannot read plan files on this platform.',
  'file changed before it could be read': 'The file changed while Compass read it.',
  malformed: 'The source did not have the expected format.',
  'Status not recognised': 'Compass did not recognise a status the source needs.',
  'not named in settings': 'The Plan settings do not name this file.',
  'outside declared root': 'The file is outside the folder the Plan settings declare.',
  'git reads are off': 'Git reads are off.',
  'git timed out': 'Git did not answer in time.',
  'git unavailable': 'Git is not available.',
  'branch missing': 'The branch is missing.',
  'not in branch': 'The file is not on the branch.',
  'not a regular file in branch': 'The file on the branch is not a regular file.',
  disabled: 'Tracker reads are off.',
  'cli-missing': 'The GitHub CLI is unavailable.',
  'signed-out': 'Sign in to GitHub with your GitHub CLI.',
  'rate-limited': 'GitHub is limiting reads.',
  timeout: 'GitHub did not answer in time.',
  'not-found-or-inaccessible': 'The source is missing or unavailable to your account.',
  'partial-result': 'GitHub returned an incomplete read.',
  'unreadable-output': 'The GitHub reply could not be read.',
  'limit-exceeded': 'The source has more items than Compass reads.',
  'cli-failed': 'The GitHub CLI could not read the source.',
  expired: 'The last read is out of date.',
  'plan-read-unavailable': 'Compass could not refresh the plan.',
  refreshing: PLAN_WORDS.readingGitHub,
  'unsafe lane identifier': 'The lane name has characters Compass does not accept.',
} as const;

export type PlanRefusalReason = keyof typeof SOURCE_REFUSALS;

export type PlanSource = {
  readonly id: string;
  readonly name: string;
} & (
  | {
      readonly status: 'ok';
      /** The lane-brief folder's row: how many briefs were read, when the folder held any. */
      readonly read?: number;
    }
  | { readonly status: 'refused'; readonly reason: PlanRefusalReason }
  | {
      readonly status: 'tracker';
      readonly state: ReadyPlan['sources'][number]['state'];
      readonly reason: PlanRefusalReason;
    }
);

const trackerStatuses: readonly PlanTrackerStatus[] = [
  'not_started',
  'running',
  'waiting',
  'blocked',
  'done',
  'dropped',
  'Status not recognised',
];

function known(state: string): state is PlanTrackerStatus {
  return (trackerStatuses as readonly string[]).includes(state);
}

/* A tracker row always has a status word, so an unknown one reads as not recognised. A lane's
   state is optional, so anything outside the closed list reads as not measured. */
function trackerStatus(group: string): PlanTrackerStatus {
  return known(group) ? group : 'Status not recognised';
}

function laneState(state: PublishedLaneState): PlanLaneState {
  return state !== null && known(state) ? state : null;
}

const sessionStates = {
  Working: 'working',
  'Waiting on you': 'waiting',
  Quiet: 'quiet',
  Ended: 'ended',
  'State not known': 'unknown',
} as const;

function repoDate(date: PublishedPlanDate | null): PlanRepoDate | undefined {
  if (date?.label === 'Due') return { kind: 'due', at: date.at };
  if (date?.label === 'Changed') return { kind: 'changed', at: date.at };
  if (date?.label === 'Proposed, not merged') return { kind: 'proposed', at: date.at };
  return undefined;
}

function sourceRefusal(reason: string | null): PlanRefusalReason {
  return reason !== null && Object.hasOwn(SOURCE_REFUSALS, reason)
    ? (reason as PlanRefusalReason)
    : 'unreadable';
}

type PublishedSource = ReadyPlan['sources'][number];

/* The file kinds a repository declares. A draft branch's copy of one publishes as "draft <kind>". */
const repositoryKinds: readonly string[] = [
  'goals',
  'decisions',
  'inventory',
  'tracker',
  'diagrams',
];
const draftPrefix = 'draft ';

function sourceStatus(source: PublishedSource) {
  return source.state === 'ok'
    ? ({ status: 'ok' } as const)
    : ({ status: 'refused', reason: sourceRefusal(source.reason) } as const);
}

/* One row per source, with three exceptions that kept a long plan's list unreadable: a draft branch
   that does not exist yet is one row for its repository, the briefs that were read are counted on
   the lane-brief folder's row (a refused brief keeps its own, and refused briefs with no lane name
   share one per reason), and a repository file is named by the
   label its settings give it, or by its kind and its place among that repository's files of the
   kind. A label shown once on the list is enough on its own. */
function planSources(published: readonly PublishedSource[]): PlanSource[] {
  const labels = new Map<string, number>();
  for (const { label } of published) labels.set(label, (labels.get(label) ?? 0) + 1);
  const named = (label: string, ...parts: readonly (string | null)[]) =>
    label && labels.get(label) === 1 ? label : [label, ...parts].filter(Boolean).join(' · ');
  const briefs = published.filter((source) => source.kind === 'lane brief');
  const briefsRead = briefs.filter((source) => source.state === 'ok').length;
  // A brief refused before its lane was named has no name to show, so those count by reason.
  const unnamedBriefs = new Map<PlanRefusalReason, number>();
  for (const brief of briefs) {
    const status = sourceStatus(brief);
    if (!brief.label && status.status === 'refused') {
      unnamedBriefs.set(status.reason, (unnamedBriefs.get(status.reason) ?? 0) + 1);
    }
  }
  const missingDrafts = new Set<string>();
  const rows: PlanSource[] = [];
  published.forEach((source, index) => {
    const id = String(index);
    const { label, kind } = source;
    if (isTrackerSource(source)) {
      rows.push({
        id,
        name: source.position === null ? label : `${label} ${source.position}`,
        status: 'tracker',
        state: source.state,
        reason: sourceRefusal(source.reason),
      });
      return;
    }
    const draft = kind.startsWith(draftPrefix);
    const fileKind = draft ? kind.slice(draftPrefix.length) : kind;
    if (kind === 'lane brief') {
      const status = sourceStatus(source);
      if (status.status === 'ok') return;
      if (label) {
        rows.push({ id, name: `Lane brief · ${label}`, ...status });
        return;
      }
      const count = unnamedBriefs.get(status.reason);
      if (count === undefined) return;
      unnamedBriefs.delete(status.reason);
      rows.push({ id, name: count === 1 ? 'Lane brief' : `${count} lane briefs`, ...status });
      return;
    }
    if (!repositoryKinds.includes(fileKind)) {
      // Any brief, read or refused, puts a count on the folder's row, so "0 read" is said outright.
      const counted = kind === 'lane briefs' && source.state === 'ok' && briefs.length > 0;
      rows.push({
        id,
        name: named(label, kind),
        ...sourceStatus(source),
        ...(counted ? { read: briefsRead } : {}),
      });
      return;
    }
    const status = sourceStatus(source);
    if (draft && status.status === 'refused' && status.reason === 'branch missing') {
      if (!missingDrafts.has(label)) rows.push({ id, name: named(label, 'draft'), ...status });
      missingDrafts.add(label);
      return;
    }
    const file =
      source.fileLabel ?? (source.position === null ? fileKind : `${fileKind} ${source.position}`);
    rows.push({ id, name: named(label, draft ? 'draft' : null, file), ...status });
  });
  return rows;
}

/* The ask a session sent through Compass, else the request its harness published with the wait, else
   the plain sentence Needs you uses. An unconfirmed wait's note is not a request, so it is not shown. */
function waitingRequest(row: ReturnType<typeof observedFor>['sessions'][number]): {
  readonly request: string;
  readonly requestAuthored: boolean;
} {
  if (row.askKnown) return { request: row.askText, requestAuthored: true };
  if (row[SESSION_TEXT_ORIGIN].blockNote) return { request: row.blockNote, requestAuthored: true };
  return { request: 'The agent is waiting for your input.', requestAuthored: false };
}

export function planModel(plan: ReadyPlan, board: PayloadData | null): PlanModel {
  const labels = harnessLabels((board ?? {}) as Row);
  const bySession = new Map<string, PlanSessionReference>();
  const waitingSessions: PlanWaitingSession[] = [];
  for (const row of observedFor(board).sessions) {
    if (!row.harness.trim() || !row.sid.trim()) continue;
    const key: SessionRoute = {
      view: 'session',
      harness: row.harness,
      session: row.sid,
      project: row.project,
    };
    const state = sessionState(row);
    const identity = sessionKey(row);
    if (bySession.has(identity)) continue;
    bySession.set(identity, {
      key,
      name: row.titleText,
      state: sessionStates[sessionTile(row, state)],
    });
    if (state === 'Waiting on you') {
      waitingSessions.push({
        key,
        title: row.titleText,
        harnessLabel: labels.get(row.harness) ?? row.harness,
        ...waitingRequest(row),
      });
    }
  }

  const lanes = new Map<string, PlanGoal['lanes'][number]>();
  for (const lane of plan.lanes) {
    const sessions =
      lane.sessions === null
        ? null
        : [...new Set(lane.sessions)].flatMap((key) => bySession.get(key) ?? []);
    lanes.set(lane.id, {
      id: lane.id,
      title: lane.title,
      state: laneState(lane.state),
      sessions,
    });
  }

  const trackerSources = plan.sources.filter(isTrackerSource);
  const sourceKinds = new Set(plan.sources.map(({ kind }) => kind));
  return {
    trackerIncomplete: trackerSources.some(({ state }) => state !== 'ok' && state !== 'empty'),
    fileSections: {
      design: sourceKinds.has('decisions'),
      tracker: sourceKinds.has('tracker'),
      diagrams: sourceKinds.has('diagrams'),
    },
    trackerAsks: plan.trackerAsksEnabled ? plan.trackerAsks : undefined,
    waitingSessions,
    goals: plan.goals.map((goal) => ({
      id: goal.id,
      title: goal.title,
      doneWhen: goal.doneWhen,
      date: goal.date?.label === 'Due' ? repoDate(goal.date) : undefined,
      ...(goal.proposal ? { proposal: goal.proposal } : {}),
      lanes: [...new Set(goal.lanes)].flatMap((id) => lanes.get(id) ?? []),
    })),
    asks: plan.asks.map(({ lane, ...ask }) => ({
      ...ask,
      ...(lane ? { lane } : {}),
      sessions: lane ? (lanes.get(lane.id)?.sessions ?? null) : null,
    })),
    design: plan.design.map((item, index) => ({
      id: String(index),
      title: item.title,
      summary: item.summary,
      decided: item.decided,
      source: item.source,
      date: repoDate(item.date),
    })),
    tracker: plan.tracker.map((item, index) => ({
      id: String(index),
      title: item.title,
      status: trackerStatus(item.group),
      source: item.source,
      date: repoDate(item.date),
    })),
    diagrams: plan.diagrams.map(({ title, caption, source, date, linkHosts }, index) => ({
      id: String(index),
      title,
      summary: caption === title ? null : caption,
      source,
      date: repoDate(date),
      linkHosts,
    })),
    sources: planSources(plan.sources),
    limits: plan.limits,
  };
}

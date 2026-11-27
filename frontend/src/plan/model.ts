import type { PlanGroup, PublishedLaneState, PublishedPlanDate, ReadyPlan } from '../api/plan';
import type { PayloadData } from '../api/types';
import { SESSION_TEXT_ORIGIN, sessionKey, sessionState, sessionTile, type Row } from '../observed';
import { observedFor } from '../observed/select';
import { harnessLabels } from '../sessions/rows';
import type { SessionRoute } from '../router/grammar';

export interface PlanModel {
  readonly asks: readonly PlanAsk[];
  readonly waitingSessions: readonly PlanWaitingSession[];
  readonly goals: readonly PlanGoal[];
  readonly design: readonly PlanNote[];
  readonly tracker: readonly PlanTrackerItem[];
  readonly diagrams: readonly PlanNote[];
  readonly sources: readonly PlanSource[];
  readonly limits: string;
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
  readonly lanes: readonly {
    readonly id: string;
    readonly title: string;
    readonly state: PlanLaneState;
    readonly sessions: readonly PlanSessionReference[] | null;
  }[];
}

export interface PlanAsk {
  readonly id: string;
  readonly text: string;
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
  readonly kind: 'changed' | 'proposed';
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
  'unsafe lane identifier': 'The lane name has characters Compass does not accept.',
} as const;

export type PlanRefusalReason = keyof typeof SOURCE_REFUSALS;

export type PlanSource = {
  readonly id: string;
  readonly name: string;
} & (
  | { readonly status: 'ok' }
  | { readonly status: 'refused'; readonly reason: PlanRefusalReason }
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
  if (date?.label === 'Changed') return { kind: 'changed', at: date.at };
  if (date?.label === 'Proposed, not merged') return { kind: 'proposed', at: date.at };
  return undefined;
}

function sourceRefusal(reason: string | null): PlanRefusalReason {
  return reason !== null && Object.hasOwn(SOURCE_REFUSALS, reason)
    ? (reason as PlanRefusalReason)
    : 'unreadable';
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

  const sourceLabels = new Map<string, number>();
  for (const { label } of plan.sources) sourceLabels.set(label, (sourceLabels.get(label) ?? 0) + 1);

  return {
    waitingSessions,
    goals: plan.goals.map((goal) => ({
      id: goal.id,
      title: goal.title,
      doneWhen: goal.doneWhen,
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
    sources: plan.sources.map(({ label, kind, state, reason }, index) => ({
      id: String(index),
      name:
        label && sourceLabels.get(label) === 1 ? label : [label, kind].filter(Boolean).join(' · '),
      ...(state === 'ok' ? { status: 'ok' } : { status: 'refused', reason: sourceRefusal(reason) }),
    })),
    limits: plan.limits,
  };
}

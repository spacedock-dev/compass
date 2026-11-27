import type { PlanGroup, PublishedLaneState, PublishedPlanDate, ReadyPlan } from '../api/plan';
import type { PayloadData } from '../api/types';
import { sessionKey, sessionState, sessionTile, type Row } from '../observed';
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
}

interface PlanTrackerItem {
  readonly id: string;
  readonly title: string;
  readonly status: PlanTrackerStatus;
  readonly source: string;
  readonly date?: PlanRepoDate | undefined;
}

export type PlanRefusalReason =
  | 'unknown'
  | 'git reads are off'
  | 'unreadable'
  | 'malformed'
  | 'symlink'
  | 'hard-link'
  | 'private'
  | 'unknown-structural-status';

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
  switch (reason) {
    case 'symbolic link':
      return 'symlink';
    case 'hard link':
      return 'hard-link';
    case 'unreadable':
    case 'malformed':
    case 'private':
    case 'unknown-structural-status':
    case 'git reads are off':
      return reason;
    default:
      return 'unknown';
  }
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
        request: row.askText,
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

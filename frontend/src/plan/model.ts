// Storybook mock-up of the published Plan data. The API contract is still to be decided.
export interface PlanModel {
  readonly asks: readonly PlanAsk[];
  readonly waitingSessions: readonly PlanWaitingSession[];
  readonly goals: readonly PlanGoal[];
  readonly design: readonly PlanNote[];
  readonly tracker: readonly PlanTrackerItem[];
  readonly diagrams: readonly PlanNote[];
  readonly sources: readonly PlanSource[];
  readonly limits: readonly ['health-information', 'confidential-text'];
}

export type PlanLaneState = 'done' | 'in-progress' | 'blocked' | 'planned';

export interface PlanGoal {
  readonly id: string;
  readonly title: string;
  readonly doneWhen: string;
  readonly lanes: readonly {
    readonly id: string;
    readonly title: string;
    readonly state: PlanLaneState;
  }[];
}

export interface PlanAsk {
  readonly id: string;
  readonly verb: 'ask';
  readonly text: string;
  readonly at: string;
}

interface PlanWaitingSession {
  readonly id: string;
  readonly title: string;
  readonly request: string;
}

export type PlanRepoDate = {
  readonly kind: 'changed' | 'proposed';
  readonly at: string;
};

export interface PlanNote {
  readonly id: string;
  readonly title: string;
  readonly summary: string;
  readonly date?: PlanRepoDate;
  readonly linkHost?: string;
}

interface PlanTrackerItem {
  readonly id: string;
  readonly title: string;
  readonly status: PlanLaneState | 'unrecognised';
  readonly date?: PlanRepoDate;
  readonly linkHost?: string;
}

export type PlanRefusalReason =
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

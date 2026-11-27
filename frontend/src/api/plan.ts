export type PlanGroup = 'not_started' | 'running' | 'waiting' | 'blocked' | 'done' | 'dropped';
export type PlanLaneStatus = 'blocked' | 'in-progress' | 'planned' | 'done';

export interface PublishedPlanDate {
  readonly label: 'Changed' | 'Proposed, not merged' | 'from the log';
  readonly at: string | null;
}

interface PublishedPlanSource {
  readonly label: string;
  readonly kind: string;
  readonly state: 'ok' | 'refused';
  readonly reason: string | null;
}

interface PublishedPlanItem {
  readonly title: string;
  readonly source: string;
  readonly date: PublishedPlanDate | null;
}

export interface ReadyPlan {
  readonly state: 'ready';
  readonly goals: readonly {
    readonly id: string;
    readonly title: string;
    readonly doneWhen: string | null;
    readonly lanes: readonly string[];
    readonly proposal: 'Proposed, not merged' | null;
  }[];
  readonly lanes: readonly {
    readonly id: string;
    readonly title: string;
    readonly doneWhen: string | null;
    readonly state: PlanLaneStatus | null;
    readonly date: PublishedPlanDate | null;
    readonly sessions: readonly string[] | null;
  }[];
  readonly asks: readonly {
    readonly id: string;
    readonly text: string;
    readonly at: string | null;
    readonly timeLabel: 'from the log' | null;
    readonly source: string;
    readonly lane: { readonly id: string; readonly title: string } | null;
  }[];
  readonly design: readonly (PublishedPlanItem & {
    readonly summary: string | null;
    readonly decided: boolean;
  })[];
  readonly tracker: readonly (PublishedPlanItem & {
    readonly group: PlanGroup | 'Status not recognised';
  })[];
  readonly inventory: readonly (PublishedPlanItem & {
    readonly group: 'built' | 'partial' | 'not_built' | 'Status not recognised';
  })[];
  readonly diagrams: readonly (PublishedPlanItem & {
    readonly caption: string;
    readonly kind: string;
    readonly linkHosts: readonly string[];
    readonly body: string;
  })[];
  readonly sources: readonly PublishedPlanSource[];
  readonly logRejected: number | null;
  readonly limits: string;
}

export type RefusedPlan = {
  readonly state: 'refused';
  readonly reason: string;
};

export type ConfiguredPlan = ReadyPlan | RefusedPlan;
export type PlanPayload = ConfiguredPlan | { readonly state: 'not-configured' };

export function configuredPlan(body: PlanPayload): body is ConfiguredPlan {
  if (body.state === 'refused') return typeof body.reason === 'string';
  return (
    body.state === 'ready' &&
    [
      body.goals,
      body.lanes,
      body.asks,
      body.design,
      body.tracker,
      body.diagrams,
      body.sources,
    ].every(Array.isArray) &&
    typeof body.limits === 'string'
  );
}

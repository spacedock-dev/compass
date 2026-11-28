export type PlanGroup = 'not_started' | 'running' | 'waiting' | 'blocked' | 'done' | 'dropped';
/* A tracker row's group, or the unknown-word marker; null when the lane is not measured. */
export type PublishedLaneState = PlanGroup | 'Status not recognised' | null;

export interface PublishedPlanDate {
  readonly label: 'Changed' | 'Proposed, not merged' | 'from the log' | 'Due' | 'Updated';
  readonly at: string | null;
}

interface PublishedPlanSource {
  readonly label: string;
  readonly kind: string;
  /** The short label the settings give a repository file, or null. */
  readonly fileLabel: string | null;
  /** The file's place among its repository's files of this kind, or null when it is the only one. */
  readonly position: number | null;
  readonly state: 'ok' | 'empty' | 'refused' | 'refreshing' | 'expired';
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
    readonly date: PublishedPlanDate | null;
  }[];
  readonly lanes: readonly {
    readonly id: string;
    readonly title: string;
    readonly doneWhen: string | null;
    readonly state: PublishedLaneState;
    readonly date: PublishedPlanDate | null;
    readonly sessions: readonly string[] | null;
  }[];
  readonly asks: readonly {
    readonly id: string;
    /** Null when the settings forbid the log verb's text on the board. */
    readonly text: string | null;
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
  readonly trackerRead: {
    readonly freshForMs: number;
    readonly localGoals: ReadyPlan['goals'];
    readonly localLanes: ReadyPlan['lanes'];
  } | null;
  readonly logRejected: number | null;
  readonly limits: string;
}

export type RefusedPlan = {
  readonly state: 'refused';
  readonly reason: string;
};

export type ConfiguredPlan = ReadyPlan | RefusedPlan;
export type PlanPayload = ConfiguredPlan | { readonly state: 'not-configured' };

/* What the page holds for the plan: not read yet, a read that has never succeeded, an authoritative
   absence (not configured, switched off or loopback only), or the last configured reply. A failed or
   unusable read after a configured one keeps that reply, so one slow Git read never hides the page. */
export type PlanReading =
  | ConfiguredPlan
  | { readonly state: 'unread' }
  | { readonly state: 'failed' }
  | { readonly state: 'none' };

export function planShown(reading: PlanReading): reading is ConfiguredPlan {
  return reading.state === 'ready' || reading.state === 'refused';
}

type Fields = Record<string, unknown>;

function isRecord(value: unknown): value is Fields {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
const text = (value: unknown): value is string => typeof value === 'string';
const textOrNull = (value: unknown) => value === null || text(value);
const texts = (value: unknown) => Array.isArray(value) && value.every(text);
const dateLabels: readonly unknown[] = [
  'Changed',
  'Proposed, not merged',
  'from the log',
  'Due',
  'Updated',
];
const planDate = (value: unknown) =>
  value === null ||
  (isRecord(value) && dateLabels.includes(value['label']) && textOrNull(value['at']));
const place = (value: unknown) =>
  value === null || (typeof value === 'number' && Number.isInteger(value) && value >= 1);
const dated = (item: Fields) =>
  text(item['title']) && text(item['source']) && planDate(item['date']);

/* Every field the page reads, checked to its published type, one list item at a time. An item
   that fails is dropped and the rest of the plan still shows; a reply whose lists or limits sentence
   are missing is an unusable read. Either way the page never throws on a missing field. */
const ITEM_CHECKS = {
  goals: (goal: Fields) =>
    text(goal['id']) &&
    text(goal['title']) &&
    textOrNull(goal['doneWhen']) &&
    texts(goal['lanes']) &&
    planDate(goal['date']) &&
    (goal['proposal'] === null || goal['proposal'] === 'Proposed, not merged'),
  lanes: (lane: Fields) =>
    text(lane['id']) &&
    text(lane['title']) &&
    textOrNull(lane['doneWhen']) &&
    textOrNull(lane['state']) &&
    planDate(lane['date']) &&
    (lane['sessions'] === null || texts(lane['sessions'])),
  // A log verb the settings declare with its text forbidden publishes an ask with no words.
  asks: (ask: Fields) =>
    text(ask['id']) &&
    textOrNull(ask['text']) &&
    text(ask['source']) &&
    textOrNull(ask['at']) &&
    (ask['timeLabel'] === null || ask['timeLabel'] === 'from the log') &&
    (ask['lane'] === null ||
      (isRecord(ask['lane']) && text(ask['lane']['id']) && text(ask['lane']['title']))),
  design: (item: Fields) =>
    dated(item) && textOrNull(item['summary']) && typeof item['decided'] === 'boolean',
  tracker: (item: Fields) => dated(item) && text(item['group']),
  diagrams: (item: Fields) => dated(item) && text(item['caption']) && texts(item['linkHosts']),
  sources: (source: Fields) =>
    text(source['label']) &&
    text(source['kind']) &&
    textOrNull(source['fileLabel']) &&
    place(source['position']) &&
    text(source['state']) &&
    ['ok', 'empty', 'refused', 'refreshing', 'expired'].includes(source['state']) &&
    textOrNull(source['reason']),
} as const;

export const isTrackerSource = (source: Pick<PublishedPlanSource, 'kind'>) =>
  source.kind.startsWith('github ');

const completeList = (value: unknown, check: (item: Fields) => boolean) =>
  Array.isArray(value) && value.every((item) => isRecord(item) && check(item));

export function expireTrackerRead(plan: ReadyPlan): ReadyPlan {
  if (!plan.trackerRead) return plan;
  return {
    ...plan,
    goals: plan.trackerRead.localGoals,
    lanes: plan.trackerRead.localLanes,
    sources: plan.sources.map((source) =>
      isTrackerSource(source) && (source.state === 'ok' || source.state === 'empty')
        ? { ...source, state: 'expired', reason: 'expired' }
        : source,
    ),
    trackerRead: null,
  };
}

/** The reply as the page may read it, or null when it is not a usable plan reply. */
export function usablePlan(body: unknown): ConfiguredPlan | null {
  if (!isRecord(body)) return null;
  if (body['state'] === 'refused') return text(body['reason']) ? (body as RefusedPlan) : null;
  if (body['state'] !== 'ready' || !text(body['limits'])) return null;
  const lists = Object.entries(ITEM_CHECKS);
  if (!lists.every(([list]) => Array.isArray(body[list]))) return null;
  const trackerRead = body['trackerRead'];
  if (trackerRead !== null) {
    if (
      !isRecord(trackerRead) ||
      typeof trackerRead['freshForMs'] !== 'number' ||
      !Number.isInteger(trackerRead['freshForMs']) ||
      trackerRead['freshForMs'] < 0 ||
      trackerRead['freshForMs'] > 30_000 ||
      !completeList(trackerRead['localGoals'], ITEM_CHECKS.goals) ||
      !completeList(trackerRead['localLanes'], ITEM_CHECKS.lanes) ||
      !completeList(body['goals'], ITEM_CHECKS.goals) ||
      !completeList(body['lanes'], ITEM_CHECKS.lanes) ||
      !completeList(body['sources'], ITEM_CHECKS.sources)
    )
      return null;
  } else if (
    (body['sources'] as unknown[]).some(
      (source) =>
        isRecord(source) &&
        typeof source['kind'] === 'string' &&
        isTrackerSource({ kind: source['kind'] }) &&
        (source['state'] === 'ok' || source['state'] === 'empty'),
    )
  )
    return null;
  const kept = lists.map(([list, check]) => [
    list,
    (body[list] as readonly unknown[]).filter((item) => isRecord(item) && check(item)),
  ]);
  return { ...body, ...Object.fromEntries(kept) } as unknown as ReadyPlan;
}

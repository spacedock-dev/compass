export type PlanGroup = 'not_started' | 'running' | 'waiting' | 'blocked' | 'done' | 'dropped';
/* A tracker row's group, or the unknown-word marker; null when the lane is not measured. */
export type PublishedLaneState = PlanGroup | 'Status not recognised' | null;

export interface PublishedPlanDate {
  readonly label:
    | 'Changed'
    | 'Proposed, not merged'
    | 'from the log'
    | 'Due'
    | 'Updated'
    | 'Target'
    | 'Completed';
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

interface PublishedTrackerAsk {
  readonly title: string;
  readonly linkHost: 'github.com' | 'linear.app';
  readonly source: string;
  readonly lane: string;
  readonly goals: readonly string[];
}

interface PlanRowChanges<Row> {
  readonly remove: readonly string[];
  readonly upsert: readonly Row[];
}

interface TrackerReadUpdate {
  readonly freshForMs: number;
  readonly goals: PlanRowChanges<ReadyPlan['goals'][number]>;
  readonly lanes: PlanRowChanges<ReadyPlan['lanes'][number]>;
  readonly sources: ReadyPlan['sources'];
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
    readonly additionalDates?: readonly PublishedPlanDate[];
  }[];
  readonly lanes: readonly {
    readonly id: string;
    readonly title: string;
    readonly doneWhen: string | null;
    readonly state: PublishedLaneState;
    readonly date: PublishedPlanDate | null;
    readonly additionalDates?: readonly PublishedPlanDate[];
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
  readonly trackerAsksEnabled: boolean;
  readonly trackerAsks: readonly PublishedTrackerAsk[] | null;
  readonly trackerAsksFreshForMs: number | null;
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
    readonly localSources?: ReadyPlan['sources'];
    readonly updates?: readonly TrackerReadUpdate[];
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
  'Target',
  'Completed',
];
const dateFields = (value: unknown) =>
  isRecord(value) && dateLabels.includes(value['label']) && textOrNull(value['at']);
const planDate = (value: unknown) => value === null || dateFields(value);
const additionalDates = (value: unknown) =>
  value === undefined || (Array.isArray(value) && value.every(dateFields));
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
    additionalDates(goal['additionalDates']) &&
    (goal['proposal'] === null || goal['proposal'] === 'Proposed, not merged'),
  lanes: (lane: Fields) =>
    text(lane['id']) &&
    text(lane['title']) &&
    textOrNull(lane['doneWhen']) &&
    textOrNull(lane['state']) &&
    planDate(lane['date']) &&
    additionalDates(lane['additionalDates']) &&
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

export function trackerProvider({ kind }: Pick<PublishedPlanSource, 'kind'>) {
  if (kind.startsWith('github ')) return 'github';
  if (kind === 'linear project' || kind === 'linear milestone') return 'linear';
  return null;
}

export const isTrackerSource = (source: Pick<PublishedPlanSource, 'kind'>) =>
  trackerProvider(source) !== null;

const completeList = (value: unknown, check: (item: Fields) => boolean) =>
  Array.isArray(value) && value.every((item) => isRecord(item) && check(item));

const trackerAsk = (item: Fields) =>
  text(item['title']) &&
  (item['linkHost'] === 'github.com' || item['linkHost'] === 'linear.app') &&
  text(item['source']) &&
  text(item['lane']) &&
  texts(item['goals']);

const freshness = (value: unknown): value is number =>
  typeof value === 'number' && Number.isInteger(value) && value >= 0 && value <= 30_000;

function applyRowChanges<Row extends { readonly id: string }>(
  rows: readonly Row[],
  changes: PlanRowChanges<Row>,
): readonly Row[] {
  const removed = new Set(changes.remove);
  const replacements = new Map<string, Row[]>();
  for (const row of changes.upsert) {
    const group = replacements.get(row.id);
    if (group) group.push(row);
    else replacements.set(row.id, [row]);
  }
  const replaced = new Set(replacements.keys());
  const kept = rows.flatMap((row) => {
    if (removed.has(row.id)) return [];
    if (!replaced.has(row.id)) return [row];
    const next = replacements.get(row.id) ?? [];
    replacements.delete(row.id);
    return next;
  });
  return [...kept, ...[...replacements.values()].flat()];
}

function expireTrackerRead(plan: ReadyPlan, elapsed: number): ReadyPlan {
  let current = plan;
  while (current.trackerRead && current.trackerRead.freshForMs <= elapsed) {
    const read = current.trackerRead;
    const [update, ...updates] = read.updates ?? [];
    if (!update) {
      return {
        ...current,
        goals: read.localGoals,
        lanes: read.localLanes,
        sources:
          read.localSources ??
          current.sources.map((source) =>
            isTrackerSource(source) && (source.state === 'ok' || source.state === 'empty')
              ? { ...source, state: 'expired', reason: 'expired' }
              : source,
          ),
        trackerRead: null,
      };
    }
    current = {
      ...current,
      goals: applyRowChanges(current.goals, update.goals),
      lanes: applyRowChanges(current.lanes, update.lanes),
      sources: update.sources,
      trackerRead: { ...read, freshForMs: update.freshForMs, updates },
    };
  }
  return current;
}

export function expirePlanReadings(plan: ReadyPlan, elapsed: number): ReadyPlan {
  const current = expireTrackerRead(plan, elapsed);
  return current.trackerAsksFreshForMs !== null && current.trackerAsksFreshForMs <= elapsed
    ? { ...current, trackerAsks: null, trackerAsksFreshForMs: null }
    : current;
}

export function failTrackerRead(plan: ReadyPlan): ReadyPlan {
  const local = expirePlanReadings(plan, Infinity);
  if (!local.sources.some((source) => isTrackerSource(source) && source.state === 'refreshing')) {
    return local;
  }
  return {
    ...local,
    sources: local.sources.map((source) =>
      isTrackerSource(source) && source.state === 'refreshing'
        ? { ...source, state: 'refused', reason: 'plan-read-unavailable' }
        : source,
    ),
  };
}

function rowChanges(value: unknown, check: (item: Fields) => boolean) {
  return isRecord(value) && texts(value['remove']) && completeList(value['upsert'], check);
}

function validUpdates(updates: unknown, initial: number): boolean {
  if (updates === undefined) return true;
  if (!Array.isArray(updates) || updates.length > 31) return false;
  let previous = initial;
  for (const update of updates) {
    if (
      !isRecord(update) ||
      !freshness(update['freshForMs']) ||
      update['freshForMs'] < previous ||
      !rowChanges(update['goals'], ITEM_CHECKS.goals) ||
      !rowChanges(update['lanes'], ITEM_CHECKS.lanes) ||
      !completeList(update['sources'], ITEM_CHECKS.sources)
    )
      return false;
    previous = update['freshForMs'];
  }
  return true;
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
      !freshness(trackerRead['freshForMs']) ||
      !completeList(trackerRead['localGoals'], ITEM_CHECKS.goals) ||
      !completeList(trackerRead['localLanes'], ITEM_CHECKS.lanes) ||
      (trackerRead['localSources'] !== undefined &&
        !completeList(trackerRead['localSources'], ITEM_CHECKS.sources)) ||
      !validUpdates(trackerRead['updates'], trackerRead['freshForMs']) ||
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
  const trackerAsksEnabled = body['trackerAsksEnabled'] === true;
  const askFreshness = body['trackerAsksFreshForMs'];
  const trackerAsks =
    trackerAsksEnabled &&
    trackerRead !== null &&
    freshness(askFreshness) &&
    completeList(body['trackerAsks'], trackerAsk)
      ? body['trackerAsks']
      : null;
  return {
    ...body,
    ...Object.fromEntries(kept),
    trackerAsksEnabled,
    trackerAsks,
    trackerAsksFreshForMs: trackerAsks === null ? null : askFreshness,
  } as unknown as ReadyPlan;
}

export type PlanGroup = 'not_started' | 'running' | 'waiting' | 'blocked' | 'done' | 'dropped';
/* A tracker row's group, or the unknown-word marker; null when the lane is not measured. */
export type PublishedLaneState = PlanGroup | 'Status not recognised' | null;

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
    readonly state: PublishedLaneState;
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
const records = (value: unknown, check: (item: Fields) => boolean) =>
  Array.isArray(value) && value.every((item) => isRecord(item) && check(item));
const dateLabels: readonly unknown[] = ['Changed', 'Proposed, not merged', 'from the log'];
const planDate = (value: unknown) =>
  value === null ||
  (isRecord(value) && dateLabels.includes(value['label']) && textOrNull(value['at']));
const dated = (item: Fields) =>
  text(item['title']) && text(item['source']) && planDate(item['date']);

/* Every field the page reads, checked to its published type. A reply that fails any check is an
   unusable read, so a page never renders half a plan or throws on a missing field. */
function readyShape(body: Fields): boolean {
  return (
    records(
      body['goals'],
      (goal) =>
        text(goal['id']) &&
        text(goal['title']) &&
        textOrNull(goal['doneWhen']) &&
        texts(goal['lanes']) &&
        (goal['proposal'] === null || goal['proposal'] === 'Proposed, not merged'),
    ) &&
    records(
      body['lanes'],
      (lane) =>
        text(lane['id']) &&
        text(lane['title']) &&
        textOrNull(lane['doneWhen']) &&
        textOrNull(lane['state']) &&
        planDate(lane['date']) &&
        (lane['sessions'] === null || texts(lane['sessions'])),
    ) &&
    records(
      body['asks'],
      (ask) =>
        text(ask['id']) &&
        text(ask['text']) &&
        text(ask['source']) &&
        textOrNull(ask['at']) &&
        (ask['timeLabel'] === null || ask['timeLabel'] === 'from the log') &&
        (ask['lane'] === null ||
          (isRecord(ask['lane']) && text(ask['lane']['id']) && text(ask['lane']['title']))),
    ) &&
    records(
      body['design'],
      (item) => dated(item) && textOrNull(item['summary']) && typeof item['decided'] === 'boolean',
    ) &&
    records(body['tracker'], (item) => dated(item) && text(item['group'])) &&
    records(
      body['diagrams'],
      (item) => dated(item) && text(item['caption']) && texts(item['linkHosts']),
    ) &&
    records(
      body['sources'],
      (source) =>
        text(source['label']) &&
        text(source['kind']) &&
        (source['state'] === 'ok' || source['state'] === 'refused') &&
        textOrNull(source['reason']),
    ) &&
    text(body['limits'])
  );
}

export function configuredPlan(body: unknown): body is ConfiguredPlan {
  if (!isRecord(body)) return false;
  if (body['state'] === 'refused') return text(body['reason']);
  return body['state'] === 'ready' && readyShape(body);
}

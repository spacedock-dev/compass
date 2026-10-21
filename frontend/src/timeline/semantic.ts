/* The semantic model the timeline reads, and the lane registry and event selection it derives from it.

   THIS FILE IS THE ONE ADAPTER between the project context payload (`GET /api/project-context`, its
   `semantic` object) and the timeline. Until the observed model of the sessions step is joined here, the
   timeline reads that payload through `readSemantic` and nothing else does; when the join comes, it
   replaces this file's input and leaves `./Timeline` alone.

   Ported from `projectLaneRegistry`, `projectGlobalEvents`, `projectDecisionEvents`,
   `projectVisibleRegistry` and their helpers in the legacy `project.js`, which win over any prose. What is
   not ported, and is the project step's: the lane rails and graph marks drawn beside each row, and the
   unbound-contributor strip. The selection of which events appear in Active, All events and Decisions is
   ported whole, because that selection is what the reader's filter choice means. */

import { stripPasteWrapper } from '../api/paste';

export interface SessionRef {
  readonly harness: string;
  readonly sid: string;
}

export interface Fact {
  readonly id: string;
  /** The published time when it is a finite number, else null. What a row prints. */
  readonly at: number | null;
  /** `Number(at)` as the legacy sorts read it, NaN included. See `sortOrder`. */
  readonly order: number;
  readonly type: string;
  readonly summary: string;
  readonly stage: string;
  readonly targetStage: string;
  readonly sourceKind: string;
  /** What the fact declared about its own scope, lowercased. */
  readonly scope: string;
  readonly by: string;
  readonly decision: string;
  readonly applicationState: string;
  readonly workItemId: string;
  readonly session: SessionRef | null;
  readonly evidenceSource: string | null;
  readonly evidenceConfidence: string | null;
  readonly currentState: boolean;
  readonly contributorLabel: string | null;
  readonly contributorVerified: boolean;
  readonly workflowBinding: string;
  readonly workflowEntity: string;
}

export interface SourceBinding {
  readonly source: string;
  readonly value: string;
}

export interface WorkItem {
  readonly id: string;
  readonly label: string;
  readonly kind: string;
  readonly bindings: readonly SourceBinding[];
}

export interface Relation {
  readonly type: string;
  readonly from: string;
  readonly to: string;
  readonly evidenceRef: string;
  readonly confidence: string;
}

export interface Head {
  readonly workItemId: string;
  readonly status: string;
  readonly stage: string;
  readonly latestMeaningfulEvent: string;
}

export interface ActivityNode {
  readonly order: number;
  readonly kind: string;
  readonly workItemIds: readonly string[];
}

export interface Intent {
  readonly projectionId: string;
  readonly order: number;
  readonly summary: string;
  readonly derivedFrom: string;
}

export interface Episode {
  readonly intentId: string;
  readonly adaptationFact: string;
  readonly confidence: string;
}

export interface HistoryEvent {
  readonly eventType: string;
  readonly sourceIdentity: string;
  readonly workBinding: string;
}

export interface SemanticModel {
  readonly facts: readonly Fact[];
  readonly workItems: readonly WorkItem[];
  readonly relations: readonly Relation[];
  readonly heads: readonly Head[];
  /** null when the payload has no `activity.nodes` key at all, which is not an empty list. */
  readonly nodes: readonly ActivityNode[] | null;
  readonly historyNodes: readonly ActivityNode[];
  readonly steering: readonly Intent[];
  readonly intents: readonly Intent[];
  readonly episodes: readonly Episode[];
  readonly history: {
    readonly reason: string;
    readonly windowSec: number | null;
    readonly events: readonly HistoryEvent[];
  };
}

/* One worker the focused session delegated to, as the delegated-work lanes publish it. */
export interface Delegation {
  readonly workItemId?: string;
  readonly source?: string;
  readonly workflowBinding?: string;
  readonly entity?: string;
  readonly observerSid?: string;
  readonly worker: string;
  readonly at: number;
  readonly assignment: string;
  readonly parentSession?: string;
}

/* ------------------------------------------------------------------------------------------------
   Reading the payload. Nothing is trusted: every field is coerced to what the code below needs, and an
   absent one stays absent (null, empty) rather than becoming a default that looks like a measurement. */

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

const asList = (value: unknown): unknown[] => (Array.isArray(value) ? value : []);
const text = (value: unknown): string =>
  typeof value === 'string' ? value : typeof value === 'number' ? String(value) : '';
const finite = (value: unknown): number | null => {
  if (value === null || value === undefined || value === '') return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
};

function readFact(raw: unknown): Fact | null {
  if (!isRecord(raw)) return null;
  const session = isRecord(raw.source_session) ? raw.source_session : null;
  const harness = text(session?.harness);
  const sid = text(session?.sid);
  const evidence = isRecord(raw.evidence) ? raw.evidence : null;
  const contributor = isRecord(raw.contributor) ? raw.contributor : null;
  return {
    id: text(raw.fact_id),
    at: finite(raw.at),
    order: Number(raw.at),
    type: text(raw.type),
    /* A direction is the reader's words: the harness's paste tags are never part of them. */
    summary:
      text(raw.type) === 'user_message' ? stripPasteWrapper(text(raw.summary)) : text(raw.summary),
    stage: text(raw.stage),
    targetStage: text(raw.target_stage),
    sourceKind: text(raw.source_kind),
    scope: text(raw.scope).toLowerCase(),
    by: text(raw.by),
    decision: text(raw.decision),
    applicationState: text(raw.application_state),
    workItemId: text(raw.work_item_id),
    session: harness && sid ? { harness, sid } : null,
    evidenceSource: evidence && text(evidence.source) !== '' ? text(evidence.source) : null,
    evidenceConfidence:
      evidence && text(evidence.confidence) !== '' ? text(evidence.confidence) : null,
    currentState: raw.current_state === true,
    contributorLabel:
      contributor && text(contributor.label) !== '' ? text(contributor.label) : null,
    contributorVerified: contributor?.verified === true,
    workflowBinding: text(raw.workflow_binding),
    workflowEntity: text(raw.workflow_entity),
  };
}

function readItem(raw: unknown): WorkItem | null {
  if (!isRecord(raw)) return null;
  return {
    id: text(raw.work_item_id),
    label: text(raw.label),
    kind: text(raw.kind),
    bindings: asList(raw.source_bindings)
      .filter(isRecord)
      .map((binding) => ({ source: text(binding.source), value: text(binding.value) })),
  };
}

function readNodes(raw: unknown): ActivityNode[] {
  return asList(raw)
    .filter(isRecord)
    .map((node) => ({
      order: Number(node.at),
      kind: text(node.kind),
      workItemIds: asList(node.work_item_ids).map(text),
    }));
}

function readIntents(raw: unknown): Intent[] {
  return asList(raw)
    .filter(isRecord)
    .map((intent) => ({
      projectionId: text(intent.projection_id),
      order: Number(intent.at),
      summary: stripPasteWrapper(text(intent.summary)),
      derivedFrom: text(intent.derived_from),
    }));
}

export function readSemantic(raw: unknown): SemanticModel {
  const model = isRecord(raw) ? raw : {};
  const projections = isRecord(model.projections) ? model.projections : {};
  const activity = isRecord(projections.activity) ? projections.activity : {};
  const history = isRecord(model.history) ? model.history : {};
  return {
    facts: asList(model.facts)
      .map(readFact)
      .filter((fact): fact is Fact => fact !== null),
    workItems: asList(model.work_items)
      .map(readItem)
      .filter((item): item is WorkItem => item !== null),
    relations: asList(model.relations)
      .filter(isRecord)
      .map((relation) => ({
        type: text(relation.type),
        from: text(relation.from),
        to: text(relation.to),
        evidenceRef: text(relation.evidence_ref),
        confidence: text(relation.confidence),
      })),
    heads: asList(projections.trail_heads)
      .filter(isRecord)
      .map((head) => ({
        workItemId: text(head.work_item_id),
        status: text(head.status),
        stage: text(head.stage),
        latestMeaningfulEvent: text(head.latest_meaningful_event),
      })),
    // biome-ignore lint/suspicious/noPrototypeBuiltins: Object.hasOwn would change the shipped page bytes, and this port leaves them alone.
    nodes: Object.prototype.hasOwnProperty.call(activity, 'nodes')
      ? readNodes(activity.nodes)
      : null,
    historyNodes: readNodes(activity.history_nodes),
    steering: readIntents(activity.steering),
    intents: readIntents(projections.operator_intents),
    episodes: asList(projections.steering_episodes)
      .filter(isRecord)
      .map((episode) => ({
        intentId: text(episode.intent_id),
        adaptationFact: text(episode.adaptation_fact),
        confidence: text(episode.confidence),
      })),
    history: {
      reason: text(history.reason),
      windowSec: finite(history.window_sec),
      events: asList(history.events)
        .filter(isRecord)
        .map((event) => ({
          eventType: text(event.event_type),
          sourceIdentity: text(event.source_identity),
          workBinding: text(event.work_binding),
        })),
    },
  };
}

/* The project-wide read is canonical for a work item's label: a focused read can carry a stale one, and the
   same task must not be named two ways on one page. */
export function withCanonicalLabels(
  model: SemanticModel,
  project: SemanticModel | null,
): SemanticModel {
  if (!project) return model;
  const labels = new Map(project.workItems.map((item) => [item.id, item.label]));
  return {
    ...model,
    workItems: model.workItems.map((item) => {
      const label = labels.get(item.id);
      return label ? { ...item, label } : item;
    }),
  };
}

/* ------------------------------------------------------------------------------------------------
   The registry: one lane per origin session (the "First Officer" lanes) and one per work item. */

export type GraphMode = 'active' | 'all' | 'decisions';

export interface FoLane {
  readonly kind: 'fo';
  readonly key: string;
  readonly label: string;
  readonly events: readonly Fact[];
  readonly directions: readonly Fact[];
  readonly episodeByFact: ReadonlyMap<string, Episode>;
  readonly suppressedDirections: readonly Fact[];
}

export interface TaskLane {
  readonly kind: 'task';
  readonly key: string;
  readonly label: string;
  readonly workItemId: string;
  readonly item: WorkItem;
  readonly events: readonly Fact[];
  readonly contributors: readonly Delegation[];
  readonly head: Head | null;
  readonly headFact: Fact | null;
  readonly current: boolean;
  readonly working: boolean;
  readonly unreturned: boolean;
  readonly returned: boolean;
  readonly dispatchCount: number;
  readonly retryEvidence: boolean;
}

export type Lane = FoLane | TaskLane;

export interface Registry {
  readonly foKey: string;
  readonly foKeys: readonly string[];
  readonly lanes: readonly Lane[];
  readonly laneByKey: ReadonlyMap<string, Lane>;
  readonly unboundContributors: readonly Delegation[];
}

export const compatKey = (ref: {
  readonly harness?: unknown;
  readonly sid?: unknown;
  readonly session?: unknown;
}): string => `${text(ref.harness)}:${text(ref.sid) || text(ref.session)}`;

/* Newest first by `Number(at)`, with a missing or non-numeric time as NaN. That is what the legacy sorts do,
   and it is deliberately not "cleaned" to treat a missing time as 0: a comparator that returns NaN leaves
   the engine to order such facts, and only reproducing the NaN reproduces the order a reader of the legacy
   page sees. The two sorts the legacy page does write with `|| 0` use `order || 0` below. */
const newestFirst = (a: { readonly order: number }, b: { readonly order: number }): number =>
  b.order - a.order;

const factSessionKey = (fact: Fact): string =>
  fact.session ? `${fact.session.harness}:${fact.session.sid}` : '';

export function taskTitle(label: string | null | undefined): string {
  const words = (label || 'Task').replace(/-/g, ' ');
  return words.replace(/^./, (first) => first.toUpperCase());
}

export function eventKind(fact: Fact): string {
  if (['prepared_dispatch', 'assignment', 'work_birth'].includes(fact.type)) return 'dispatch';
  if (['work_result', 'result', 'final_output'].includes(fact.type)) return 'result';
  if (['decision', 'gate_decision'].includes(fact.type)) return 'decision';
  if (['observer_snapshot', 'goal_shift'].includes(fact.type)) return 'observed_goal';
  if (['stage_transition', 'checkpoint', 'progress_head'].includes(fact.type)) return 'progress';
  return '';
}

/* These shapes came from a live 24-hour ledger audit of the legacy page. They are source context, but none
   independently changed intent, work, a decision or an outcome, so the newest retained entry owns them as
   source-only text. */
const EXCLUDED_DIRECTION =
  /^(?:interleved events\?|if i click last\.?|do 5 more rounds of mirror reflection\.?|oh now i see it\.?|not sure if this is useful:\s*https?:.*|run it, and continue the loop\.?|id you run the server\?|read\s+[~/].*|look here:\s*https?:.*|and tell me what you find in the mock|continue the rounds\.?|ok let's try this|what is this\?|keep going|let's get that panel review|did you get a review from IA advisor and UX expert\?)$/i;

const IGNORED_TOKENS = new Set([
  'a',
  'again',
  'an',
  'can',
  'could',
  'i',
  'let',
  'please',
  'the',
  'this',
  'us',
  'we',
  'would',
  'you',
]);

function directionTokens(summary: string): string[] {
  return (summary.toLowerCase().match(/[a-z0-9]+/g) ?? []).filter(
    (token) => !IGNORED_TOKENS.has(token),
  );
}

export function directionRationale(summary: string): string {
  if (
    /(?:can't see|don't see|still weird|kind(?:of|a) works|not readable|long delay|missing a lot|without actual information|without telling me|recovered from crash|great, except)/i.test(
      summary,
    )
  ) {
    return 'Changes understanding of an observed outcome or work condition.';
  }
  if (
    /(?:should|don't mean|don't care|all prototype|not compact steering|model the data first|fresh context|few words|sparate|derived goals?|active lanes?)/i.test(
      summary,
    )
  ) {
    return 'Changes understanding of a product or scope decision.';
  }
  if (
    /(?:continuously check|sketch first|panel review|review from|try xterm|session within tmux|dev workflow|adjustment between rounds)/i.test(
      summary,
    )
  ) {
    return 'Changes understanding of the work or its validation method.';
  }
  return "Changes understanding of the operator's intent.";
}

/* The directions worth a row: not low-signal, not transport, not a near duplicate of a newer one within
   fifteen minutes. Newest first. */
function meaningfulDirections(
  intents: readonly Intent[],
  factById: ReadonlyMap<string, Fact>,
): Fact[] {
  const lowSignal = /^(?:ok(?:ay)?|alright|thanks?|working|oh\b.*\b(?:see|got it))\W*$/i;
  const transport = /^(?:env\b|pwd\b|ls\b|cd\b|git\s|\/[A-Za-z0-9_.-]|[A-Za-z0-9_.-]+\/)/i;
  const selected: Fact[] = [];
  const clusters: { at: number; tokens: string[] }[] = [];
  const exact = new Set<string>();
  [...intents].sort(newestFirst).forEach((intent) => {
    const summary = intent.summary.trim();
    const fact = factById.get(intent.derivedFrom);
    const normalized = summary.toLowerCase().replace(/\W+/g, ' ').trim();
    if (
      !fact ||
      summary.length < 4 ||
      lowSignal.test(summary) ||
      transport.test(summary) ||
      EXCLUDED_DIRECTION.test(summary) ||
      exact.has(normalized)
    )
      return;
    const tokens = directionTokens(summary);
    if (!tokens.length) return;
    const at = intent.order || fact.order || 0;
    const duplicate = clusters.some((cluster) => {
      if (cluster.at - at > 15 * 60 || tokens[0] !== cluster.tokens[0]) return false;
      const shared = new Set(tokens.filter((token) => cluster.tokens.includes(token))).size;
      return shared / Math.min(new Set(tokens).size, new Set(cluster.tokens).size) >= 0.8;
    });
    if (duplicate) return;
    clusters.push({ at, tokens });
    exact.add(normalized);
    selected.push(fact);
  });
  return selected;
}

/* Which work item a delegated worker belongs to: its own id when the model knows it and it is not merely
   derived, else the item bound to its workflow entity, else the item an assignment event of its observer
   names. A worker with none is "unbound" and does not bind a lane. */
function delegationWorkItem(model: SemanticModel, row: Delegation): string {
  if (
    row.workItemId &&
    model.workItems.some((item) => item.id === row.workItemId) &&
    !(row.source ?? '').includes('derived')
  ) {
    return row.workItemId;
  }
  if (!row.workflowBinding || !row.entity) return '';
  const binding = `${row.workflowBinding}:${row.entity}`;
  const item = model.workItems.find((candidate) =>
    candidate.bindings.some((source) => source.value === binding),
  );
  if (item) return item.id;
  const assignment = model.history.events.find(
    (event) =>
      event.eventType === 'assignment' &&
      row.observerSid &&
      event.sourceIdentity === `codex:${row.observerSid}`,
  );
  return assignment?.workBinding ?? '';
}

export interface RegistryInput {
  readonly model: SemanticModel;
  readonly delegations?: readonly Delegation[];
  /** The focused session, whose state decides whether a final output is yet a result. */
  readonly focus?: (SessionRef & { readonly state?: string }) | null;
  /** The project's sessions, which name the First Officer lanes when no session is focused. */
  readonly origins?: readonly SessionRef[];
  /** The focused session's compatibility key, for the lane of a project that published no session at all. */
  readonly fallbackSession?: string;
}

export function buildRegistry(input: RegistryInput): Registry {
  const { model } = input;
  const delegations = input.delegations ?? [];
  const focus = input.focus ?? null;
  const { facts, workItems: items, heads, relations } = model;

  const namedOrigins = (input.origins?.length ?? 0) > 0;
  let origins: readonly SessionRef[] = input.origins ?? [];
  if (focus) origins = [focus];
  if (!origins.length) {
    const keys = [...new Set(facts.map(factSessionKey).filter(Boolean))];
    origins = keys.map((key) => ({
      harness: key.split(':')[0] ?? '',
      sid: key.slice(key.indexOf(':') + 1),
    }));
  }
  if (!origins.length) origins = [{ harness: '', sid: input.fallbackSession || 'focused' }];
  const originKeys = [
    ...new Set(origins.map((origin) => compatKey(origin) || origin.sid || 'focused')),
  ];
  const foKeys = originKeys.map((key) => `fo:${key}`);
  const foKey = foKeys[0] ?? 'fo:focused';

  const itemById = new Map(items.map((item) => [item.id, item]));
  const normalizedLabel = (item: WorkItem): string =>
    item.label
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-|-$/g, '');
  /* A workflow-unbound item that names the same label as exactly one bound workflow item is that item. */
  const canonicalByItem = new Map<string, string>();
  items
    .filter((item) => item.id.startsWith('workflow-unbound:'))
    .forEach((item) => {
      const matches = items.filter(
        (candidate) =>
          candidate.kind === 'workflow_item' &&
          !candidate.id.startsWith('workflow-unbound:') &&
          normalizedLabel(candidate) === normalizedLabel(item),
      );
      const [only] = matches;
      if (matches.length === 1 && only) canonicalByItem.set(item.id, only.id);
    });
  const canonicalItemId = (id: string): string => canonicalByItem.get(id) ?? id;
  const factById = new Map(facts.map((fact) => [fact.id, fact]));

  const headByItem = new Map<string, Head>();
  const headAt = (head: Head): number => factById.get(head.latestMeaningfulEvent)?.order || 0;
  heads.forEach((head) => {
    const id = canonicalItemId(head.workItemId);
    const prior = headByItem.get(id);
    if (!prior || headAt(head) > headAt(prior)) headByItem.set(id, head);
  });

  const projectedDirections = [...model.intents, ...model.steering];
  const intentFactById = new Map(
    projectedDirections.map((intent) => [intent.projectionId, intent.derivedFrom]),
  );
  const meaningful = meaningfulDirections(projectedDirections, factById);
  const meaningfulIds = new Set(meaningful.map((fact) => fact.id));
  const allDirectionFacts = [
    ...new Map(
      projectedDirections
        .map((intent) => [intent.derivedFrom, factById.get(intent.derivedFrom)] as const)
        .filter((entry): entry is readonly [string, Fact] => entry[1] !== undefined),
    ).values(),
  ].sort(newestFirst);
  const suppressedDirections = allDirectionFacts.filter((fact) => !meaningfulIds.has(fact.id));

  const contributorByTask = new Map<string, Delegation[]>();
  const unboundContributors: Delegation[] = [];
  delegations.forEach((row) => {
    const id = delegationWorkItem(model, row);
    if (!id) {
      unboundContributors.push(row);
      return;
    }
    contributorByTask.set(id, [...(contributorByTask.get(id) ?? []), row]);
  });

  const relevance = new Map<string, { priority: number; at: number }>();
  const addTask = (rawId: string, order: number | undefined, priority: number): void => {
    const id = canonicalItemId(rawId);
    const item = itemById.get(id);
    if (!id || !item || item.kind === 'session_result') return;
    const prior = relevance.get(id) ?? { priority: 0, at: 0 };
    relevance.set(id, {
      priority: Math.max(priority || 0, prior.priority),
      at: Math.max(order || 0, prior.at),
    });
  };
  contributorByTask.forEach((rows, id) =>
    addTask(id, Math.max(...rows.map((row) => row.at || 0)), 3),
  );
  /* Active filters these later. The complete registry keeps every source-backed head so All can restore an
     inactive or unresolved lane without inventing a key at filter time. */
  heads.forEach((head) =>
    addTask(head.workItemId, factById.get(head.latestMeaningfulEvent)?.order, 1),
  );
  const nodes =
    model.nodes ??
    heads
      .filter((head) => ['prepared', 'outcome', 'decision'].includes(head.status))
      .map(
        (head): ActivityNode => ({
          order: factById.get(head.latestMeaningfulEvent)?.order ?? Number.NaN,
          kind: '',
          workItemIds: [head.workItemId],
        }),
      );
  [...nodes, ...model.historyNodes].forEach((node) =>
    node.workItemIds.forEach((id) => addTask(id, node.order, node.kind === 'burst' ? 1 : 2)),
  );
  const taskIds = [...relevance]
    .sort((a, b) => b[1].priority - a[1].priority || b[1].at - a[1].at || a[0].localeCompare(b[0]))
    .map((entry) => entry[0]);

  const allFoEvents = facts
    .filter((fact) => {
      const item = itemById.get(fact.workItemId);
      if (['final_output', 'result'].includes(fact.type) && focus?.state === 'working')
        return false;
      return (
        item?.kind === 'session_result' ||
        (!fact.workItemId && fact.type === 'user_message') ||
        ['final_output', 'observer_snapshot', 'goal_shift'].includes(fact.type)
      );
    })
    .sort(
      (a, b) =>
        Number(a.type === 'observer_snapshot') - Number(b.type === 'observer_snapshot') ||
        newestFirst(a, b),
    );
  const episodeByFact = new Map<string, Episode>();
  model.episodes.forEach((episode) => {
    const factId = intentFactById.get(episode.intentId);
    if (factId) episodeByFact.set(factId, episode);
  });

  const foLanes: FoLane[] = originKeys.map((originKey) => {
    const matching = (fact: Fact): boolean =>
      factSessionKey(fact) === originKey || (!factSessionKey(fact) && originKeys.length === 1);
    const harness = originKey.split(':')[0] ?? '';
    return {
      kind: 'fo',
      key: `fo:${originKey}`,
      label: namedOrigins ? `${taskTitle(harness || 'First Officer')} FO` : 'First Officer',
      events: allFoEvents.filter(matching),
      directions: meaningful.filter(matching),
      episodeByFact,
      suppressedDirections: suppressedDirections.filter(matching),
    };
  });

  const supported = (relation: Relation): boolean => !relation.confidence.includes('derived');
  const topologyFor = (workItemId: string) => {
    const taskKey = `task:${workItemId}`;
    const branches = relations
      .filter(
        (relation) =>
          relation.type === 'dispatches_to' &&
          foKeys.includes(relation.from) &&
          relation.to === taskKey,
      )
      .filter(supported);
    const merges = relations
      .filter(
        (relation) =>
          relation.type === 'returns_to' &&
          relation.from === taskKey &&
          foKeys.includes(relation.to),
      )
      .filter(supported);
    const relationAt = (relation: Relation): number =>
      factById.get(relation.evidenceRef)?.order || 0;
    const latestDispatchAt = Math.max(0, ...branches.map(relationAt));
    const taskResults = facts.filter(
      (fact) =>
        canonicalItemId(fact.workItemId) === workItemId &&
        ['work_result', 'result'].includes(fact.type) &&
        fact.evidenceConfidence === 'exact',
    );
    const latestReturnAt = Math.max(
      0,
      ...merges.map(relationAt),
      ...taskResults.map((fact) => fact.order || 0),
    );
    const retryEvidence =
      relations.some(
        (relation) =>
          ['retries', 'retry_of', 'failed_attempt'].includes(relation.type) &&
          supported(relation) &&
          (relation.from === taskKey || relation.to === taskKey),
      ) ||
      facts.some(
        (fact) =>
          canonicalItemId(fact.workItemId) === workItemId &&
          ['retry', 'failed_attempt'].includes(fact.sourceKind) &&
          fact.evidenceConfidence === 'exact',
      );
    return { dispatchCount: branches.length, latestDispatchAt, latestReturnAt, retryEvidence };
  };

  const taskLanes: TaskLane[] = taskIds.map((workItemId) => {
    const taskEvents = facts
      .filter((fact) => canonicalItemId(fact.workItemId) === workItemId)
      .sort(newestFirst);
    const contributors = [...(contributorByTask.get(workItemId) ?? [])].sort((a, b) =>
      a.worker.localeCompare(b.worker),
    );
    const topology = topologyFor(workItemId);
    const head = headByItem.get(workItemId) ?? null;
    const item = itemById.get(workItemId) ?? { id: workItemId, label: '', kind: '', bindings: [] };
    const working =
      contributors.length > 0 ||
      taskEvents.some((fact) => fact.currentState && fact.evidenceConfidence === 'exact');
    const unreturned =
      topology.dispatchCount > 0 && topology.latestDispatchAt > topology.latestReturnAt;
    const returned = topology.latestReturnAt > 0 && !unreturned;
    return {
      kind: 'task',
      key: `task:${workItemId}`,
      label: item.label || 'Task',
      workItemId,
      item,
      events: taskEvents,
      contributors,
      head,
      headFact: head ? (factById.get(head.latestMeaningfulEvent) ?? null) : null,
      current: working || unreturned,
      working,
      unreturned,
      returned,
      dispatchCount: topology.dispatchCount,
      retryEvidence: topology.retryEvidence,
    };
  });

  const lanes: Lane[] = [...foLanes, ...taskLanes];
  return {
    foKey,
    foKeys,
    lanes,
    laneByKey: new Map(lanes.map((lane) => [lane.key, lane])),
    unboundContributors,
  };
}

/* ------------------------------------------------------------------------------------------------
   Events. */

export interface TimelineEvent {
  readonly eventId: string;
  readonly at: number | null;
  readonly kind: string;
  readonly meaning: string;
  readonly fact: Fact;
  readonly lane: Lane;
  readonly rationale: string;
  readonly relations: readonly Relation[];
  /** Direction messages the first row of a lane folds in as source-only text. */
  readonly suppressed: readonly Fact[];
  /** Whether a direction was paired with a reaction, and how sure the pairing is. Undefined off direction rows. */
  readonly causal?: 'derived' | 'solid' | 'none';
}

function laneFor(registry: Registry, fact: Fact): Lane {
  const sourceKey = fact.session
    ? `fo:${fact.session.harness}:${fact.session.sid}`
    : registry.foKey;
  const lane = registry.laneByKey.get(sourceKey) ?? registry.laneByKey.get(registry.foKey);
  if (!lane) throw new Error('The registry has no First Officer lane.');
  return lane;
}

/* Every meaningful event, newest first. Written out lane by lane exactly as the legacy builder did, because
   the order the sources are consulted in decides which of two events about one fact survives. */
function globalEvents(
  model: SemanticModel,
  registry: Registry,
  focus: RegistryInput['focus'],
): TimelineEvent[] {
  const events: TimelineEvent[] = [];
  const foLanes = registry.lanes.filter((lane): lane is FoLane => lane.kind === 'fo');

  foLanes.forEach((lane) =>
    lane.directions.forEach((fact, index) => {
      const episode = lane.episodeByFact.get(fact.id);
      events.push({
        eventId: fact.id,
        at: fact.at,
        kind: 'direction',
        meaning: fact.summary,
        fact,
        lane,
        rationale: directionRationale(fact.summary),
        relations: [],
        suppressed: index === 0 ? lane.suppressedDirections : [],
        causal: episode ? (episode.confidence.includes('derived') ? 'derived' : 'solid') : 'none',
      });
    }),
  );

  /* The current observer snapshot is already named beside the operator-owned focus. Only a source-backed
     change belongs in the event axis; repeating the same snapshot here makes one observation look like two. */
  foLanes.forEach((lane) => {
    const observed = lane.events.filter((fact) => fact.type === 'goal_shift').sort(newestFirst)[0];
    if (observed) {
      events.push({
        eventId: observed.id,
        at: observed.at,
        kind: 'observed_goal',
        meaning: observed.summary,
        fact: observed,
        lane,
        rationale: 'Changes understanding of the observed goal.',
        relations: [],
        suppressed: [],
      });
    }
    const final = lane.events.find((fact) => ['final_output', 'result'].includes(fact.type));
    if (final && (!focus || focus.state !== 'working')) {
      events.push({
        eventId: final.id,
        at: final.at,
        kind: 'result',
        meaning: final.summary,
        fact: final,
        lane,
        rationale: 'Changes understanding of an observed outcome.',
        relations: [],
        suppressed: [],
      });
    }
  });

  const linkedReactionIds = new Set(
    foLanes
      .flatMap((lane) => [...lane.episodeByFact.values()])
      .map((episode) => episode.adaptationFact),
  );
  model.facts
    .filter(
      (fact) =>
        linkedReactionIds.has(fact.id) &&
        ['result', 'decision', 'final_output'].includes(fact.type),
    )
    .forEach((fact) => {
      if (events.some((event) => event.eventId === fact.id)) return;
      events.push({
        eventId: fact.id,
        at: fact.at,
        kind: eventKind(fact) || 'result',
        meaning: fact.summary,
        fact,
        lane: laneFor(registry, fact),
        rationale: 'Changes understanding of a supported reaction or outcome.',
        relations: [],
        suppressed: [],
      });
    });

  registry.lanes
    .filter((lane): lane is TaskLane => lane.kind === 'task')
    .forEach((lane) => {
      lane.events.forEach((fact) => {
        const kind = eventKind(fact);
        if (!kind) return;
        const sourceFoKey = fact.session
          ? `fo:${fact.session.harness}:${fact.session.sid}`
          : registry.foKey;
        const branch =
          kind === 'dispatch'
            ? model.relations.filter(
                (r) =>
                  r.type === 'dispatches_to' &&
                  r.from === sourceFoKey &&
                  r.to === lane.key &&
                  r.evidenceRef === fact.id,
              )
            : [];
        const merge =
          kind === 'result'
            ? model.relations.filter(
                (r) =>
                  r.type === 'returns_to' &&
                  r.from === lane.key &&
                  r.to === sourceFoKey &&
                  r.evidenceRef === fact.id,
              )
            : [];
        const meaning =
          kind === 'progress' && fact.stage
            ? taskTitle(fact.stage)
            : kind === 'dispatch'
              ? fact.summary || 'Dispatched'
              : fact.summary || taskTitle(kind);
        const rationale =
          kind === 'dispatch'
            ? 'Changes understanding of assigned work.'
            : kind === 'progress'
              ? 'Changes understanding of work progress.'
              : kind === 'decision'
                ? 'Changes understanding of a recorded decision.'
                : 'Changes understanding of an observed outcome.';
        events.push({
          eventId: fact.id,
          at: fact.at,
          kind,
          meaning,
          fact,
          lane,
          rationale,
          relations: [...branch, ...merge],
          suppressed: [],
        });
      });
    });

  const seenDispatches = new Set<string>();
  return events
    .sort((a, b) => (b.fact.order || 0) - (a.fact.order || 0) || a.eventId.localeCompare(b.eventId))
    .filter((event) => {
      if (event.kind !== 'dispatch') return true;
      const key = `${event.lane.key}\n${event.meaning.toLowerCase().trim()}`;
      if (seenDispatches.has(key)) return false;
      seenDispatches.add(key);
      return true;
    });
}

/* Decisions belong by recorded fact identity, independent of author, task binding or steering links. */
export function decisionFacts(model: SemanticModel): Fact[] {
  return [
    ...new Map(
      model.facts
        .filter((fact) => eventKind(fact) === 'decision')
        .map((fact) => [fact.id || fact, fact] as const),
    ).values(),
  ];
}

function decisionEvents(
  model: SemanticModel,
  registry: Registry,
  focus: RegistryInput['focus'],
): TimelineEvent[] {
  const placed = new Map(globalEvents(model, registry, focus).map((event) => [event.fact, event]));
  return decisionFacts(model)
    .map((fact): TimelineEvent => {
      const found = placed.get(fact);
      if (found) return found;
      return {
        eventId: fact.id,
        at: fact.at,
        kind: 'decision',
        meaning: fact.summary,
        fact,
        lane: laneFor(registry, fact),
        rationale: 'Changes understanding of a recorded decision.',
        relations: [],
        suppressed: [],
      };
    })
    .sort(
      (a, b) => (b.fact.order || 0) - (a.fact.order || 0) || a.eventId.localeCompare(b.eventId),
    );
}

/* The lanes a mode keeps. First Officer lanes always stay, because a direction is not a task. All keeps
   every task, Active only those still current, and Decisions the ones that recorded a decision. */
export function visibleLaneKeys(registry: Registry, mode: GraphMode): ReadonlySet<string> {
  return new Set(
    registry.lanes
      .filter(
        (lane) =>
          lane.kind === 'fo' ||
          mode === 'all' ||
          lane.current ||
          (mode === 'decisions' && lane.events.some((fact) => eventKind(fact) === 'decision')),
      )
      .map((lane) => lane.key),
  );
}

export function eventsForMode(
  model: SemanticModel,
  registry: Registry,
  mode: GraphMode,
  focus: RegistryInput['focus'],
): TimelineEvent[] {
  if (mode === 'decisions') return decisionEvents(model, registry, focus);
  const visible = visibleLaneKeys(registry, mode);
  return globalEvents(model, registry, focus).filter((event) => visible.has(event.lane.key));
}

/* Said when a mode has nothing to show, from what the payload published about its own window. */
export function historyEmptyText(model: SemanticModel, mode: GraphMode | 'course'): string {
  if (model.history.reason) return model.history.reason;
  const subject =
    mode === 'course'
      ? 'source-backed course changes'
      : mode === 'decisions'
        ? 'decisions'
        : mode === 'active'
          ? 'semantic events for active work'
          : 'semantic events';
  const seconds = model.history.windowSec;
  if (seconds === null || seconds <= 0) {
    return `No ${subject} ${mode === 'course' ? 'observed' : 'available'}. The semantic history window was not published.`;
  }
  const count = seconds % 3600 === 0 ? seconds / 3600 : seconds % 60 === 0 ? seconds / 60 : seconds;
  const unit = seconds % 3600 === 0 ? 'hour' : seconds % 60 === 0 ? 'minute' : 'second';
  return `No ${subject} observed in the last ${String(count)} ${unit}${count === 1 ? '' : 's'}.`;
}

/* ------------------------------------------------------------------------------------------------
   What a row says. */

export function gateApplicationResult(fact: Fact): string {
  const stage = fact.stage || 'gate';
  const state = fact.applicationState.toLowerCase();
  if (['applied', 'consumed'].includes(state) && fact.targetStage)
    return `${stage} → ${fact.targetStage}`;
  if (['pending', 'unspent'].includes(state))
    return `${stage} · decision recorded · pending application`;
  if (state === 'superseded') return `${stage} · decision superseded`;
  if (!state) return `${stage} · decision recorded · application unknown`;
  return `${stage} · decision recorded · application ${state}`;
}

export function gateApplicationDisposition(fact: Fact): string {
  const state = fact.applicationState.toLowerCase();
  if (['applied', 'consumed'].includes(state)) return 'applied';
  if (['pending', 'unspent'].includes(state)) return 'pending application';
  if (state === 'superseded') return 'superseded';
  if (!state) return 'application unknown';
  return `application ${state}`;
}

export interface EventSentence {
  readonly actor: string;
  readonly action: string;
  readonly object: string;
  readonly result: string;
}

export function eventSentence(event: TimelineEvent): EventSentence {
  const { fact, lane } = event;
  const harness = taskTitle(fact.session?.harness || 'Session');
  const contributor = fact.contributorVerified
    ? (fact.contributorLabel ?? `${harness} worker`)
    : `${harness} worker`;
  const object = lane.kind === 'task' ? taskTitle(lane.label) : lane.label;
  let actor = `${harness} FO`;
  let action = event.kind;
  let result = event.meaning || 'observed';
  if (event.kind === 'direction') {
    actor = 'You';
    action = 'directed';
  } else if (event.kind === 'decision') {
    actor = fact.by === 'person:captain' ? 'You' : fact.by || 'Decision author';
    action =
      ({ approve: 'approved', revise: 'revised', hold: 'held' } as Record<string, string>)[
        fact.decision
      ] ??
      (fact.decision || 'decided');
    result = gateApplicationResult(fact);
  } else if (event.kind === 'dispatch') {
    const started = ['work_birth', 'task_started', 'child_assignment'].includes(fact.sourceKind);
    actor = started ? contributor : `${harness} FO`;
    action = started ? 'started' : 'dispatched';
    result =
      lane.kind === 'task' && lane.unreturned
        ? 'return not observed'
        : fact.stage || 'dispatch recorded';
  } else if (event.kind === 'result') {
    actor = contributor;
    action = 'returned';
  } else if (event.kind === 'progress') {
    actor = fact.session ? `${harness} worker` : 'Project state';
    action = 'advanced';
    result = fact.stage || event.meaning || 'progress recorded';
  }
  return { actor, action, object, result };
}

/* The scope an event belongs to, which is what tells a reader of a project timeline whose words these are. */
export type ScopeKind = 'project' | 'session' | 'unknown';

export interface Scope {
  readonly kind: ScopeKind;
  readonly owner: string;
}

export function factScope(fact: Fact): Scope {
  const project: Scope = { kind: 'project', owner: 'project' };
  if (fact.scope === 'project') return project;
  if (fact.type === 'gate_decision') {
    return fact.scope === 'session' && fact.session
      ? { kind: 'session', owner: `${fact.session.harness}:${fact.session.sid}` }
      : project;
  }
  if (fact.session)
    return { kind: 'session', owner: `${fact.session.harness}:${fact.session.sid}` };
  if (['prepared_dispatch', 'stage_transition'].includes(fact.type)) return project;
  return { kind: 'unknown', owner: 'unknown' };
}

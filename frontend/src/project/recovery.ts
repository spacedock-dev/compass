import { nativeSession } from '../observed/native';
import { ageSeconds } from '../observed/values';
import { formatDuration } from '../shell/format';
import { humanLabel, scopeLabel, sessKey, workingSessions, type ProjectGroup } from './group';
import { delegationLanes, type Lane } from './lanes';
import { field, fieldText, isRecord, list, PROJECT_STALLED_SEC, record, type Row } from './raw';

/* The recovery briefing: what a reader returning to a project needs to know first, and the text the More
   menu copies. Every sentence here is a claim about what the board observed, so each carries its source or
   its absence: an assignment is "Exact workflow state" or "Exact operator direction", never inferred, and a
   scan that did not finish says it did not. Ported from the legacy `next-cockpit.js` (the recovery block),
   function for function, and held to it by the differential test.

   Everything is a function of its arguments. The legacy page reads module globals for the payload, the
   route, the context cache and the memo store; here the caller hands them in. */

export interface ContextEntryLike {
  readonly data: Row | null;
  /** The legacy flag is `true`; the store's is the failure it recorded. Only its truthiness is read. */
  readonly error?: unknown;
  readonly revision?: number;
}

/** What the recovery functions read besides the group itself. */
export interface RecoveryEnv {
  readonly group: ProjectGroup;
  readonly workflow?: boolean;
  /** The payload's own clock, which every age here is measured against. */
  readonly generated: number | null;
  readonly harnesses: ReadonlyMap<string, string>;
  /** The project-scope context read (never the focused one), or undefined before one was asked. */
  readonly entry: ContextEntryLike | undefined;
}

const age = (env: RecoveryEnv, stamp: unknown): number | null => ageSeconds(env.generated, stamp);

/** The project context's data, or null: `entry && entry.data || null`. */
export function observationOf(entry: ContextEntryLike | undefined): Row | null {
  return entry?.data ?? null;
}

export function semanticOf(observation: Row | null): Row {
  const semantic = field(observation, 'semantic');
  return isRecord(semantic) && semantic ? semantic : {};
}

/* ------------------------------------------------------------------------------------------------
   Decisions. */

/* The legacy kind of a fact. Only `decision` is read here; the rest of the table belongs to the timeline.
   `includes` is handed the published value itself, so a type that is not a string matches nothing. */
function isDecision(fact: Row): boolean {
  return ['decision', 'gate_decision'].includes(fact['type'] as string);
}

/* Decisions belong by recorded fact identity, independent of author, task binding or steering links.
   Both the summary and the rows consume this collection. A fact with no id is its own identity. */
export function decisionFacts(model: unknown): Row[] {
  const facts =
    isRecord(model) && Array.isArray(model['facts']) ? (model['facts'] as unknown[]) : [];
  const byIdentity = new Map<unknown, Row>();
  for (const fact of facts) {
    if (!isRecord(fact) || !isDecision(fact)) continue;
    byIdentity.set(fact['fact_id'] || fact, fact);
  }
  return [...byIdentity.values()];
}

export interface DecisionCounts {
  pending: number;
  unknown: number;
  superseded: number;
  applied: number;
}

export function captainDecisionCounts(semantic: unknown): DecisionCounts {
  const counts = { pending: 0, unknown: 0, superseded: 0, applied: 0 };
  for (const fact of decisionFacts(semantic)) {
    const state = String(fact['application_state'] || 'unknown').toLowerCase();
    if (state === 'pending' || state === 'unspent') counts.pending += 1;
    else if (state === 'consumed' || state === 'applied') counts.applied += 1;
    else if (state === 'superseded') counts.superseded += 1;
    else counts.unknown += 1;
  }
  return counts;
}

/** "pending 2 · consumed/applied 1", or the sentence for none. */
export function recoveryDecisions(semantic: unknown, workflow = true): string {
  const counts = captainDecisionCounts(semantic);
  const total = counts.pending + counts.unknown + counts.superseded + counts.applied;
  if (!total) return workflow ? 'No captain decisions observed' : 'No decisions observed';
  const labels = {
    pending: 'pending',
    unknown: 'unknown',
    superseded: 'superseded',
    applied: 'consumed/applied',
  } as const;
  return (['pending', 'unknown', 'superseded', 'applied'] as const)
    .filter((key) => counts[key])
    .map((key) => `${labels[key]} ${String(counts[key])}`)
    .join(' · ');
}

/* ------------------------------------------------------------------------------------------------
   Attention coverage and source failures. */

export interface AttentionCoverage {
  readonly state: 'unavailable' | 'complete' | 'incomplete';
  readonly label: string;
  readonly source: string;
  readonly scanned: number | null;
  readonly total: number | null;
}

export function attentionCoverage(
  entry: ContextEntryLike | undefined,
  workflow = true,
): AttentionCoverage {
  const observation = observationOf(entry);
  if (!observation || entry?.error) {
    return {
      state: 'unavailable',
      label: workflow ? 'Captain attention unavailable' : 'Attention unavailable',
      source: entry?.error ? 'project context request failed' : 'project context pending',
      scanned: null,
      total: null,
    };
  }
  const semantic = semanticOf(observation);
  const raw = record(field(semantic['projections'], 'command_attention_coverage'));
  const state = String(raw['state'] || '');
  const scanned = Number(raw['scanned']);
  const total = Number(raw['total']);
  const omitted = Number(raw['omitted']);
  if (
    !['complete', 'incomplete'].includes(state) ||
    !Number.isFinite(scanned) ||
    !Number.isFinite(total) ||
    scanned < 0 ||
    total < scanned
  ) {
    return {
      state: 'unavailable',
      label: workflow ? 'Captain attention unavailable' : 'Attention unavailable',
      source: 'project context coverage unavailable',
      scanned: null,
      total: null,
    };
  }
  const count = `${String(scanned)} of ${String(total)} active ${total === 1 ? 'session' : 'sessions'}`;
  if (state === 'incomplete') {
    const missing = Number.isFinite(omitted) && omitted >= 0 ? omitted : total - scanned;
    return {
      state: 'incomplete',
      label: `Coverage incomplete · ${count} · ${String(missing)} omitted`,
      scanned,
      total,
      source: String(raw['source'] || 'active-session attention scan'),
    };
  }
  return {
    state: 'complete',
    label: `Coverage complete · ${count}`,
    scanned,
    total,
    source: String(raw['source'] || 'active-session attention scan'),
  };
}

export function sourceFailures(observation: Row | null): string[] {
  const failures: string[] = [];
  const sources = record(field(observation, 'sources'));
  for (const [name, channel] of Object.entries(sources)) {
    const unavailable = field(channel, 'unavailable');
    if (!channel || !Array.isArray(unavailable)) continue;
    for (const row of unavailable) {
      const reason = String(fieldText(row, 'reason') || 'source unavailable').trim();
      const failure = `${humanLabel(name)} · ${reason}`;
      if (reason && !failures.includes(failure)) failures.push(failure);
    }
  }
  return failures;
}

/* ------------------------------------------------------------------------------------------------
   Children. */

export interface Child {
  readonly worker: string;
  readonly lifecycle: 'active' | 'returned';
  readonly assignment: string;
  readonly assignmentSource: string;
  readonly sourceSession: string;
  readonly workItemId?: string;
  readonly result?: string;
  readonly handoffUnavailable?: boolean;
  readonly at?: number;
  readonly ageSec?: number | null;
  readonly age?: string | null;
}

export interface Children {
  readonly active: readonly Child[];
  readonly latestReturn: Child | null;
}

/** The project-scope context's child assignment snapshot, for a lane's fallbacks. */
export function childAssignments(entry: ContextEntryLike | undefined): unknown {
  return field(entry?.data ?? null, 'child_assignments');
}

export function projectLanes(env: RecoveryEnv, sessions: readonly Row[]): Lane[] {
  const snapshot = childAssignments(env.entry);
  return sessions.flatMap((session) => delegationLanes(session, snapshot));
}

export function recoveryChildren(env: RecoveryEnv): Children {
  const active: Child[] = projectLanes(env, workingSessions(env.group))
    .filter((lane) => lane.active !== false)
    .map((lane) => ({
      worker: lane.worker,
      lifecycle: 'active' as const,
      assignment: lane.assignment,
      assignmentSource: lane.source,
      sourceSession: lane.parentSession,
      workItemId: lane.workItemId,
    }));
  const returned: Child[] = env.group.sessions
    .flatMap((session) =>
      list(session['subagent_events'])
        .filter((event) => isRecord(event) && event['kind'] === 'subagent_complete')
        .map((raw) => {
          const event = raw as Row;
          const at = Number(event['at']) || 0;
          const ageSec = age(env, at);
          const assignment =
            typeof event['assignment'] === 'string' && event['assignment'].trim()
              ? event['assignment'].trim()
              : 'assignment unavailable';
          const found = [event['result'], event['result_summary']].find(
            (value) => typeof value === 'string' && value.trim(),
          );
          const result = (typeof found === 'string' ? found.trim() : '') || 'result unavailable';
          return {
            worker: String(event['name'] || 'Child'),
            lifecycle: 'returned' as const,
            assignment,
            assignmentSource: String(event['source'] || 'child lifecycle source unavailable'),
            result,
            handoffUnavailable:
              assignment === 'assignment unavailable' && result === 'result unavailable',
            sourceSession: sessKey(session),
            at,
            ageSec,
            age: formatDuration(ageSec),
          };
        }),
    )
    .sort((left, right) => (right.at ?? 0) - (left.at ?? 0));
  return { active, latestReturn: returned[0] ?? null };
}

/* ------------------------------------------------------------------------------------------------
   What the captain, or the first officer, has to look at. */

export interface AttentionItem {
  readonly owner: string;
  readonly label: string;
  readonly kind: string;
  readonly question?: string;
  readonly blockedStep?: string;
  /** As published, or the pair this page wrote: only `source` and `confidence` are read. */
  readonly evidence: unknown;
}

export function commandAttention(env: RecoveryEnv): AttentionItem[] {
  const attention: AttentionItem[] = [];
  const add = (owner: string, label: string, source: string, confidence = 'exact', kind = '') =>
    attention.push({ owner, label, kind, evidence: { source, confidence } });
  const observation = observationOf(env.entry);
  const semantic = semanticOf(observation);
  const projections = field(semantic, 'projections');
  const projected: unknown[] = Array.isArray(field(projections, 'command_attention'))
    ? (field(projections, 'command_attention') as unknown[])
    : [];
  for (const item of projected) {
    if (!isRecord(item) || !['CAPTAIN', 'FO'].includes(item['owner'] as string)) continue;
    const kind = String(item['kind'] || '');
    const question = String(item['question'] || '').trim();
    const blockedStep = String(item['blocked_step'] || '').trim();
    if (item['owner'] === 'CAPTAIN' && !question) {
      const recorded = kind.replaceAll('_', ' ').trim() || 'decision';
      attention.push({
        owner: 'FO',
        kind: 'decision_application',
        label: `apply recorded ${recorded}`,
        question: '',
        blockedStep,
        evidence: item['evidence'] || {},
      });
      continue;
    }
    const label = question || String(item['label'] || 'resolve system follow-up');
    attention.push({
      owner: item['owner'] as string,
      label,
      question,
      kind,
      blockedStep,
      evidence: item['evidence'] || {},
    });
  }
  const coverage = attentionCoverage(env.entry, env.workflow !== false);
  if (coverage.state === 'unavailable') {
    attention.push({
      owner: 'FO',
      kind: 'coverage_inspection',
      label: env.workflow === false ? 'refresh attention scan' : 'refresh captain-attention scan',
      question: '',
      evidence: { source: coverage.source, confidence: 'unavailable' },
    });
  } else if (coverage.state === 'incomplete') {
    attention.push({
      owner: 'FO',
      kind: 'coverage_inspection',
      label: env.workflow === false ? 'complete attention scan' : 'complete captain-attention scan',
      question: '',
      evidence: { source: coverage.source, confidence: 'bounded' },
    });
  }
  for (const session of env.group.observed.needs) {
    if (session.askKnown) {
      add('CAPTAIN', session.askText, 'AskRegistry exact question', 'exact', 'ask');
      continue;
    }
    const name =
      env.harnesses.get(String(session.harness || '')) || humanLabel(session.harness || 'session');
    add('FO', `inspect ${name} input request`, 'exact session needs-input state', 'unavailable');
  }

  const discovery = record(field(observation, 'workflow_discovery'));
  const projectedDiscovery = projected.some(
    (item) =>
      isRecord(item) &&
      item['owner'] === 'FO' &&
      /workflow discovery/i.test(String(item['question'] || item['label'] || '')),
  );
  if (discovery['state'] === 'error' && !projectedDiscovery) {
    const reason = String(discovery['reason'] || 'source error').trim();
    add(
      'FO',
      'refresh workflow discovery',
      `${String(discovery['source'] || 'project workflow discovery')} · ${reason}`,
    );
  } else if (discovery['state'] === 'unavailable' && !projectedDiscovery) {
    const reason = String(discovery['reason'] || 'source unavailable').trim();
    add(
      'FO',
      'refresh workflow discovery',
      `${String(discovery['source'] || 'project workflow discovery')} · ${reason}`,
    );
  }
  const failures = sourceFailures(observation);
  if (failures.length) {
    const observer = failures.some((reason) => /observer/i.test(reason));
    add(
      'FO',
      observer ? 'refresh observer' : 'inspect project context source',
      failures.join(' · '),
      'unavailable',
    );
  }

  const trails: unknown[] = Array.isArray(field(projections, 'trail_heads'))
    ? (field(projections, 'trail_heads') as unknown[])
    : [];
  const unreturned = trails.filter(
    (row) => isRecord(row) && ['prepared', 'requested'].includes(row['status'] as string),
  ) as Row[];
  if (unreturned.length) {
    const retried = unreturned.filter((row) => Number(row['dispatch_count'] || 0) > 1).length;
    add(
      'FO',
      `inspect assignment return · ${String(unreturned.length)}${retried ? ` · ${String(retried)} retried` : ''}`,
      'semantic task trail heads',
    );
  }

  const native = env.group.sessions.map(nativeSession);
  const idle = native.filter((session) => session['state'] === 'idle');
  const stale = native.filter((session) => {
    const seconds = age(env, session['last_activity']);
    return session['state'] !== 'idle' && seconds !== null && seconds >= PROJECT_STALLED_SEC;
  });
  if (idle.length || stale.length) {
    const parts: string[] = [];
    if (idle.length) parts.push(`inspect idle owner · ${String(idle.length)}`);
    if (stale.length) parts.push(`refresh stale owner · ${String(stale.length)}`);
    add('FO', parts.join(' · '), 'exact session state');
  }
  const children = recoveryChildren(env);
  for (const child of children.active) {
    if (child.assignment !== 'assignment unavailable') continue;
    add(
      'FO',
      `inspect ${child.worker} assignment`,
      child.assignmentSource,
      'unavailable',
      'child_evidence_gap',
    );
  }
  const returned = children.latestReturn;
  if (
    returned &&
    (returned.assignment === 'assignment unavailable' || returned.result === 'result unavailable')
  ) {
    if (returned.handoffUnavailable) {
      add(
        'FO',
        `recover ${returned.worker} handoff`,
        returned.assignmentSource,
        'unavailable',
        'child_evidence_gap',
      );
    } else if (/source unavailable/i.test(returned.assignmentSource)) {
      const gaps = [
        returned.assignment === 'assignment unavailable' ? 'assignment' : '',
        returned.result === 'result unavailable' ? 'result' : '',
      ].filter(Boolean);
      add(
        'FO',
        `inspect ${returned.worker} ${gaps.join('/')}`,
        returned.assignmentSource,
        'unavailable',
        'child_evidence_gap',
      );
    } else {
      add(
        'FO',
        `inspect ${returned.worker} handoff`,
        returned.assignmentSource,
        'unavailable',
        'child_evidence_gap',
      );
    }
  }
  const rank = (owner: string) => (owner === 'CAPTAIN' ? 0 : 1);
  const seen = new Set<string>();
  return attention
    .filter((item) => {
      const key = `${item.owner}\n${item.label}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    })
    .sort((left, right) => rank(left.owner) - rank(right.owner));
}

/** The verb the reader is asked to do, from the kind and the label. */
export function authorityVerb(
  item: Pick<AttentionItem, 'owner' | 'kind' | 'label'> | null,
): string {
  const kind = String(item?.kind || '').toLowerCase();
  if (item && item.owner === 'CAPTAIN') {
    if (/authori|approv/.test(kind)) return 'AUTHORIZE';
    if (/cho(?:ice|ose)|select/.test(kind)) return 'CHOOSE';
    if (/revis/.test(kind)) return 'REVISE';
    return 'ANSWER';
  }
  const label = String(item?.label || '').toLowerCase();
  if (kind === 'decision_application' || /^apply\b/.test(label)) return 'APPLY';
  if (/^refresh\b/.test(label)) return 'REFRESH';
  if (/^complete\b/.test(label)) return 'COMPLETE';
  if (/^link\b/.test(label)) return 'LINK';
  return 'INSPECT';
}

/* ------------------------------------------------------------------------------------------------
   Assignment, direction and result. */

export interface Task {
  readonly known: boolean;
  readonly id: string;
  readonly label: string;
  readonly stage: string;
}

/* The workflow task the project is on: the trail head whose status is `current stage`, joined to its
   work item by id. All three of the id, the item's label and the head's stage are needed; two of three is
   not "known". */
export function currentTask(observation: Row | null): Task {
  const semantic = semanticOf(observation);
  const items = new Map<string, Row>(
    list(semantic['work_items'])
      .filter(isRecord)
      .map((item) => [String(item['work_item_id'] || ''), item]),
  );
  const heads = Array.isArray(field(semantic['projections'], 'trail_heads'))
    ? (field(semantic['projections'], 'trail_heads') as unknown[])
    : [];
  const head = heads.find((row) => isRecord(row) && row['status'] === 'current stage');
  const id = String(fieldText(head, 'work_item_id')).trim();
  const item = id ? items.get(id) : undefined;
  const label = String(fieldText(item, 'label')).trim();
  const stage = String(fieldText(head, 'stage')).trim();
  if (!id || !label || !stage) return { known: false, id: '', label: 'Not observed', stage: '' };
  return { known: true, id, label: humanLabel(label), stage: humanLabel(stage) };
}

export function factSessionKey(fact: unknown): string {
  const source = record(field(fact, 'source_session'));
  const harness = String(source['harness'] || '');
  const sid = String(source['sid'] || '');
  return harness && sid ? `${harness}:${sid}` : '';
}

/** A message the server recognised as a correction the reader copied from Compass is Compass's words. */
export function readingCopied(entry: unknown): boolean {
  return String(fieldText(entry, 'type')) === 'user_message' && field(entry, 'copied') === true;
}

/* The latest exact, promoted operator direction that is not an acknowledgement, a bare link, a tooling
   remark or a request for a status report, preferring ones from sessions that are working now. */
export function substantiveDirection(env: RecoveryEnv, semantic: unknown): Row | null {
  const active = new Set(workingSessions(env.group).map((session) => sessKey(session)));
  const known = new Set(env.group.sessions.map((session) => sessKey(session)));
  const facts =
    isRecord(semantic) && Array.isArray(semantic['facts']) ? (semantic['facts'] as unknown[]) : [];
  const candidates = facts.filter((fact): fact is Row => {
    if (
      !isRecord(fact) ||
      fact['type'] !== 'user_message' ||
      fact['intent_promoted'] === false ||
      !fact['evidence'] ||
      field(fact['evidence'], 'confidence') !== 'exact' ||
      readingCopied(fact)
    )
      return false;
    const source = factSessionKey(fact);
    const summary = String(fact['summary'] || '').trim();
    if (!source || !known.has(source) || !summary) return false;
    if (/^(?:great|thanks|thank you|ok|okay|well|got it|acknowledged)[.!\s]*$/i.test(summary))
      return false;
    if (/^https?:\/\/\S+\/?$/i.test(summary)) return false;
    if (
      /\b(?:playwright(?:-chrome)?|built-?in browser|browser works|sandbox access|broader sandbox)\b/i.test(
        summary,
      )
    )
      return false;
    if (
      /^(?:please\s+)?(?:send|report|share|provide)\b.{0,40}\b(?:progress|status|update)\b/i.test(
        summary,
      )
    )
      return false;
    return true;
  });
  const pool = candidates.some((fact) => active.has(factSessionKey(fact)))
    ? candidates.filter((fact) => active.has(factSessionKey(fact)))
    : candidates;
  return (
    [...pool].sort((left, right) => Number(right['at'] || 0) - Number(left['at'] || 0))[0] ?? null
  );
}

function stageLinkEffect(
  env: RecoveryEnv,
  attention: readonly AttentionItem[],
  sourceSession: string,
): string {
  const blocked = attention.find(
    (item) =>
      item.owner === 'FO' &&
      item.kind === 'stage_link_required' &&
      item.blockedStep &&
      field(item.evidence, 'confidence') === 'exact',
  );
  if (blocked) return `Stage link required before ${String(blocked.blockedStep)}`;
  const canContinue = workingSessions(env.group).some(
    (session) => sessKey(session) === sourceSession,
  );
  return canContinue ? 'Stage link missing · current work can continue' : '';
}

export interface Assignment extends Task {
  readonly provenance: string;
  readonly qualifier: string;
  readonly sourceSession: string;
  readonly fact: Row | null;
}

export function recoveryAssignment(
  env: RecoveryEnv,
  semantic: unknown,
  observation: Row | null,
  attention: readonly AttentionItem[],
): Assignment {
  const current = currentTask(observation);
  if (current.known) {
    const facts =
      isRecord(semantic) && Array.isArray(semantic['facts'])
        ? (semantic['facts'] as unknown[])
        : [];
    const bound =
      facts
        .filter(
          (fact) =>
            isRecord(fact) &&
            String(fact['work_item_id'] || '') === current.id &&
            factSessionKey(fact),
        )
        .sort(
          (left, right) => Number(field(right, 'at') || 0) - Number(field(left, 'at') || 0),
        )[0] ?? null;
    return {
      ...current,
      provenance: 'Exact workflow state',
      qualifier: '',
      sourceSession: factSessionKey(bound),
      fact: null,
    };
  }
  const fact = substantiveDirection(env, semantic);
  if (!fact) return { ...current, provenance: '', qualifier: '', sourceSession: '', fact: null };
  const summary = String(fact['summary'] || '').trim();
  const sourceSession = factSessionKey(fact);
  return {
    known: true,
    id: '',
    label: (summary[0] ?? '').toUpperCase() + summary.slice(1),
    stage: '',
    provenance: 'Exact operator direction',
    qualifier: stageLinkEffect(env, attention, sourceSession),
    sourceSession,
    fact,
  };
}

export interface SessionResult {
  readonly summary: string;
  readonly display: string;
  readonly at: number;
  readonly source_session: { readonly harness: string; readonly sid: string };
  readonly evidence: { readonly source: string; readonly confidence: string };
}

export function latestSessionResult(
  group: Pick<ProjectGroup, 'sessions'>,
  sourceSession: string,
): SessionResult | null {
  const outputs = group.sessions
    .filter((session) => !sourceSession || sessKey(session) === sourceSession)
    .map((session) => {
      const summary =
        typeof session['last_output'] === 'string' ? session['last_output'].trim() : '';
      const firstLine =
        summary
          .split(/\r?\n/)
          .map((line) => line.trim())
          .find(Boolean) || '';
      const display = firstLine.length > 180 ? `${firstLine.slice(0, 177).trimEnd()}…` : firstLine;
      return {
        summary,
        display,
        at: Number(session['last_activity']) || 0,
        source_session: {
          harness: String(session['harness'] || ''),
          sid: String(session['sid'] || ''),
        },
        evidence: { source: 'attributable session output', confidence: 'uncertain' },
      };
    })
    .filter(
      (result) => result.summary && result.source_session.harness && result.source_session.sid,
    )
    .sort((left, right) => right.at - left.at);
  return outputs[0] ?? null;
}

export interface Latest {
  readonly direction: Row | null;
  readonly directionInAssignment: boolean;
  readonly result: Row | SessionResult | null;
  readonly resultKind: 'semantic' | 'session' | 'unavailable';
  readonly stale: boolean;
}

export function recoveryLatest(
  env: RecoveryEnv,
  semantic: unknown,
  stale: unknown,
  assignment: Assignment,
): Latest {
  const facts =
    isRecord(semantic) && Array.isArray(semantic['facts']) ? (semantic['facts'] as unknown[]) : [];
  const exact = (type: string): Row[] =>
    facts
      .filter(
        (fact): fact is Row =>
          isRecord(fact) &&
          fact['type'] === type &&
          !!fact['evidence'] &&
          field(fact['evidence'], 'confidence') === 'exact' &&
          !!String(fact['summary'] || '').trim(),
      )
      .sort((left, right) => Number(right['at'] || 0) - Number(left['at'] || 0));
  const direction = assignment.fact || substantiveDirection(env, semantic);
  const semanticResult =
    exact('result').find(
      (fact) =>
        (assignment.id && String(fact['work_item_id'] || '') === assignment.id) ||
        (assignment.sourceSession && factSessionKey(fact) === assignment.sourceSession),
    ) ?? null;
  const sessionResult =
    semanticResult || !assignment.sourceSession
      ? null
      : latestSessionResult(env.group, assignment.sourceSession);
  return {
    direction,
    directionInAssignment: !!assignment.fact,
    result: semanticResult || sessionResult,
    resultKind: semanticResult ? 'semantic' : sessionResult ? 'session' : 'unavailable',
    stale: !!stale,
  };
}

export function recoveryFactSource(fact: unknown): string {
  const source = record(field(fact, 'source_session'));
  const harness = String(source['harness'] || '');
  const sid = String(source['sid'] || '');
  return harness && sid ? `${harness}:${sid}` : 'unavailable';
}

/** The exact assignments the working sessions' lanes publish, from a source that says exact or structured. */
export function exactAssignments(env: RecoveryEnv): Lane[] {
  return projectLanes(env, workingSessions(env.group)).filter(
    (lane) =>
      lane.active !== false &&
      lane.assignment !== 'assignment unavailable' &&
      /(?:exact|structured)/i.test(String(lane.source || '')),
  );
}

export function recoveryActive(env: RecoveryEnv): string {
  const activeSessions = workingSessions(env.group);
  const assignments = exactAssignments(env);
  if (!activeSessions.length && !assignments.length) {
    return 'No active sessions or exact assignments observed';
  }
  return `${String(activeSessions.length)} active ${activeSessions.length === 1 ? 'session' : 'sessions'} · ${String(assignments.length)} exact ${assignments.length === 1 ? 'assignment' : 'assignments'}`;
}

/* ------------------------------------------------------------------------------------------------
   The briefing. */

export interface Briefing {
  readonly outcome: string;
  readonly currentFocus: string;
  readonly task: Assignment;
  readonly active: string;
  readonly children: Children;
  readonly latest: Latest;
  readonly decisions: string;
  readonly coverage: AttentionCoverage;
  readonly text: string;
}

export interface BriefingInput {
  readonly env: RecoveryEnv;
  /** The route's focused session, or null at project scope. */
  readonly focus: Row | null;
  readonly attention: readonly AttentionItem[];
  /** The two browser-local notes, empty when not set. */
  readonly outcome: string;
  readonly currentFocus: string;
}

export function recoveryBriefing(input: BriefingInput): Briefing {
  const { env, focus, attention } = input;
  const observation = observationOf(env.entry);
  const semantic = semanticOf(observation);
  const outcome = input.outcome || 'Not set';
  const currentFocus = input.currentFocus || 'Not set';
  const task = recoveryAssignment(env, semantic, observation, attention);
  const active = recoveryActive(env);
  const latest = recoveryLatest(env, semantic, env.entry?.error, task);
  const decisions = recoveryDecisions(semantic, env.workflow !== false);
  const coverage = attentionCoverage(env.entry, env.workflow !== false);
  const children = recoveryChildren(env);
  const captain = attention.filter(
    (item) =>
      item.owner === 'CAPTAIN' &&
      !['coverage_unavailable'].includes(String(item.kind || '')) &&
      item.label !== 'Captain-attention coverage incomplete',
  );
  const activeSessions = workingSessions(env.group);
  const assignments = exactAssignments(env);
  const returnedAge = children.latestReturn
    ? children.latestReturn.age
      ? `${children.latestReturn.age} ago${(children.latestReturn.ageSec ?? 0) >= PROJECT_STALLED_SEC ? ' · stale' : ''}`
      : 'age unavailable'
    : '';
  const lines = [
    'Compass recovery briefing',
    `Project: ${scopeLabel(env.group)}`,
    `Scope: ${focus ? `Session ${sessKey(focus)}` : 'Project'}`,
    ...(outcome !== 'Not set' ? [`Outcome (browser-local): ${outcome}`] : []),
    ...(currentFocus !== 'Not set' ? [`Focus (browser-local): ${currentFocus}`] : []),
    `Assignment: ${
      task.known
        ? [task.label, task.stage, task.provenance, task.qualifier].filter(Boolean).join(' · ')
        : 'Not observed'
    }`,
    `Active: ${active}`,
    `Active sessions: ${
      activeSessions.length
        ? activeSessions
            .map((session) => `${sessKey(session)} · ${String(session['state'])}`)
            .join('; ')
        : 'None observed'
    }`,
    `Active children: ${
      children.active.length
        ? children.active
            .map(
              (child) =>
                `${child.worker} · ${child.lifecycle} · ${child.assignment} · source session ${child.sourceSession}`,
            )
            .join('; ')
        : 'None observed'
    }`,
    `Latest returned child (bounded 1): ${
      children.latestReturn
        ? `${children.latestReturn.worker} · ${children.latestReturn.lifecycle} · ${children.latestReturn.assignment} · ${String(children.latestReturn.result)} · source session ${children.latestReturn.sourceSession} · ${returnedAge}`
        : 'None observed'
    }`,
    `Exact assignments: ${
      assignments.length ? assignments.map((lane) => lane.assignment).join('; ') : 'None observed'
    }`,
    ...(latest.direction
      ? [
          `${latest.stale ? 'Actionable direction (stale cached)' : 'Latest actionable direction'}: ${String(latest.direction['summary'])} · source session ${recoveryFactSource(latest.direction)}`,
        ]
      : []),
    ...(latest.resultKind === 'semantic'
      ? [
          `${latest.stale ? 'Exact result (stale cached)' : 'Latest exact result'}: ${String(field(latest.result, 'summary'))} · source session ${recoveryFactSource(latest.result)}`,
        ]
      : latest.resultKind === 'session'
        ? [
            `Latest session result: ${String(field(latest.result, 'summary'))} · source session ${recoveryFactSource(latest.result)} · uncertainty: session output; semantic result not published`,
          ]
        : []),
    `Decisions: ${decisions}`,
    `${env.workflow === false ? 'Your attention' : 'Captain attention'}: ${
      captain.length
        ? captain.map((item) => item.label).join('; ')
        : coverage.state === 'complete'
          ? 'None observed'
          : coverage.label
    }`,
    `Attention coverage: ${coverage.label} · source ${coverage.source}`,
  ];
  return {
    outcome,
    currentFocus,
    task,
    active,
    children,
    latest,
    decisions,
    coverage,
    text: lines.join('\n'),
  };
}

import { declaredRelations } from './relationships';
import { nativeSession } from './native';
import { nextNumber } from '../api/bootstrap';
import { boardLocationWarnings, rowLocationNote } from './location';
import {
  observeCapacity,
  type BoardRisk,
  type CapacitySublimit,
  type CapacityWindow,
} from './capacity';
import { delegatedWork } from './landing';
import { observeProject, sessionRisk, type ObservedProject } from './project';
import { labelOf, observeSession, sessionState, type ObservedSession } from './session';
import {
  asPayload,
  compare,
  exactAskOwner,
  identityPart,
  pair,
  payloadAskRows,
  payloadSessionRows,
  sessionKey,
  trimmed,
  workingOrder,
  isRecord,
  type Pair,
  type Row,
} from './values';

export interface ObservedCounter {
  readonly label: string;
  readonly value: number;
  readonly noteText: string;
  readonly noteKnown: true;
}

export interface CoverageRow {
  readonly key: string;
  readonly label: string;
  readonly sessions: number;
}

export type Coverage = {
  readonly observed: string;
  readonly quiet: string;
  readonly gates: string;
  readonly rows: readonly (CoverageRow & Pair<'block'> & Pair<'rate'>)[];
  readonly caveats: readonly string[];
};

export interface ObservedTotals {
  readonly sessions: number;
  readonly running: number;
  readonly needs: number;
  readonly ended: number;
  readonly quiet: number;
  readonly subagents: number;
  readonly reportsBlock: number;
  readonly exactRequests: number;
}

export type Observed = {
  readonly sessions: readonly ObservedSession[];
  readonly projects: readonly ObservedProject[];
  readonly activeProjects: readonly ObservedProject[];
  readonly restProjects: readonly ObservedProject[];
  readonly active: readonly ObservedSession[];
  readonly history: readonly ObservedSession[];
  readonly totals: ObservedTotals;
  readonly coverage: Coverage;
  readonly risks: readonly BoardRisk[];
  readonly boardRisks: readonly BoardRisk[];
  readonly counters: readonly ObservedCounter[];
  readonly windows: readonly CapacityWindow[];
  readonly sublimits: readonly CapacitySublimit[];
  /** What the board cannot see yet, by name and sentence: [key, title, sentence]. */
  readonly open: readonly (readonly [string, string, string])[];
} & Pair<'capacityEmpty'>;

/* The order of a project group in the active lane: gates (the server's order), then working sessions
   (a long turn first, then by sid), then idle ones by nearest activity and sid, then anything else. */
function laneOrder(
  sources: readonly Row[],
  sessions: readonly ObservedSession[],
): ObservedSession[] {
  const bySource = new Map<Row, ObservedSession | undefined>(
    sources.map((source, index) => [source, sessions[index]]),
  );
  const gates = sources.filter((source) => source['state'] === 'needs_input');
  const working = workingOrder(sources.filter((source) => source['state'] === 'working'));
  const idle = sources
    .filter((source) => source['state'] === 'idle')
    .sort(
      (a, b) =>
        (nextNumber(b['last_activity']) ?? 0) - (nextNumber(a['last_activity']) ?? 0) ||
        compare(identityPart(a['sid']), identityPart(b['sid'])),
    );
  const other = sources.filter(
    (source) => !['needs_input', 'working', 'idle'].includes(String(source['state'] || '')),
  );
  return [...gates, ...working, ...idle, ...other].map(
    (source) => bySource.get(source) as ObservedSession,
  );
}

const OPEN: Observed['open'] = [
  [
    'attention-accounting',
    'Attention accounting',
    'Delegation share is measured per project, not yet aggregated across the week.',
  ],
  [
    'unpushed-commits',
    'Ended with unpushed commits',
    'The board reports uncommitted work, not commits that never reached a remote.',
  ],
  [
    'never-read',
    'Finished and never read',
    'Nothing on the board publishes whether you have read a finished session. The dismissal store is server-side and does not reach the page.',
  ],
];

/* The one reader of a payload. The selectors and views count from these same rows. A missing or
   malformed payload is the empty model, and whether the
   collection was ABSENT is the caller's question, answered from the payload itself. */
export function observe(input: unknown): Observed {
  const payload = asPayload(input);
  const sources = payloadSessionRows(payload);
  const harnesses = payloadHarnessRows(payload);
  const byHarness = new Map<string, Row>(harnesses.map((row) => [identityPart(row['key']), row]));
  const groups = new Map<string, Row[]>();
  for (const source of sources) {
    const label = labelOf(source);
    const group = groups.get(label);
    if (group) group.push(source);
    else groups.set(label, [source]);
  }
  const asks = new Map<string, Row[]>();
  const unowned: Row[] = [];
  for (const ask of payload['ask'] === true ? payloadAskRows(payload) : []) {
    if (!trimmed(ask['question'])) continue;
    const owner = exactAskOwner(payload, ask);
    if (!owner) {
      unowned.push(ask);
      continue;
    }
    const key = sessionKey(owner);
    const held = asks.get(key);
    if (held) held.push(ask);
    else asks.set(key, [ask]);
  }
  const generated = nextNumber(payload['generated']);
  const sessions = sources.map((source) =>
    observeSession(
      source,
      asks.get(sessionKey(source)) ?? [],
      byHarness.get(identityPart(source['harness'])),
      generated,
      rowLocationNote(groups.get(labelOf(source)) ?? [], source),
      source['waiting_on_child'] ? declaredRelations(payload, source).waitingText : '',
    ),
  );
  const risks: BoardRisk[] = [];
  sessions.forEach((session, index) => {
    // A waiting session has one primary category; its risk evidence stays on the session.
    if (session.isNeeds || session.askKnown) return;
    const source = nativeSession(sources[index] as Row);
    const finished = (nextNumber(source['finished_at']) ?? 0) > 0;
    const attributed =
      !session.isEnded &&
      ((finished && (source['state'] === 'working' || source['active'] === true)) ||
        (!finished &&
          (typeof source['dirty'] === 'boolean' || Number.isInteger(source['changed']))));
    const outcomeKnown = session.outcomeKnown;
    if (outcomeKnown && source['dirty'] === true) {
      risks.push(
        sessionRisk(
          session,
          session.isEnded ? 'end-dirty' : 'stop-dirty',
          session.outcomeText,
          session.gitText,
        ),
      );
    } else if (attributed) {
      risks.push(
        sessionRisk(
          session,
          'attribution',
          'Conflicting completion evidence',
          'Published activity and completion or git evidence do not establish the same end',
        ),
      );
    } else if (session.stuckKnown) {
      risks.push(sessionRisk(session, 'loop', 'Stuck signal', session.stuckText));
    } else if (
      !session.isEnded &&
      source['state'] === 'working' &&
      isRecord(source['turn']) &&
      source['turn']['long'] === true
    ) {
      risks.push(sessionRisk(session, 'long-turn', 'Long working turn', session.turnText));
    } else {
      const delegated = delegatedWork(source, generated);
      if (delegated.risky)
        risks.push({
          ...sessionRisk(session, 'quiet-launch', 'Quiet delegated launch', delegated.text),
          delegatedSession: source,
        });
    }
  });
  const riskKeys = new Set(
    risks.map((risk) => sessionKey({ harness: risk.harness, sid: risk.sid })),
  );
  const projects = [...groups].map(([key, group]) => {
    const members = sessions.filter((session) => session.project === key);
    return observeProject(
      key,
      members,
      group,
      members.filter((session) => riskKeys.has(sessionKey(session))),
    );
  });
  const rank = (project: ObservedProject) =>
    project.needs.length ? 0 : project.risky.length ? 1 : project.working.length ? 2 : 3;
  projects.sort((a, b) => rank(a) - rank(b) || compare(a.key, b.key));
  const capacity = observeCapacity(payload);
  const boardRisks: BoardRisk[] = [...capacity.risks];
  for (const { label, warning } of boardLocationWarnings(sources)) {
    boardRisks.push({
      scope: 'board',
      kind: warning.kind,
      title: warning.title,
      identity: `${label || 'Across display labels ·'} ${warning.kind === 'checkout' ? 'checkout' : 'display label'}`,
      src: 'Published project location evidence',
      nowText: warning.text,
      nowKnown: true,
      nextText: 'Compare title, worktree, id and start time below',
      nextKnown: true,
      tone: 'unknown',
    });
  }
  for (const ask of unowned) {
    boardRisks.push({
      scope: 'board',
      kind: 'ask',
      waitAge: nextNumber(ask['age_sec']),
      title: 'Exact request without an identified session',
      identity: trimmed(ask['id']) || 'Request identity not published',
      src: trimmed(ask['harness']) || 'Harness not published',
      nowText: String(ask['question']),
      nowKnown: true,
      nextText: 'Exact session ownership not established',
      nextKnown: false,
      tone: 'want',
    });
  }
  const totals: ObservedTotals = {
    sessions: sessions.length,
    running: sessions.filter((session) => session.isLive).length,
    needs: sessions.filter((session) => session.isNeeds).length,
    ended: sessions.filter((session) => session.isEnded).length,
    quiet: sessions.filter((session) => sessionState(session) === 'Quiet').length,
    subagents: sessions.reduce((sum, session) => sum + session.subagents.length, 0),
    reportsBlock: sessions.filter((session) => session.blockKnown).length,
    exactRequests: sessions.filter((session) => session.askKnown).length,
  };
  const ordered = laneOrder(sources, sessions);
  const active = ordered.filter((session) => session.isActive);
  const history = ordered.filter((session) => !session.isActive);
  const needs = sessions.filter((session) => session.isNeeds || session.askKnown);
  const needKeys = new Set(needs.map(sessionKey));
  const atRisk = sessions.filter(
    (session) => riskKeys.has(sessionKey(session)) && !needKeys.has(sessionKey(session)),
  );
  const close = sessions.filter(
    (session, index) =>
      !needKeys.has(sessionKey(session)) &&
      !riskKeys.has(sessionKey(session)) &&
      (session.isEnded ||
        (nativeSession(sources[index] as Row)['state'] === 'idle' &&
          (nextNumber((sources[index] as Row)['finished_at']) ?? 0) > 0)),
  );
  const subjectKeys = new Set([...needs, ...atRisk, ...close].map(sessionKey));
  const other = sessions.filter((session) => !subjectKeys.has(sessionKey(session)));
  const partial = other.filter((session) => {
    const source = sources[sessions.indexOf(session)] as Row;
    return Array.isArray(source['source_gaps']) && source['source_gaps'].length > 0;
  }).length;
  const otherStates = other.map(sessionState);
  const otherWords: [string, number][] = [
    ['moving', otherStates.filter((state) => state === 'Working').length],
    ['quiet', otherStates.filter((state) => state === 'Quiet').length],
    ['ended', otherStates.filter((state) => state === 'Ended').length],
  ];
  const counted = otherWords.reduce((sum, word) => sum + word[1], 0);
  if (counted < other.length) otherWords.push(['in no counted state', other.length - counted]);
  const sessionsWord = (count: number, one: string, many: string) => (count === 1 ? one : many);
  const coverage: Coverage = {
    observed:
      `${String(sessions.length - other.length)} of ${String(totals.sessions)} ${sessionsWord(totals.sessions, 'session carries', 'sessions carry')} a subject: ` +
      `${String(needs.length)} waiting on you · ${String(atRisk.length)} at risk · ${String(close.length)} to close the loop.`,
    quiet: `The other ${String(other.length)}: ${
      otherWords
        .filter((word) => word[1])
        .map((word) => `${String(word[1])} ${word[0]}`)
        .join(' · ') || 'none'
    }; of these, ${String(partial)} partially read.`,
    gates:
      `${String(totals.reportsBlock)} of ${String(totals.sessions)} ${sessionsWord(totals.sessions, 'session reports', 'sessions report')} block state · ` +
      `${String(totals.sessions - totals.reportsBlock)} unknown · ${payload['ends_observable'] === false ? 'ends unobservable' : `ends observed on ${String(totals.ended)} ${sessionsWord(totals.ended, 'session', 'sessions')}`}`,
    rows: harnesses.map((row) => ({
      key: identityPart(row['key']),
      label: trimmed(row['label']) || String(row['key'] || 'Harness not published'),
      sessions: sessions.filter((session) => session.harness === row['key']).length,
      ...pair(
        'block',
        !row['error'] && row['reports_needs_input'] === true
          ? 'needs-input reporting' +
              (trimmed(row['reports_needs_input_when'])
                ? `, ${String(row['reports_needs_input_when'])}`
                : '')
          : '',
        row['error'] ? 'Harness source could not be read' : 'Harness does not report blocks',
      ),
      ...pair(
        'rate',
        !row['error'] && row['reports_rate'] === true ? 'token-rate reporting' : '',
        'Token rate not reported',
      ),
    })),
    caveats: [
      'Termination cause not reported.',
      ...new Set(
        Object.keys(sessions[0] ?? {})
          .filter(
            (key) =>
              key.endsWith('Text') &&
              sessions.every(
                (session) =>
                  (session as unknown as Record<string, unknown>)[key.slice(0, -4) + 'Known'] ===
                  false,
              ),
          )
          .flatMap((key) =>
            sessions.map(
              (session) => (session as unknown as Record<string, unknown>)[key] as string,
            ),
          ),
      ),
    ],
  };
  const counter = (label: string, value: number, noteText: string): ObservedCounter => ({
    label,
    value,
    noteText,
    noteKnown: true,
  });
  return {
    sessions,
    projects,
    activeProjects: projects.filter((project) => project.needs.length || project.working.length),
    restProjects: projects.filter((project) => !project.needs.length && !project.working.length),
    active,
    history,
    totals,
    coverage,
    risks,
    boardRisks,
    counters: [
      counter(
        'EXACT REQUESTS',
        totals.exactRequests,
        `${String(totals.exactRequests)} of ${String(totals.sessions)} ${sessionsWord(totals.sessions, 'session carries', 'sessions carry')} an exact request`,
      ),
      counter(
        'REPORTED BLOCKS',
        totals.reportsBlock,
        `${String(totals.reportsBlock)} of ${String(totals.sessions)} ${sessionsWord(totals.sessions, 'session reports', 'sessions report')} block state`,
      ),
    ],
    windows: capacity.windows,
    sublimits: capacity.sublimits,
    ...pair('capacityEmpty', '', 'No plan usage has been reported yet.'),
    open: OPEN,
  };
}

function payloadHarnessRows(payload: Row): Row[] {
  return Array.isArray(payload['harnesses']) ? payload['harnesses'].filter(isRecord) : [];
}

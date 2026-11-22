import { sessionState, sessionStateLimit } from '../observed/session';
import { ageSeconds, endedAt, sessionKey } from '../observed/values';
import { formatDuration } from '../shell/format';
import { humanLabel, scopeLabel, sessKey, type ProjectGroup } from './group';
import { fieldText, isRecord, text, type Row } from './raw';

/* The scope tree and the scope switcher: the project as a whole and each of its sessions, as links that
   change what the page is about. The project root and one exact focused session are different scopes and
   draw different cues, on the desktop rail and in the compact disclosure alike. Ported from
   `nextCockpitScopeLinks` and the scope helpers around it. */

export type ScopeKind = 'project' | 'session' | 'unknown';

export interface Scope {
  readonly kind: ScopeKind;
  readonly owner: string;
  /** For a session, the harness's own label: the part that tells two sessions apart at a glance. */
  readonly detail?: string;
}

export const PROJECT_SCOPE: Scope = { kind: 'project', owner: 'project' };
export const UNKNOWN_SCOPE: Scope = { kind: 'unknown', owner: 'unknown' };

/** The scope one session is. A session with no harness or no sid is a scope nobody can name. */
export function sessionScope(
  session: Row | null | undefined,
  harnesses: ReadonlyMap<string, string>,
): Scope {
  // `session.source_session || session`: a published `source_session` that is not a record names no one.
  const source = session?.['source_session'] || session || {};
  const harness = fieldText(source, 'harness');
  const sid = fieldText(source, 'sid');
  if (!harness || !sid) return UNKNOWN_SCOPE;
  return {
    kind: 'session',
    owner: `${harness}:${sid}`,
    detail: harnesses.get(harness) || humanLabel(harness),
  };
}

/* Whose words a recorded fact is: the project's, one session's, or not known. */
export function factScope(fact: unknown, harnesses: ReadonlyMap<string, string>): Scope {
  if (!isRecord(fact)) return UNKNOWN_SCOPE;
  const declared = String(fact['scope'] || '').toLowerCase();
  if (declared === 'project') return PROJECT_SCOPE;
  if (fact['type'] === 'gate_decision') {
    return declared === 'session'
      ? sessionScope(fact['source_session'] as Row, harnesses)
      : PROJECT_SCOPE;
  }
  const session = sessionScope(fact['source_session'] as Row, harnesses);
  if (session.kind === 'session') return session;
  if (['prepared_dispatch', 'stage_transition'].includes(String(fact['type'] || '')))
    return PROJECT_SCOPE;
  return UNKNOWN_SCOPE;
}

/** The scope a set of facts is when read together: one session's only if every fact is, else the project's. */
export function factSetScope(
  facts: readonly unknown[],
  harnesses: ReadonlyMap<string, string>,
): Scope {
  const scopes = facts.map((fact) => factScope(fact, harnesses));
  if (!scopes.length || scopes.some((scope) => scope.kind === 'unknown')) return UNKNOWN_SCOPE;
  const sessions = new Map(
    scopes.filter((scope) => scope.kind === 'session').map((scope) => [scope.owner, scope]),
  );
  if (sessions.size === 1 && scopes.every((scope) => scope.kind === 'session')) {
    return [...sessions.values()][0] as Scope;
  }
  return PROJECT_SCOPE;
}

/* Whether the session is working: the collector says so and no end was observed, or the project's
   observed model counts it. */
export function sessionIsWorking(session: Row, group: ProjectGroup): boolean {
  if (session['state'] === 'working' && endedAt(session) === null) return true;
  const keys = new Set(group.observed.working.map((row) => sessionKey(row as unknown as Row)));
  return keys.has(sessionKey(session));
}

export function sessionTone(session: Row, group: ProjectGroup): string {
  const found = group.observed.sessions.find(
    (row) => sessionKey(row as unknown as Row) === sessionKey(session),
  );
  if (found?.tone) return found.tone;
  if (session['tone']) return String(session['tone']);
  if (isRecord(session['turn']) && session['turn']['long']) return 'want';
  return 'ok';
}

function sessionRank(session: Row, group: ProjectGroup): number {
  if (sessionIsWorking(session, group)) return 0;
  if (session['state'] === 'needs_input') return 1;
  if (session['state'] === 'idle') return 2;
  return 3;
}

function harnessName(session: Row, harnesses: ReadonlyMap<string, string>): string {
  return harnesses.get(text(session['harness'])) || text(session['harness']) || 'Session';
}

/** The harness name when every row of the group carries the same one, so the rail says it once. */
export function hoistedHarness(
  group: Pick<ProjectGroup, 'sessions'>,
  harnesses: ReadonlyMap<string, string>,
): string {
  const labels = new Set(group.sessions.map((session) => harnessName(session, harnesses)));
  const [only] = labels;
  return group.sessions.length && labels.size === 1 && only !== undefined ? only : '';
}

export interface ScopeLink {
  /** `project`, or the session's compatibility key: what the route's focus carries. */
  readonly key: string;
  readonly scope: Scope;
  /** The value, whitespace folded and untruncated: the stylesheet clips it, so cutting here would take the tail it is drawing. */
  readonly title: string;
  /** The title is the sentence for "no title published", which is not the session's own words. */
  readonly withheld: boolean;
  readonly isWorking: boolean;
  readonly isLive: boolean;
  readonly limit: string;
  /** The part under the title: for a session, harness, state, age and a sid where two rows look the same. */
  readonly meta: {
    readonly harness: string;
    readonly state: string;
    readonly label: string;
    readonly tone: string;
    readonly age: string;
    readonly sid: string;
  } | null;
  /** For the project row, the sentence under its name. */
  readonly count: string;
}

export const TITLE_WITHHELD = 'Session title not published';

/* The rows, in the order the rail draws them: working first, then waiting, then idle, then the rest, each
   by harness and then key. A row's sid is shown only where two rows would otherwise read the same, because
   a key beside a name that is already unique is noise on every other board. */
export function scopeLinks(
  group: ProjectGroup,
  harnesses: ReadonlyMap<string, string>,
  generated: number | null,
): ScopeLink[] {
  const rows = [...group.sessions].sort(
    (left, right) =>
      sessionRank(left, group) - sessionRank(right, group) ||
      text(left['harness']).localeCompare(text(right['harness'])) ||
      sessKey(left).localeCompare(sessKey(right)),
  );
  const face = (session: Row) =>
    [text(session['harness']), text(session['state']), text(session['title']).trim()].join(
      '\u0000',
    );
  const faces = rows.map(face);
  const hoisted = hoistedHarness(group, harnesses);
  const project: ScopeLink = {
    key: 'project',
    scope: PROJECT_SCOPE,
    title: scopeLabel(group).replace(/\s+/g, ' ').trim(),
    withheld: scopeLabel(group).replace(/\s+/g, ' ').trim() === TITLE_WITHHELD,
    isWorking: false,
    isLive: false,
    limit: '',
    meta: null,
    count: `${String(rows.length)} ${rows.length === 1 ? 'session' : 'sessions'}`,
  };
  const observedByKey = new Map(group.observed.sessions.map((row) => [sessionKey(row), row]));
  return [
    project,
    ...rows.map((session, index): ScopeLink => {
      const twin = faces.some((other, at) => at !== index && other === faces[index]);
      const raw = text(session['title']).trim() || TITLE_WITHHELD;
      const title = raw.replace(/\s+/g, ' ').trim();
      const state = String(session['state'] || 'unknown');
      const observed = observedByKey.get(sessionKey(session));
      const word = observed ? sessionState(observed) : 'State not published';
      const limit = observed ? sessionStateLimit(observed, word) : 'State not published';
      const since = ageSeconds(generated, session['last_activity']);
      return {
        key: sessKey(session),
        scope: sessionScope(session, harnesses),
        title,
        withheld: title === TITLE_WITHHELD,
        isWorking: word === 'Working',
        isLive: word === 'Working' && observed?.isLive === true,
        limit,
        meta: {
          harness: hoisted ? '' : harnessName(session, harnesses),
          state,
          label: word === 'State not published' || word === 'Waiting on child' ? '' : word,
          tone: sessionTone(session, group),
          age: since === null ? '' : (formatDuration(since) ?? ''),
          sid: twin ? text(session['sid']) : '',
        },
        count: '',
      };
    }),
  ];
}

/** The focused session's name and state share the scope links' evidence. */
export function viewingSession(
  focus: Row,
  group: ProjectGroup,
  harnesses: ReadonlyMap<string, string>,
) {
  const scope = sessionScope(focus, harnesses);
  const observed = group.observed.sessions.find((row) => sessionKey(row) === sessionKey(focus));
  const state = observed ? sessionState(observed) : 'State not published';
  return {
    label: `Viewing session · ${scope.detail || 'Session'}`,
    state: state === 'Waiting on child' || state === 'State not published' ? '' : state,
    limit: observed ? sessionStateLimit(observed, state) : 'State not published',
  };
}

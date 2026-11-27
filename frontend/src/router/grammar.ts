/* The released fragment grammar, ported from `next-boot.js` and held to it by a differential test
   (`grammar.test.ts` runs the legacy file as the oracle). The legacy source wins over any prose
   description, because the legacy page stays the rollback and a link written by one must open in
   the other.

   A route is `#n=<token>[&from=<origin>]`. The token is colon-separated, and every part is
   `encodeURIComponent`-escaped, which is what lets a project, harness or sid contain a colon
   and keeps `&` out of every part. */

/* `settings` arrived after the legacy page was retired, so the grammar's oracle has no answer for it. The
   legacy page read it as an unknown view and landed on Sessions, which is still what an old build does. */
export const TOP_LEVEL_VIEWS = [
  'attention',
  'projects',
  'sessions',
  'intent',
  'plan',
  'settings',
  'help',
] as const;
export type TopLevelView = (typeof TOP_LEVEL_VIEWS)[number];

/* Where a reader opened a session from, carried as a trailing `&from=` so the tab, the crumb and
   Escape agree after a reload. Closed, so a fragment cannot name anything else. */
export const SESSION_ORIGINS = [
  'sessions',
  'attention',
  'intent',
  'projects',
  'project',
  'help',
] as const;
export type SessionOrigin = (typeof SESSION_ORIGINS)[number];

export const PROJECT_TABS = ['now', 'course', 'decisions', 'console'] as const;
export type ProjectTab = (typeof PROJECT_TABS)[number];

/* A retired slug owes an alias, not a fall-through: without one a bookmarked `:held-to` link
   parses as a session focus id and lands on a filter that matches nothing. */
export const RETIRED_SESSION_TAB = 'held-to';

export interface TopLevelRoute {
  readonly view: TopLevelView;
  readonly project: null;
  readonly session: null;
}

export interface ProjectRoute {
  readonly view: 'project';
  readonly project: string;
  readonly session: null;
  /** The compatibility session key (`harness:sid`) a project view is narrowed to. */
  readonly focus?: string;
  readonly tab?: ProjectTab;
}

export interface SessionRoute {
  readonly view: 'session';
  readonly project: string;
  /** Absent on the released id-only form, which must never silently match an ambiguous owner. */
  readonly harness?: string;
  readonly session: string;
  readonly from?: SessionOrigin;
  readonly explain?: 'goal';
}

export type Route = TopLevelRoute | ProjectRoute | SessionRoute;

/* What `fragmentForRoute` accepts: the loose shape a caller builds, including the retired tab and
   values outside the closed sets, which print as the legacy printer prints them. */
export interface RouteInput {
  readonly view?: string;
  readonly project?: string | null;
  readonly harness?: string | null;
  readonly session?: string | null;
  readonly focus?: string | null;
  readonly tab?: string | null;
  readonly from?: string | null;
  readonly explain?: 'goal';
}

const LANDING: TopLevelRoute = { view: 'sessions', project: null, session: null };

function isTopLevel(value: unknown): value is TopLevelView {
  return (TOP_LEVEL_VIEWS as readonly unknown[]).includes(value);
}

function isOrigin(value: unknown): value is SessionOrigin {
  return (SESSION_ORIGINS as readonly unknown[]).includes(value);
}

function isTab(value: unknown): value is ProjectTab {
  return (PROJECT_TABS as readonly unknown[]).includes(value);
}

/* Which cockpit tabs exist, given the focus. One reader, so a keyboard wrap cannot reach past
   the list the nav drew. Both scopes answer the same today, and the focus argument is kept so a
   session-only tab can return without a second place to read the list. */
export function cockpitTabs(focus?: string | null): readonly ProjectTab[] {
  void focus;
  return PROJECT_TABS;
}

/* Null for malformed encoding. An empty project is valid and must not be confused with it. */
function decode(value: string): string | null {
  try {
    return decodeURIComponent(value);
  } catch {
    return null;
  }
}

/* Old project focus bookmarks encode harness and id as one part. Only the first colon
   separates them. A leading colon belongs to an id-only bookmark. */
function projectFocusSession(project: string, focus: string): SessionRoute | null {
  const at = focus.indexOf(':');
  if (at <= 0) return focus ? { view: 'session', project, session: focus, from: 'project' } : null;
  const session = focus.slice(at + 1);
  return session
    ? { view: 'session', project, harness: focus.slice(0, at), session, from: 'project' }
    : null;
}

function sessionRouteFromToken(token: string): SessionRoute | null {
  const parts = token.split(':');
  /* The part count, not the label, tells the two session forms apart, because
     `encodeURIComponent` escapes every colon inside a part. A session may carry an empty project:
     a harness that publishes no label groups it under "", and requiring one here would leave that
     session with no page and no link that could open it. */
  if (parts.length === 4 && parts[0] === 'session') {
    const project = decode(parts[1] ?? '');
    const harness = decode(parts[2] ?? '');
    const session = decode(parts[3] ?? '');
    if (project !== null && harness && session)
      return { view: 'session', project, harness, session };
  }
  if (parts.length === 3 && parts[0] === 'session') {
    const project = decode(parts[1] ?? '');
    const session = decode(parts[2] ?? '');
    if (project !== null && session) return { view: 'session', project, session };
  }
  return null;
}

function pathRouteFromToken(token: string): Route {
  if (isTopLevel(token)) return { view: token, project: null, session: null };
  const parts = token.split(':');
  if (parts.length === 2 && parts[0] === 'project') {
    const project = decode(parts[1] ?? '');
    if (project) return { view: 'project', project, session: null };
  }
  if (parts.length === 3 && parts[0] === 'project') {
    const project = decode(parts[1] ?? '');
    const value = decode(parts[2] ?? '');
    if (project && isTab(value)) return { view: 'project', project, session: null, tab: value };
    if (project && value) return projectFocusSession(project, value) ?? LANDING;
  }
  if (parts.length === 4 && parts[0] === 'project') {
    const project = decode(parts[1] ?? '');
    const focus = decode(parts[2] ?? '');
    const tab = decode(parts[3] ?? '');
    if (project && focus && (tab === RETIRED_SESSION_TAB || isTab(tab)))
      return projectFocusSession(project, focus) ?? LANDING;
  }
  /* Sessions is the landing view, so the bare URL and every fragment that parses as nothing land
     there. */
  return LANDING;
}

export function parseFragment(fragment: string | null | undefined): Route {
  const text = String(fragment ?? '');
  const whole = text.startsWith('#n=') ? text.slice(3) : '';
  const amp = whole.indexOf('&');
  const token = amp < 0 ? whole : whole.slice(0, amp);
  const query = amp < 0 ? '' : whole.slice(amp + 1);
  const session = sessionRouteFromToken(token);
  if (session) {
    const options = new URLSearchParams(query);
    const from = options.get('from');
    if (!isOrigin(from)) return session;
    if (from === 'help' && options.get('explain') === 'goal')
      return { ...session, from, explain: 'goal' };
    return { ...session, from };
  }
  return pathRouteFromToken(token);
}

export function fragmentForRoute(route: RouteInput | null | undefined): string {
  if (route && route.view === 'session' && route.project != null && route.session) {
    const harness = String(route.harness ?? '');
    const prefix = `#n=session:${encodeURIComponent(route.project)}:`;
    const from = isOrigin(route.from) ? `&from=${route.from}` : '';
    const body = harness
      ? `${prefix}${encodeURIComponent(harness)}:${encodeURIComponent(route.session)}`
      : `${prefix}${encodeURIComponent(route.session)}`;
    const explain = route.from === 'help' && route.explain === 'goal' ? '&explain=goal' : '';
    return body + from + explain;
  }
  if (route && route.view === 'project' && route.project) {
    if (route.focus) {
      const session = projectFocusSession(route.project, route.focus);
      return session ? fragmentForRoute(session) : '#n=sessions';
    }
    const tab = isTab(route.tab) && route.tab !== 'now' ? `:${route.tab}` : '';
    return `#n=project:${encodeURIComponent(route.project)}${tab}`;
  }
  if (route && isTopLevel(route.view)) return `#n=${route.view}`;
  return '#n=sessions';
}

/** What a bare, malformed or retired fragment is rewritten to. */
export function canonicalFragment(fragment: string | null | undefined): string {
  return fragmentForRoute(parseFragment(fragment));
}

/* Where a session opened from here came from: a session passes its own on, a top-level or project
   view names itself, and anything else names nothing, which reads as Sessions. */
export function routeOrigin(route: RouteInput | null | undefined): SessionOrigin | null {
  if (!route) return null;
  if (route.view === 'session') return isOrigin(route.from) ? route.from : null;
  return isOrigin(route.view) ? route.view : null;
}

/* The view a session page sits under, by where the reader came from: its tab, the root of its
   crumb and the place Escape returns to are all this one. */
export function sessionHome(route: RouteInput | null | undefined): TopLevelView {
  const from = route?.from;
  if (from === 'project' || from === 'projects') return 'projects';
  return from === 'attention' || from === 'intent' || from === 'help' ? from : 'sessions';
}

/* A new page opens at its top; a tab or scope change within one does not move the reader. */
export function routeIdentity(route: RouteInput | null | undefined): string {
  return [route?.view, route?.project, route?.harness, route?.session].join('\n');
}

import { describe, expect, it } from 'vitest';
import {
  canonicalFragment,
  fragmentForRoute,
  parseFragment,
  routeIdentity,
  routeOrigin,
  sessionHome,
  type RouteInput,
} from './grammar';
import { loadLegacyBoot } from './legacyBoot.test.helper';

const enc = encodeURIComponent;

describe('every released fragment parses to its route and prints back canonically', () => {
  const top = (view: string) => ({ view, project: null, session: null });
  const table: readonly {
    readonly name: string;
    readonly fragment: string;
    readonly route: RouteInput;
    readonly canonical: string;
  }[] = [
    {
      name: 'the bare fragment lands on Sessions',
      fragment: '',
      route: top('sessions'),
      canonical: '#n=sessions',
    },
    {
      name: 'a hash with no n token lands on Sessions',
      fragment: '#',
      route: top('sessions'),
      canonical: '#n=sessions',
    },
    {
      name: 'an unknown view lands on Sessions',
      fragment: '#n=bogus',
      route: top('sessions'),
      canonical: '#n=sessions',
    },
    {
      name: 'an empty n token lands on Sessions',
      fragment: '#n=',
      route: top('sessions'),
      canonical: '#n=sessions',
    },
    { name: 'sessions', fragment: '#n=sessions', route: top('sessions'), canonical: '#n=sessions' },
    {
      name: 'attention',
      fragment: '#n=attention',
      route: top('attention'),
      canonical: '#n=attention',
    },
    { name: 'projects', fragment: '#n=projects', route: top('projects'), canonical: '#n=projects' },
    { name: 'intent', fragment: '#n=intent', route: top('intent'), canonical: '#n=intent' },
    { name: 'settings', fragment: '#n=settings', route: top('settings'), canonical: '#n=settings' },
    {
      name: 'a top-level view carries no suffix',
      fragment: '#n=attention&from=sessions',
      route: top('attention'),
      canonical: '#n=attention',
    },
    {
      name: 'a project root',
      fragment: '#n=project:recce',
      route: { view: 'project', project: 'recce', session: null },
      canonical: '#n=project:recce',
    },
    {
      name: 'a project name with a colon, a slash and a space is encoded per part',
      fragment: `#n=project:${enc('a:b/c d')}`,
      route: { view: 'project', project: 'a:b/c d', session: null },
      canonical: `#n=project:${enc('a:b/c d')}`,
    },
    {
      name: 'an empty project is not a project route',
      fragment: '#n=project:',
      route: top('sessions'),
      canonical: '#n=sessions',
    },
    {
      name: 'a project tab',
      fragment: '#n=project:recce:course',
      route: { view: 'project', project: 'recce', session: null, tab: 'course' },
      canonical: '#n=project:recce:course',
    },
    {
      name: 'Now is the default and is not printed',
      fragment: '#n=project:recce:now',
      route: { view: 'project', project: 'recce', session: null, tab: 'now' },
      canonical: '#n=project:recce',
    },
    {
      name: 'decisions',
      fragment: '#n=project:recce:decisions',
      route: { view: 'project', project: 'recce', session: null, tab: 'decisions' },
      canonical: '#n=project:recce:decisions',
    },
    {
      name: 'console',
      fragment: '#n=project:recce:console',
      route: { view: 'project', project: 'recce', session: null, tab: 'console' },
      canonical: '#n=project:recce:console',
    },
    {
      name: 'a third part that is no tab is a focused session of the project',
      fragment: `#n=project:recce:${enc('claude:one')}`,
      route: { view: 'project', project: 'recce', session: null, focus: 'claude:one' },
      canonical: `#n=project:recce:${enc('claude:one')}`,
    },
    {
      name: 'a focused session with a tab',
      fragment: `#n=project:recce:${enc('claude:one')}:console`,
      route: {
        view: 'project',
        project: 'recce',
        session: null,
        focus: 'claude:one',
        tab: 'console',
      },
      canonical: `#n=project:recce:${enc('claude:one')}:console`,
    },
    {
      name: 'a focused session at Now prints without the tab',
      fragment: `#n=project:recce:${enc('claude:one')}:now`,
      route: { view: 'project', project: 'recce', session: null, focus: 'claude:one', tab: 'now' },
      canonical: `#n=project:recce:${enc('claude:one')}`,
    },
    {
      name: 'a focused session with an unknown fourth part is not a project route',
      fragment: `#n=project:recce:${enc('claude:one')}:nonsense`,
      route: top('sessions'),
      canonical: '#n=sessions',
    },
    {
      name: 'the retired held-to slug aliases to the exact session',
      fragment: `#n=project:recce:${enc('claude:one')}:held-to`,
      route: { view: 'session', project: 'recce', harness: 'claude', session: 'one' },
      canonical: `#n=session:recce:claude:one`,
    },
    {
      name: 'a held-to sid keeps every colon after the first',
      fragment: `#n=project:recce:${enc('codex:a:b')}:held-to`,
      route: { view: 'session', project: 'recce', harness: 'codex', session: 'a:b' },
      canonical: `#n=session:recce:codex:${enc('a:b')}`,
    },
    {
      name: 'a held-to focus with no harness falls to the id-only session form',
      fragment: `#n=project:recce:${enc('loose')}:held-to`,
      route: { view: 'session', project: 'recce', session: 'loose' },
      canonical: '#n=session:recce:loose',
    },
    {
      name: 'a held-to focus with no sid after the harness is no route at all',
      fragment: `#n=project:recce:${enc('codex:')}:held-to`,
      route: top('sessions'),
      canonical: '#n=sessions',
    },
    {
      name: 'an exact session',
      fragment: '#n=session:recce:claude:one',
      route: { view: 'session', project: 'recce', harness: 'claude', session: 'one' },
      canonical: '#n=session:recce:claude:one',
    },
    {
      name: 'the same sid under two harnesses is two routes',
      fragment: '#n=session:recce:codex:one',
      route: { view: 'session', project: 'recce', harness: 'codex', session: 'one' },
      canonical: '#n=session:recce:codex:one',
    },
    {
      name: 'a sid with colons is encoded in its part',
      fragment: `#n=session:${enc('a/b')}:claude:${enc('x:y')}`,
      route: { view: 'session', project: 'a/b', harness: 'claude', session: 'x:y' },
      canonical: `#n=session:${enc('a/b')}:claude:${enc('x:y')}`,
    },
    {
      name: 'an empty project is a valid session project',
      fragment: '#n=session::claude:one',
      route: { view: 'session', project: '', harness: 'claude', session: 'one' },
      canonical: '#n=session::claude:one',
    },
    {
      name: 'the released id-only session form',
      fragment: '#n=session:recce:one',
      route: { view: 'session', project: 'recce', session: 'one' },
      canonical: '#n=session:recce:one',
    },
    {
      name: 'the id-only form with an empty project',
      fragment: '#n=session::one',
      route: { view: 'session', project: '', session: 'one' },
      canonical: '#n=session::one',
    },
    {
      name: 'an origin is kept when it is in the closed set',
      fragment: '#n=session:recce:claude:one&from=attention',
      route: {
        view: 'session',
        project: 'recce',
        harness: 'claude',
        session: 'one',
        from: 'attention',
      },
      canonical: '#n=session:recce:claude:one&from=attention',
    },
    ...['sessions', 'attention', 'intent', 'projects', 'project'].map((from) => ({
      name: `origin ${from} is in the closed set`,
      fragment: `#n=session:recce:claude:one&from=${from}`,
      route: { view: 'session', project: 'recce', harness: 'claude', session: 'one', from },
      canonical: `#n=session:recce:claude:one&from=${from}`,
    })),
    {
      name: 'an unknown origin is omitted',
      fragment: '#n=session:recce:claude:one&from=elsewhere',
      route: { view: 'session', project: 'recce', harness: 'claude', session: 'one' },
      canonical: '#n=session:recce:claude:one',
    },
    {
      name: 'an origin on the id-only form',
      fragment: '#n=session:recce:one&from=intent',
      route: { view: 'session', project: 'recce', session: 'one', from: 'intent' },
      canonical: '#n=session:recce:one&from=intent',
    },
    {
      name: 'a stray query beside the origin is dropped',
      fragment: '#n=session:recce:claude:one&x=1&from=projects',
      route: {
        view: 'session',
        project: 'recce',
        harness: 'claude',
        session: 'one',
        from: 'projects',
      },
      canonical: '#n=session:recce:claude:one&from=projects',
    },
    {
      name: 'malformed percent encoding in the project never names the empty project',
      fragment: '#n=session:%E0%A4%A:claude:one',
      route: top('sessions'),
      canonical: '#n=sessions',
    },
    {
      name: 'malformed percent encoding in the sid lands on Sessions',
      fragment: '#n=session:recce:claude:%E0%A4%A',
      route: top('sessions'),
      canonical: '#n=sessions',
    },
    {
      name: 'malformed percent encoding in the id-only form lands on Sessions',
      fragment: '#n=session:%E0%A4%A:one',
      route: top('sessions'),
      canonical: '#n=sessions',
    },
    {
      name: 'an empty harness part is not the exact form',
      fragment: '#n=session:recce::one',
      route: top('sessions'),
      canonical: '#n=sessions',
    },
    {
      name: 'an empty sid is no session',
      fragment: '#n=session:recce:claude:',
      route: top('sessions'),
      canonical: '#n=sessions',
    },
    {
      name: 'a fifth part is no session',
      fragment: '#n=session:recce:claude:one:two',
      route: top('sessions'),
      canonical: '#n=sessions',
    },
    {
      name: 'a malformed project root lands on Sessions rather than a dead filter',
      fragment: '#n=project:%E0%A4%A',
      route: top('sessions'),
      canonical: '#n=sessions',
    },
    {
      name: 'a fragment that does not start with #n= is no route',
      fragment: '#session:recce:claude:one',
      route: top('sessions'),
      canonical: '#n=sessions',
    },
  ];

  it.each(table)('$name', ({ fragment, route, canonical }) => {
    const parsed = parseFragment(fragment);
    expect(parsed).toEqual(route);
    expect(fragmentForRoute(parsed)).toBe(canonical);
    expect(canonicalFragment(fragment)).toBe(canonical);
    // Canonical output is a fixed point. The route may differ (an explicit Now tab is the default
    // and is not printed), but the fragment it prints never moves again.
    expect(canonicalFragment(canonical)).toBe(canonical);
  });
});

describe('printing a route', () => {
  it('prints a session with no project as the landing view, never an invented one', () => {
    expect(fragmentForRoute({ view: 'session', project: null, session: 'one' })).toBe(
      '#n=sessions',
    );
  });

  it('prints a retired held-to tab as the exact session it meant', () => {
    expect(
      fragmentForRoute({
        view: 'project',
        project: 'recce',
        session: null,
        focus: 'claude:one',
        tab: 'held-to',
      }),
    ).toBe('#n=session:recce:claude:one');
  });

  it('keeps the held-to alias distinct from a focus whose sid is empty', () => {
    expect(
      fragmentForRoute({
        view: 'project',
        project: 'recce',
        session: null,
        focus: 'codex:',
        tab: 'held-to',
      }),
    ).toBe('#n=project:recce:codex%3A');
  });

  it('drops a tab the focus does not offer and an origin outside the closed set', () => {
    expect(
      fragmentForRoute({ view: 'project', project: 'recce', session: null, tab: 'bogus' }),
    ).toBe('#n=project:recce');
    expect(
      fragmentForRoute({
        view: 'session',
        project: 'recce',
        harness: 'claude',
        session: 'one',
        from: 'nowhere',
      }),
    ).toBe('#n=session:recce:claude:one');
  });

  it('prints an unknown view and a missing route as Sessions', () => {
    expect(fragmentForRoute({ view: 'bogus', project: null, session: null })).toBe('#n=sessions');
    expect(fragmentForRoute(null)).toBe('#n=sessions');
  });
});

describe('where a session was opened from', () => {
  const session = (from?: string): RouteInput => ({
    view: 'session',
    project: 'p',
    harness: 'h',
    session: 's',
    ...(from ? { from } : {}),
  });

  it('names the view a reader came from and defaults an absent or unknown origin to Sessions', () => {
    expect(sessionHome(session())).toBe('sessions');
    expect(sessionHome(session('sessions'))).toBe('sessions');
    expect(sessionHome(session('attention'))).toBe('attention');
    expect(sessionHome(session('intent'))).toBe('intent');
    expect(sessionHome(session('projects'))).toBe('projects');
    expect(sessionHome(session('project'))).toBe('projects');
    expect(sessionHome(session('bogus'))).toBe('sessions');
  });

  it('stamps an origin from a top-level view, a project, and a session that already carries one', () => {
    expect(routeOrigin({ view: 'attention', project: null, session: null })).toBe('attention');
    expect(routeOrigin({ view: 'project', project: 'p', session: null })).toBe('project');
    expect(routeOrigin(session('intent'))).toBe('intent');
    expect(routeOrigin(session())).toBeNull();
    expect(routeOrigin(null)).toBeNull();
  });

  it('treats a tab or scope change inside one page as the same page, and a new session as a new one', () => {
    const a = parseFragment('#n=project:recce:course');
    const b = parseFragment('#n=project:recce:decisions');
    expect(routeIdentity(a)).toBe(routeIdentity(b));
    expect(routeIdentity(parseFragment('#n=session:recce:claude:one'))).not.toBe(
      routeIdentity(parseFragment('#n=session:recce:codex:one')),
    );
    expect(routeIdentity(parseFragment('#n=session:recce:claude:one&from=sessions'))).toBe(
      routeIdentity(parseFragment('#n=session:recce:claude:one')),
    );
  });
});

/* The legacy grammar is the oracle: it keeps rollback compatible, so where it and this port disagree the
   port is wrong. The file is read and run as the page runs it, with only the browser objects it touches
   stubbed, and the comparison is over the route and its canonical fragment together. */
describe('the port agrees with the legacy grammar', () => {
  const legacy = loadLegacyBoot();
  const legacyParse = legacy.parse;
  const legacyPrint = legacy.print;

  const projects = ['recce', '', 'a:b', 'a/b c', 'é', '%', '&', 'x&from=attention'];
  const sids = ['one', 'x:y', 'colon:', ':lead', 'a b', '%20', ''];
  const harnesses = ['claude', 'codex', '', 'x:y'];
  const raw = [
    '',
    '#',
    '#n',
    '#n=',
    '#n=sessions',
    '#n=bogus',
    '#n=attention&from=intent',
    '#N=sessions',
    '#n=project:',
    '#n=project::',
    '#n=session:::',
  ];
  const generated: string[] = [...raw];
  for (const project of projects) {
    generated.push(`#n=project:${enc(project)}`);
    for (const sid of sids) {
      generated.push(
        `#n=session:${enc(project)}:${enc(sid)}`,
        `#n=project:${enc(project)}:${enc(sid)}`,
      );
      for (const harness of harnesses) {
        generated.push(`#n=session:${enc(project)}:${enc(harness)}:${enc(sid)}`);
        generated.push(`#n=session:${enc(project)}:${enc(harness)}:${enc(sid)}&from=attention`);
        generated.push(
          `#n=session:${enc(project)}:${enc(harness)}:${enc(sid)}&from=nope&from=intent`,
        );
        generated.push(`#n=project:${enc(project)}:${enc(`${harness}:${sid}`)}:held-to`);
        generated.push(`#n=project:${enc(project)}:${enc(`${harness}:${sid}`)}:console`);
        generated.push(`#n=project:${enc(project)}:${enc(`${harness}:${sid}`)}:bogus`);
      }
    }
    for (const tab of ['now', 'course', 'decisions', 'console', 'held-to', 'other'])
      generated.push(`#n=project:${enc(project)}:${tab}`);
  }
  // Malformed escapes in every part position.
  for (const bad of ['%E0%A4%A', '%', '%ZZ', '%C3']) {
    generated.push(
      `#n=session:${bad}:claude:one`,
      `#n=session:p:${bad}:one`,
      `#n=session:p:claude:${bad}`,
      `#n=session:${bad}:one`,
      `#n=session:p:${bad}`,
    );
    generated.push(
      `#n=project:${bad}`,
      `#n=project:p:${bad}`,
      `#n=project:p:${bad}:console`,
      `#n=project:p:x:${bad}`,
    );
  }

  it('parses and prints the same for every generated fragment', () => {
    expect(generated.length).toBeGreaterThan(500);
    for (const fragment of generated) {
      const legacy = legacyParse(fragment);
      const ported = parseFragment(fragment);
      // The legacy route is a plain object built inside another realm; compare by value.
      expect(JSON.parse(JSON.stringify(ported)), fragment).toEqual(
        JSON.parse(JSON.stringify(legacy)),
      );
      expect(fragmentForRoute(ported), fragment).toBe(legacyPrint(legacy));
    }
  });
});

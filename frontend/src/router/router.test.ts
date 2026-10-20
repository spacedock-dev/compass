import { describe, expect, it, vi } from 'vitest';
import { createRouter } from './router';
import { fakeRouterEnvironment as fakeEnvironment } from './testing';

describe('the router starts from the address and canonicalises it without adding history', () => {
  it.each([
    ['', '#n=sessions'],
    ['#n=bogus', '#n=sessions'],
    ['#n=session:recce:claude:one&from=elsewhere', '#n=session:recce:claude:one'],
    [`#n=project:recce:${encodeURIComponent('claude:one')}:held-to`, '#n=session:recce:claude:one'],
    ['#n=session:%E0%A4%A:claude:one', '#n=sessions'],
  ])('%s becomes %s by replacement', (typed, canonical) => {
    const fake = fakeEnvironment(typed);
    const router = createRouter(fake.env);
    expect(fake.entries()).toEqual([canonical]);
    expect(fake.calls.replace).toEqual([canonical]);
    expect(fake.calls.push).toEqual([]);
    expect(router.getRoute()).toEqual(createRouter(fakeEnvironment(canonical).env).getRoute());
  });

  it('leaves an already canonical address alone', () => {
    const fake = fakeEnvironment('#n=attention');
    createRouter(fake.env);
    expect(fake.calls.replace).toEqual([]);
    expect(fake.calls.push).toEqual([]);
  });
});

describe('moving between views', () => {
  it('pushes one history entry per move, and Back returns to the preceding view', () => {
    const fake = fakeEnvironment('#n=sessions');
    const router = createRouter(fake.env);
    const stop = router.subscribe(() => undefined);
    router.navigate({ view: 'attention', project: null, session: null });
    fake.flush();
    router.navigate({ view: 'projects', project: null, session: null });
    fake.flush();
    expect(fake.entries()).toEqual(['#n=sessions', '#n=attention', '#n=projects']);
    expect(router.getRoute().view).toBe('projects');
    fake.back();
    fake.flush();
    expect(router.getRoute().view).toBe('attention');
    fake.back();
    fake.flush();
    expect(router.getRoute().view).toBe('sessions');
    fake.forward();
    fake.flush();
    expect(router.getRoute().view).toBe('attention');
    stop();
  });

  it('draws a move once: the hashchange its own write announces changes nothing', () => {
    const fake = fakeEnvironment('#n=sessions');
    const router = createRouter(fake.env);
    const listener = vi.fn();
    const stop = router.subscribe(listener);
    router.navigate({ view: 'attention', project: null, session: null });
    expect(listener).toHaveBeenCalledTimes(1);
    fake.flush();
    expect(listener).toHaveBeenCalledTimes(1);
    stop();
  });

  it('does not push an entry for the route already shown', () => {
    const fake = fakeEnvironment('#n=attention');
    const router = createRouter(fake.env);
    router.navigate({ view: 'attention', project: null, session: null });
    expect(fake.calls.push).toEqual([]);
    expect(fake.calls.assigned).toEqual([]);
  });

  it('opens a new page at its top and leaves a tab change within one where it was', () => {
    const fake = fakeEnvironment('#n=project:recce');
    const router = createRouter(fake.env);
    router.navigate({ view: 'project', project: 'recce', session: null, tab: 'course' });
    expect(fake.calls.scroll).toBe(0);
    router.navigate({ view: 'projects', project: null, session: null });
    expect(fake.calls.scroll).toBe(1);
  });

  it('opens a page reached by a typed address or Back at its top too, and a tab change where it was', () => {
    const fake = fakeEnvironment('#n=project:recce');
    const router = createRouter(fake.env);
    router.subscribe(() => undefined);
    fake.type('#n=project:recce:course');
    fake.flush();
    expect(fake.calls.scroll).toBe(0);
    fake.type('#n=session:recce:codex:one');
    fake.flush();
    expect(fake.calls.scroll).toBe(1);
    fake.back();
    fake.flush();
    expect(fake.calls.scroll).toBe(2);
  });

  it('rewrites a pasted or malformed fragment by replacement, so Back is never stuck on it', () => {
    const fake = fakeEnvironment('#n=sessions');
    const router = createRouter(fake.env);
    router.subscribe(() => undefined);
    fake.type('#n=nonsense');
    fake.flush();
    expect(router.getRoute().view).toBe('sessions');
    expect(fake.calls.replace).toEqual(['#n=sessions']);
    expect(fake.entries()).toEqual(['#n=sessions', '#n=sessions']);
  });

  it('follows a hash typed into the address bar', () => {
    const fake = fakeEnvironment('#n=sessions');
    const router = createRouter(fake.env);
    router.subscribe(() => undefined);
    fake.type('#n=session:recce:codex:one&from=attention');
    fake.flush();
    expect(router.getRoute()).toEqual({
      view: 'session',
      project: 'recce',
      harness: 'codex',
      session: 'one',
      from: 'attention',
    });
  });

  it('keeps no hashchange listener while nothing is subscribed, and one while several are', () => {
    const fake = fakeEnvironment('#n=sessions');
    const router = createRouter(fake.env);
    expect(fake.listenerCount()).toBe(0);
    const first = router.subscribe(() => undefined);
    const second = router.subscribe(() => undefined);
    expect(fake.listenerCount()).toBe(1);
    first();
    expect(fake.listenerCount()).toBe(1);
    second();
    expect(fake.listenerCount()).toBe(0);
  });

  it('picks up a change made between creation and the first subscriber', () => {
    const fake = fakeEnvironment('#n=sessions');
    const router = createRouter(fake.env);
    fake.type('#n=attention');
    fake.flush();
    const listener = vi.fn();
    router.subscribe(listener);
    expect(router.getRoute().view).toBe('attention');
  });
});

describe('where a session was opened from', () => {
  const session = { view: 'session', project: 'recce', harness: 'claude', session: 'one' } as const;

  it('stamps the view a session is opened from, so the tab, the crumb and Escape agree after a reload', () => {
    const fake = fakeEnvironment('#n=attention');
    const router = createRouter(fake.env);
    router.navigate(session);
    expect(fake.entries().at(-1)).toBe('#n=session:recce:claude:one&from=attention');
    expect(router.getRoute()).toMatchObject({ from: 'attention' });
  });

  it('keeps the origin a session already carries rather than stamping over it', () => {
    const fake = fakeEnvironment('#n=attention');
    const router = createRouter(fake.env);
    router.navigate({ ...session, from: 'intent' });
    expect(fake.entries().at(-1)).toBe('#n=session:recce:claude:one&from=intent');
  });

  it('names a project page as the origin, and reads a pasted link as Sessions', () => {
    const fake = fakeEnvironment('#n=project:recce');
    const router = createRouter(fake.env);
    router.navigate(session);
    expect(fake.entries().at(-1)).toBe('#n=session:recce:claude:one&from=project');
    const pasted = createRouter(fakeEnvironment('#n=session:recce:claude:one').env);
    expect(pasted.getRoute()).not.toHaveProperty('from');
  });
});

describe('a router that nobody listens to', () => {
  it('can still be asked for its route and moved', () => {
    const fake = fakeEnvironment('#n=sessions');
    const router = createRouter(fake.env);
    router.navigate({ view: 'intent', project: null, session: null });
    expect(router.getRoute().view).toBe('intent');
  });
});

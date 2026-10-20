import {
  fragmentForRoute,
  parseFragment,
  routeIdentity,
  routeOrigin,
  type Route,
  type RouteInput,
} from './grammar';

/* The browser surface the router reads and writes, as interfaces it owns so a test can run a
   history without a window. `setHash` is `location.hash = ...`, which pushes an entry and later
   fires `hashchange`; `replaceHash` is `history.replaceState`, which does neither. */
export interface RouterEnvironment {
  getHash(): string;
  setHash(fragment: string): void;
  replaceHash(fragment: string): void;
  onHashChange(listener: () => void): () => void;
  scrollToTop(): void;
}

export function browserRouterEnvironment(): RouterEnvironment {
  return {
    getHash: () => window.location.hash,
    setHash(fragment) {
      window.location.hash = fragment;
    },
    replaceHash(fragment) {
      window.history.replaceState(window.history.state, '', fragment);
    },
    onHashChange(listener) {
      window.addEventListener('hashchange', listener);
      return () => window.removeEventListener('hashchange', listener);
    },
    scrollToTop() {
      window.scrollTo(0, 0);
    },
  };
}

/* The one place the address and the shown route are kept in step. Held outside React, as the
   board's store is, so the route survives a remount and `useSyncExternalStore` reads it without
   an effect.

   A canonical spelling REPLACES the history entry rather than pushing one: pushing left Back
   stuck on a malformed or retired link, which canonicalised itself forward again on every press.
   The initial rewrite happens here, at creation, before anything is drawn, so no frame shows a
   route the address does not name and a StrictMode double effect cannot repeat it. */
export function createRouter(env: RouterEnvironment = browserRouterEnvironment()) {
  let route: Route = parseFragment(env.getHash());
  const initial = fragmentForRoute(route);
  if (env.getHash() !== initial) env.replaceHash(initial);

  const listeners = new Set<() => void>();
  let detach: (() => void) | null = null;

  function notify(): void {
    for (const listener of [...listeners]) listener();
  }

  function onHashChange(): void {
    const parsed = parseFragment(env.getHash());
    const fragment = fragmentForRoute(parsed);
    if (env.getHash() !== fragment) env.replaceHash(fragment);
    // `navigate` already drew the route its own hash write announces.
    if (fragment === fragmentForRoute(route)) return;
    const moved = routeIdentity(parsed) !== routeIdentity(route);
    route = parsed;
    notify();
    /* Back, Forward and a typed address open a new page too: they kept the old page's scroll, so a session
       opened mid-card (usability review, 2026-10-20). The fragment is the route, so there is no anchor
       in it to keep. */
    if (moved) env.scrollToTop();
  }

  return {
    getRoute: (): Route => route,

    /* Every route producer lands here, so an origin is stamped once rather than at each link: a
       session opened without one takes the view it was opened from. A new page opens at its top; a
       tab or scope change within one does not move the reader. */
    navigate(target: RouteInput): void {
      let next = target;
      if (next.view === 'session' && !next.from) {
        const from = routeOrigin(route);
        if (from) next = { ...next, from };
      }
      const fragment = fragmentForRoute(next);
      const parsed = parseFragment(fragment);
      const moved = routeIdentity(parsed) !== routeIdentity(route);
      route = parsed;
      if (env.getHash() !== fragment) env.setHash(fragment);
      notify();
      if (moved) env.scrollToTop();
    },

    /* The `hashchange` listener exists only while something listens, so an unmounted page leaves
       none behind. A change made before the first subscriber is read on subscribing. */
    subscribe(listener: () => void): () => void {
      listeners.add(listener);
      if (listeners.size === 1) {
        detach = env.onHashChange(onHashChange);
        onHashChange();
      }
      return () => {
        listeners.delete(listener);
        if (listeners.size === 0) {
          detach?.();
          detach = null;
        }
      };
    },
  };
}

export type Router = ReturnType<typeof createRouter>;

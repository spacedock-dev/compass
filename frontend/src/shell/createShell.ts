import { createControls, type Announce, type ControlsDeps } from '../controls/kit';
import { startWorkstream } from '../workstream';
import { choiceOpenIn, createDisplayGate } from '../controls/displayGate';
import { createRouter, type Router } from '../router/router';
import {
  browserBeacon,
  createBrowserEnvironment,
  createBrowserRuntime,
  type BrowserRuntimeOptions,
} from '../transport/browser';
import type { Environment, EventSourceLike } from '../transport/ports';
import { createAnnouncer, type Announcer } from './announcer';
import type { Shell, ShellHost } from './context';

export interface ShellOptions
  extends Pick<BrowserRuntimeOptions, 'fetch' | 'provider' | 'events' | 'search' | 'doc'> {
  readonly env?: Environment;
  readonly router?: Router;
  /** A second shell (the sample session's) speaks through the page's own live regions. */
  readonly announcer?: Announcer;
  readonly host?: Partial<ShellHost>;
  readonly clipboard?: ControlsDeps['clipboard'];
  readonly reducedMotion?: () => boolean;
}

function prefersReducedMotion(): boolean {
  return (
    typeof window.matchMedia === 'function' &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches
  );
}

/* A control announces through one function; the legacy page kept the copy and raise sentences in
   their own regions, written plainly because each press is its own act, and everything else in the
   guarded cue region. The control's key names its kind, and a press number makes it unique. */
function routeAnnouncement(announcer: ReturnType<typeof createAnnouncer>): Announce {
  return (key, text) => {
    if (key.startsWith('copy:')) announcer.say('copy', text);
    else if (key.startsWith('raise:')) announcer.say('raise', text);
    else announcer.announce(key, text);
  };
}

/* The one place the page's owners are built. The order is the dependency order: the announcer and the
   display gate exist before the runtime that calls them, and the gate is attached to the runtime's
   store afterwards, which is why `paint` reaches it through a closure rather than by reference. */
export function createShell(options: ShellOptions = {}): Shell {
  const env =
    options.env ??
    createBrowserEnvironment({
      window,
      document,
      EventSource:
        typeof EventSource === 'undefined'
          ? undefined
          : (EventSource as unknown as new (
              url: string,
            ) => EventSourceLike),
      now: () => Date.now(),
      ...browserBeacon(),
    });
  const reducedMotion = options.reducedMotion ?? prefersReducedMotion;
  const announcer = options.announcer ?? createAnnouncer();
  const display = createDisplayGate({
    clock: env.clock,
    reducedMotion,
    isChoiceOpen: () => choiceOpenIn(() => document.getElementById('app')),
  });
  const runtime = createBrowserRuntime({
    env,
    paint: (info) => display.paint(info),
    announce: (key, sentence) => announcer.announce(`pending:${key}`, sentence),
    forget: (key) => announcer.forget(`pending:${key}`),
    ...(options.fetch ? { fetch: options.fetch } : {}),
    ...(options.provider ? { provider: options.provider } : {}),
    ...(options.events ? { events: options.events } : {}),
    ...(options.search !== undefined ? { search: options.search } : {}),
    ...(options.doc !== undefined ? { doc: options.doc } : {}),
  });
  display.attach(runtime.store);
  // Observed from the first payload, so the workstream and the delegation figure can reach back to it.
  startWorkstream(runtime);
  const controls = createControls({
    clock: env.clock,
    announce: routeAnnouncement(announcer),
    memo: runtime.storage.memo,
    reducedMotion,
    noteToggle: () => display.noteToggle(),
    // An absent capability is the feature being off for this run, and no raise control draws.
    ...(runtime.bootstrap.focusCapability
      ? { focus: (identity: Parameters<typeof runtime.focus>[0]) => runtime.focus(identity) }
      : {}),
    ...(options.clipboard ? { clipboard: options.clipboard } : {}),
  });
  return {
    runtime,
    router: options.router ?? createRouter(),
    announcer,
    display,
    controls,
    clock: env.clock,
    env,
    host: {
      reload: options.host?.reload ?? (() => window.location.reload()),
      streamSupported: options.host?.streamSupported ?? env.streamSupported,
    },
  };
}

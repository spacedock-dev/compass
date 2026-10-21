import { useSyncExternalStore } from 'react';
import type { SessionIdentity } from '../storage';
import { useShell, type Shell } from '../shell/context';

/* The live monitor switch is off by default and remembered per session in this browser only, as `1` under
   `compass.next.live-estimate:<harness>:<sid>` while it is on and no key while it is off. Nothing about it
   is ever sent: the server publishes the focused session's estimate whichever way it is set, and the switch
   decides only whether the level, its nudge and the header pill are drawn. Where storage throws, the
   in-memory choice holds it for the tab. The storage itself is the shell's one `LegacyStorage`; this is the
   change notification a component needs on top of it. */
interface Monitor {
  subscribe(listener: () => void): () => void;
  version(): number;
  on(session: SessionIdentity): boolean;
  set(session: SessionIdentity, on: boolean): void;
}

const monitors = new WeakMap<Shell, Monitor>();

export function liveMonitorFor(shell: Shell): Monitor {
  let monitor = monitors.get(shell);
  if (monitor) return monitor;
  const listeners = new Set<() => void>();
  let version = 0;
  const { liveEstimate } = shell.runtime.storage;
  monitor = {
    subscribe(listener) {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    version: () => version,
    on: (session) => liveEstimate.on(session),
    set(session, on) {
      liveEstimate.set(session, on);
      version += 1;
      for (const listener of [...listeners]) listener();
    },
  };
  monitors.set(shell, monitor);
  return monitor;
}

/* Whether the switch is on for this exact session, and the setter. Re-read on every change of the switch. */
export function useLiveMonitor(
  shell: Shell,
  session: SessionIdentity,
): readonly [boolean, (on: boolean) => void] {
  const monitor = liveMonitorFor(shell);
  useSyncExternalStore(monitor.subscribe, monitor.version);
  return [monitor.on(session), (on) => monitor.set(session, on)];
}

/* The harnesses whose live estimate the server publishes: the deterministic level read from checks and file
   paths. Claude's only today, so the switch is drawn nowhere else. */
export const LIVE_HARNESSES: ReadonlySet<string> = new Set(['claude']);

/* Whether the switch is drawn for this session: a harness with a live estimate, with annotations on. */
export function liveMonitorShown(
  session: Readonly<Record<string, unknown>>,
  payload: Readonly<Record<string, unknown>>,
): boolean {
  return LIVE_HARNESSES.has(String(session['harness'] || '')) && payload['annotate'] === true;
}

/* Whether the live estimate is wanted for this session, for the Drift step that draws it. */
export function useLiveEstimateOn(session: Readonly<Record<string, unknown>>): boolean {
  const shell = useShell();
  const [on] = useLiveMonitor(shell, {
    harness: String(session['harness'] || ''),
    sid: String(session['sid'] || ''),
    session: String(session['session'] || ''),
  });
  return LIVE_HARNESSES.has(String(session['harness'] || '')) && on;
}

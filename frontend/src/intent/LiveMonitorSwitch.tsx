import { Button } from '../ui/button';
import { compatSessKey } from '../api/identity';
import { useFocusKey } from '../controls';
import { useShell } from '../shell/context';
import { useLiveMonitor } from './liveMonitor';
import { LIVE_MONITOR } from './sentences';
import { LIVE_HINT } from '../drift/sentences';
import { usePanel } from './useIntent';

/* Drawn in the Drift card's settings, one press from its head. It drives the Live monitor's lease on the
   server: on starts a Haiku check about once a minute while this session is on screen and the tab is
   visible, and the server's own "What is sent" sentence stands under it while it is on. It is `aria-disabled`,
   never `disabled`, with its reason beside it when there is nothing live to monitor (the session has ended)
   or model calls are paused or off, so focus is kept where it was. */
export function LiveMonitorSwitch() {
  const shell = useShell();
  const { session, payload } = usePanel();
  const key = compatSessKey(session);
  const view = useLiveMonitor(session, payload);
  const ref = useFocusKey<HTMLButtonElement>(shell.controls.focusLane, `live-monitor:${key}`);
  if (!view.shown) return null;
  const sent = view.on ? view.lease.disclosure : null;
  return (
    <div className="flex max-w-[22rem] flex-col items-start gap-1">
      <div className="next-session-drift-monitor mt-0">
        <span id="next-session-drift-monitor-label">{LIVE_MONITOR}</span>
        <Button
          variant="native"
          ref={ref}
          type="button"
          className="next-session-drift-switch"
          role="switch"
          aria-checked={view.on}
          aria-disabled={view.blocked !== null || undefined}
          aria-labelledby="next-session-drift-monitor-label"
          aria-describedby={`next-session-drift-monitor-hint${view.blocked ? ' next-session-drift-monitor-reason' : ''}`}
          data-next-cockpit-action="live-monitor"
          data-next-focus={`live-monitor:${key}`}
          onClick={(event) => {
            event.preventDefault();
            view.press(!view.on);
          }}
        >
          <span className="next-session-drift-track" aria-hidden="true">
            <span />
          </span>
        </Button>
      </div>
      {view.blocked ? (
        <p
          id="next-session-drift-monitor-reason"
          className="m-0 text-label leading-[1.4] text-foreground"
          data-next-live-reason
        >
          {view.blocked}
        </p>
      ) : null}
      <p
        id="next-session-drift-monitor-hint"
        className="m-0 text-label leading-[1.4] text-muted-foreground"
        data-next-live-hint
      >
        {LIVE_HINT}
      </p>
      {sent ? (
        <p className="m-0 text-label leading-[1.4] text-muted-foreground" data-next-live-sent>
          {sent}
        </p>
      ) : null}
    </div>
  );
}

import { Switch } from '../ui/switch';
import { compatSessKey } from '../api/identity';
import { useFocusKey } from '../controls';
import { useShell } from '../shell/context';
import { useLiveMonitor } from './liveMonitor';
import { LIVE_MONITOR } from './sentences';
import { LIVE_HINT, LIVE_MONITOR_DETAILS } from '../drift/sentences';
import { useDrift } from '../drift/context';

/* Drawn under AI use and privacy in the session’s technical details. It drives the Live monitor's lease on the
   server: on starts a Haiku check about once a minute while this session is on screen and the tab is
   visible, and the server's own "What is sent" sentence stands under it while it is on. It is `aria-disabled`,
   never `disabled`, with its reason beside it when there is nothing live to monitor (the session has ended)
   or model calls are paused or off, so focus is kept where it was. */
export function LiveMonitorSwitch() {
  const shell = useShell();
  const {
    model: { session, payload },
  } = useDrift();
  const key = compatSessKey(session);
  const view = useLiveMonitor(session, payload);
  const ref = useFocusKey<HTMLButtonElement>(shell.controls.focusLane, `live-monitor:${key}`);
  if (!view.shown) return null;
  const sent = view.on ? view.lease.disclosure : null;
  return (
    <div className="next-session-drift-monitor flex items-start gap-2">
      <Switch
        ref={ref}
        checked={view.on}
        readOnly={view.blocked !== null}
        aria-disabled={view.blocked !== null || undefined}
        aria-labelledby="next-session-drift-monitor-label"
        aria-describedby={`next-session-drift-monitor-hint${view.blocked ? ' next-session-drift-monitor-reason' : ''} next-session-drift-monitor-details`}
        data-next-cockpit-action="live-monitor"
        data-next-focus={`live-monitor:${key}`}
        onCheckedChange={view.press}
      />
      <div className="flex min-w-0 flex-col gap-1">
        <span id="next-session-drift-monitor-label" className="text-body font-semibold">
          {LIVE_MONITOR}
        </span>
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
        <p
          id="next-session-drift-monitor-details"
          className="m-0 text-label leading-[1.4] text-muted-foreground"
        >
          {LIVE_MONITOR_DETAILS}
        </p>
        <p className="m-0 text-label text-muted-foreground">Live monitor · Haiku</p>
        {sent ? (
          <p className="m-0 text-label leading-[1.4] text-muted-foreground" data-next-live-sent>
            {sent}
          </p>
        ) : null}
      </div>
    </div>
  );
}

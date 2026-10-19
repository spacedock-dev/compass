import { Button } from '../ui/button';
import { compatSessKey } from '../api/identity';
import { useFocusKey } from '../controls';
import { useShell } from '../shell/context';
import { LIVE_HARNESSES, useLiveMonitor } from './liveMonitor';
import { LIVE_MONITOR } from './sentences';
import { usePanel } from './useIntent';

/* Drawn in the Drift card's head; placement only: its value still decides whether the live level, nudge and
   header pill are drawn, never whether the server or a model runs. */
export function LiveMonitorSwitch() {
  const shell = useShell();
  const { session, payload } = usePanel();
  const key = compatSessKey(session);
  const [on, set] = useLiveMonitor(shell, {
    harness: String(session['harness'] || ''),
    sid: String(session['sid'] || ''),
    session: String(session['session'] || ''),
  });
  const ref = useFocusKey<HTMLButtonElement>(shell.controls.focusLane, `live-monitor:${key}`);
  if (!LIVE_HARNESSES.has(String(session['harness'] || '')) || payload['annotate'] !== true) {
    return null;
  }
  return (
    <div className="next-session-drift-monitor">
      <span id="next-session-drift-monitor-label">{LIVE_MONITOR}</span>
      <Button
        variant="native"
        ref={ref}
        type="button"
        className="next-session-drift-switch"
        role="switch"
        aria-checked={on}
        aria-labelledby="next-session-drift-monitor-label"
        data-next-cockpit-action="live-monitor"
        data-next-focus={`live-monitor:${key}`}
        onClick={(event) => {
          event.preventDefault();
          set(!on);
        }}
      >
        <span className="next-session-drift-track" aria-hidden="true">
          <span />
        </span>
      </Button>
    </div>
  );
}

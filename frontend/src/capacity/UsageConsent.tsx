import { Button } from '../ui/button';
import { useFocusKey } from '../controls/useFocusKey';
import { useShell } from '../shell/context';
import { heldFor, useConsent, useUsageOffered } from './held';

/* The quota fetch and its off switch. SECURITY.md's "Usage quota reads" section is the contract and its
   "Consent and the off switch" paragraph is the promise this file keeps: the vendor numbers are read unless
   the reader turned them off on this origin, and the line saying so is on screen whenever the fetch is
   offered. `usage=1` rides a poll unless the transport reads `declined` from the same storage lane this
   writes (`transport/runtime`), so nothing here builds a request, and nothing here writes before a press. */

const SWITCH_KEY = 'usage:switch';

/* Records the answer the reader pressed, then asks for the board again so the answer is visibly acted on:
   without this refresh the change would wait out the ordinary poll and the reader would think the press did
   nothing. The refresh is a manual one, so the header says it is reading. */
function useAnswer() {
  const { runtime } = useShell();
  return (value: 'granted' | 'declined') => {
    heldFor(runtime).usage.answer(value);
    void runtime.refresh({ manual: true });
  };
}

/* `windows` is whether quota windows are drawn above the switch; with none, there is no cached read to describe.
   On until turned off: an unanswered origin reads as on, as `transport/runtime` sends it. */
export function UsageSwitch({ windows = true }: { windows?: boolean } = {}) {
  const offered = useUsageOffered();
  const consent = useConsent('usage');
  const answer = useAnswer();
  const { controls } = useShell();
  const buttonRef = useFocusKey<HTMLButtonElement>(controls.focusLane, SWITCH_KEY);
  if (!offered) return null;
  const on = consent !== 'declined';
  return (
    <p className="next-usage-switch" data-next-usage-switch={on ? 'on' : 'off'}>
      <span>
        {on
          ? 'Quota is read with the Claude Code and Cursor logins on this machine. No session content is sent.'
          : windows
            ? 'Quota reading is off. Windows above are the last cached read and will lapse.'
            : 'Quota reading is off. No window has been read.'}
      </span>
      <Button
        ref={buttonRef}
        type="button"
        tone="muted"
        data-next-usage-answer={on ? 'declined' : 'granted'}
        onClick={() => answer(on ? 'declined' : 'granted')}
      >
        {`Turn ${on ? 'off' : 'on'}`}
      </Button>
    </p>
  );
}

/** What the Console rail draws under its windows. */
export function RailUsage() {
  return <UsageSwitch />;
}

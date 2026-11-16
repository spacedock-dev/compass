import { Button } from '../ui/button';
import { useId } from 'react';
import { exactIdentity } from '../api/identity';
import type { FocusOutcome } from '../api/types';
import { laneKey } from './keyedState';
import { useControls, useKeyedValue, useValueStore, type CueState } from './kit';

export interface RaiseControlProps {
  readonly harness: string;
  readonly sid: string;
  /** The row's own published bit: only a session with a reported terminal draws a control. */
  readonly focusable: boolean;
  /** The one primary a question can have, on the session header of a session waiting on the reader. */
  readonly primary?: boolean;
}

/* A successful response is one boolean. A declined lookup, an unknown session and a command
   that failed are the same `false` to a caller by contract, so the declined
   wording covers all three. SENT and not RAISED: the boolean is the raise
   command's own exit status, and a socket raise can change what a tmux client
   shows without bringing a GUI window forward. The ceiling wording names neither
   arm, because the server refuses on two and the page cannot tell which. */
const SAID: Record<Exclude<CueState, 'copied' | object>, string> = {
  sending: 'Raise requested',
  sent: 'Raise sent; the terminal switched to this session. Its window may still be behind others.',
  declined: 'No terminal was raised',
  throttled: 'Raise refused: another raise was too recent. Try again in a moment.',
  // The capability is minted per run and /api/data needs none, so a restart leaves a board rendering
  // fresh rows above a control that can only be refused; a reload is the whole remedy.
  stale: 'Raise refused: the dashboard restarted. Reload the page.',
  failed: 'Raise could not be sent',
};

function sentence(state: Exclude<CueState, 'copied'>): string {
  return typeof state === 'object' ? state.message : SAID[state];
}

function isRaiseCue(state: CueState | undefined): state is Exclude<CueState, 'copied'> {
  return state !== undefined && state !== 'copied';
}

/* Explicit, capability-bound and deduplicated. A press goes through the runtime's
   `focus`, which sends nothing for an empty identity or capability and answers a
   second press locally as throttled; the busy flag is page-wide because the
   daemon's refusal is one flag for the process, so painting the pressed row alone
   would attribute a page-wide condition to whichever row was clicked. `aria-disabled`
   and never `disabled`, which would drop focus from the control just pressed. */
export function RaiseControl({ harness, sid, focusable, primary = false }: RaiseControlProps) {
  const controls = useControls();
  const busy = useValueStore(controls.raiseBusy);
  const key = laneKey('raise', harness, sid);
  const raw = useKeyedValue(controls.cues, key);
  const state = isRaiseCue(raw) ? raw : undefined;
  const cueId = useId();
  const identity = exactIdentity({ harness, sid });
  const { focus } = controls;
  if (!focusable || !identity || !focus) return null;

  const say = (outcome: Exclude<CueState, 'copied'>, press: number) => {
    controls.cues.remember(key, outcome);
    controls.announce(`raise:${harness}:${sid}#${String(press)}`, sentence(outcome));
  };

  const press = async () => {
    const number = controls.press();
    if (controls.raiseBusy.get()) {
      say('throttled', number);
      return;
    }
    controls.raiseBusy.set(true);
    say('sending', number);
    let outcome: FocusOutcome;
    try {
      outcome = await focus(identity);
    } catch {
      outcome = 'failed';
    }
    controls.raiseBusy.set(false);
    // An absent capability or identity is the feature being off: nothing was sent, so nothing is reported.
    if (outcome === 'unavailable') controls.cues.forget(key);
    else say(outcome, number);
  };

  return (
    <>
      <Button
        type="button"
        variant={primary ? 'raise-primary' : 'raise'}
        data-control="raise"
        aria-label="Raise the terminal this session is running in"
        {...(state
          ? {
              'data-raise-state': typeof state === 'object' ? state.state : state,
              'aria-describedby': cueId,
            }
          : {})}
        {...(busy ? { 'aria-disabled': true } : {})}
        onClick={() => void press()}
      >
        <span aria-hidden="true">RAISE</span>
      </Button>
      {state ? (
        <span id={cueId} className="ctl-visually-hidden">
          {sentence(state)}
        </span>
      ) : null}
    </>
  );
}

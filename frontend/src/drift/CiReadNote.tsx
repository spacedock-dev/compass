import { datedClock } from '../observed/values';
import { ActionButton } from '../intent/ActionButton';
import { ciReadAnswer } from './actions';
import { ciReadNote } from './ciRead';
import { useDrift } from './context';
import { CI_READ_LABEL, CI_SWITCH_FLAG, CI_SWITCH_OFF, CI_SWITCH_ON } from './sentences';

/* Under the goal verdict note, from the reading's own record. Absent where no pull request was bound or the
   reader turned the read off, which is no claim either way. */
export function CiReadNote() {
  const { ctx, model } = useDrift();
  const ci = model.shape?.ci ?? null;
  if (!ci) return null;
  const note = ciReadNote(ci, datedClock(ci.read_at, ctx.shell.clock.now() / 1000));
  return (
    <div
      className="next-session-drift-limit"
      data-next-ci-read
      data-next-ci-read-state={note.state}
    >
      <p>
        <strong>{`${CI_READ_LABEL}:`}</strong> {note.lines.join(' ')}
      </p>
    </div>
  );
}

/* The page's switch for the read, beside the notice that names it. The route says which of three states
   holds; `flag-off` is the run's own `--no-ci-read`, which this switch cannot lift and so does not offer. An
   older server's route carries no state, and then there is nothing to switch. */
export function CiReadSwitch() {
  const { ctx, model } = useDrift();
  const state = String(model.route?.['ci_read'] ?? '');
  if (!['on', 'off', 'flag-off'].includes(state)) return null;
  const message = ctx.intent.held.requests.get(`ci-read:${model.key}`)?.message ?? '';
  const on = state === 'on';
  return (
    <p className="next-cockpit-reading-why" data-next-ci-switch={state}>
      <span>{on ? CI_SWITCH_ON : state === 'off' ? CI_SWITCH_OFF : CI_SWITCH_FLAG}</span>
      {state === 'flag-off' ? null : (
        <ActionButton
          weight="secondary"
          label={on ? 'Turn off the GitHub read' : 'Turn on the GitHub read'}
          busyLabel="Saving…"
          pendingKey={`ci-read:${model.key}`}
          action={on ? 'ci-read-off' : 'ci-read-on'}
          focusKey={`ci-read:${model.key}`}
          onPress={() => {
            void ciReadAnswer(ctx, model.identity, !on);
          }}
        />
      )}
      {message ? <span role="status">{message}</span> : null}
    </p>
  );
}

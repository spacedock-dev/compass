import { datedClock } from '../observed/values';
import { ActionButton } from '../intent/ActionButton';
import { ciReadAnswer } from './actions';
import { ciReadNote } from './ciRead';
import { useDrift } from './context';
import { ciProvider, ciReadLabel, CI_SWITCH_FLAG, CI_SWITCH_OFF, CI_SWITCH_ON } from './sentences';

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
        <strong>{`${ciReadLabel(ciProvider(ci.repository))}:`}</strong> {note.lines.join(' ')}
      </p>
    </div>
  );
}

/* The page's switch for the read, beside the notice that names it. The route says which of three states
   holds; `flag-off` is the run's own `--no-ci-read`, which this switch cannot lift and so does not offer. An
   older server's route carries no state, and then there is nothing to switch. */
export function CiReadSwitch({ technical = false }: { readonly technical?: boolean }) {
  const { ctx, model } = useDrift();
  const state = String(model.route?.['ci_read'] ?? '');
  if (!['on', 'off', 'flag-off'].includes(state)) return null;
  const message = ctx.intent.held.requests.get(`ci-read:${model.key}`)?.message ?? '';
  const on = state === 'on';
  const focusKey = `${technical ? 'technical-ci-read' : 'ci-read'}:${model.key}`;
  return (
    <div
      className={technical ? 'flex flex-col items-start gap-1' : 'next-cockpit-reading-why'}
      data-next-ci-switch={state}
    >
      <span className={technical ? 'order-last text-label text-muted-foreground' : undefined}>
        {on ? CI_SWITCH_ON : state === 'off' ? CI_SWITCH_OFF : CI_SWITCH_FLAG}
      </span>
      {state === 'flag-off' ? null : (
        <ActionButton
          weight="secondary"
          label={
            technical
              ? on
                ? 'Stop pull request reads'
                : 'Allow pull request reads'
              : on
                ? 'Turn off the pull request read'
                : 'Turn on the pull request read'
          }
          busyLabel="Saving…"
          pendingKey={`ci-read:${model.key}`}
          action={on ? 'ci-read-off' : 'ci-read-on'}
          focusKey={focusKey}
          onPress={() => {
            void ciReadAnswer(ctx, model.identity, !on, focusKey);
          }}
        />
      )}
      {message ? <span role="status">{message}</span> : null}
    </div>
  );
}

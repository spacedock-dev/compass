import { datedClock } from '../observed/values';
import { ciReadNote } from './ciRead';
import { RouteLink } from '../shell/RouteLink';
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

/* The disclosure describes this route's answer. Settings owns the shared preference. */
export function CiReadSettingNote({ technical = false }: { readonly technical?: boolean }) {
  const { model } = useDrift();
  const state = model.route?.['ci_read'];
  if (state !== 'on' && state !== 'off' && state !== 'flag-off') return null;
  return (
    <div
      className={technical ? 'text-label text-muted-foreground' : 'next-cockpit-reading-why'}
      data-next-ci-switch={state}
    >
      <p className="m-0">
        {state === 'on' ? CI_SWITCH_ON : state === 'off' ? CI_SWITCH_OFF : CI_SWITCH_FLAG}
      </p>
      {technical && state !== 'flag-off' ? (
        <RouteLink route={{ view: 'settings' }}>Read pull request status in Settings</RouteLink>
      ) : null}
    </div>
  );
}

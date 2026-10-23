import { datedClock } from '../observed/values';
import { harnessLabels } from '../sessions/rows';
import { useDrift } from './context';
import { harnessGaveUp, harnessVerdict, verdictNote } from './goalVerdict';
import { GOAL_GAVE_UP_LINE, GOAL_VERDICT_LABEL, goalGaveUpClaim } from './sentences';

/* The card's own margin class rather than the Intent reading's: that one carries a measure and no inset, so
   the note hung left of the level above it and stopped short of the criteria rows below it.

   What the harness decided about the goal, under the Drift level it does not move. Drawn from the row alone, so
   a session with a verdict and no analysis still says it, and always as the harness's claim; where a reading
   tested it, Compass's answer follows in Compass's own words. */
export function GoalVerdictNote() {
  const { ctx, model } = useDrift();
  const verdict = harnessVerdict(model.session);
  const gaveUp = harnessGaveUp(model.session);
  const harness = harnessLabels(model.payload).get(model.harness) || 'Claude Code';
  if (!verdict && gaveUp) {
    return (
      <div className="next-session-drift-limit" data-next-goal-gave-up>
        <p>
          <strong>{GOAL_VERDICT_LABEL}</strong>{' '}
          {goalGaveUpClaim(harness, datedClock(gaveUp.at, ctx.shell.clock.now() / 1000))}{' '}
          {GOAL_GAVE_UP_LINE}
        </p>
        {gaveUp.reason ? <p>{`Its reason: “${gaveUp.reason}”`}</p> : null}
      </div>
    );
  }
  if (!verdict) return null;
  const changed = model.shape?.goalVerdict?.changed_at ?? null;
  const note = verdictNote({
    verdict,
    analyzed: model.raw !== null,
    shape: model.shape,
    harness,
    clock: datedClock(verdict.at, ctx.shell.clock.now() / 1000),
    changedClock: changed ? datedClock(changed, ctx.shell.clock.now() / 1000) : '',
  });
  return (
    <div
      className="next-session-drift-limit"
      data-next-goal-verdict
      data-next-goal-verdict-state={note.state}
    >
      <p>
        <strong>{note.label}</strong> {note.claim} {note.line}
      </p>
      {note.reason ? <p>{`Its reason: “${note.reason}”`}</p> : null}
    </div>
  );
}

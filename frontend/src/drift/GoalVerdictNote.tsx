import { datedClock } from '../observed/values';
import { harnessLabels } from '../sessions/rows';
import { useDrift } from './context';
import { harnessVerdict, verdictNote } from './goalVerdict';

/* What the harness decided about the goal, under the Drift level it does not move. Drawn from the row alone, so
   a session with a verdict and no analysis still says it, and always as the harness's claim; where a reading
   tested it, Compass's answer follows in Compass's own words. */
export function GoalVerdictNote() {
  const { ctx, model } = useDrift();
  const verdict = harnessVerdict(model.session);
  if (!verdict) return null;
  const note = verdictNote({
    verdict,
    analyzed: model.raw !== null,
    shape: model.shape,
    harness: harnessLabels(model.payload).get(model.harness) || 'Claude Code',
    clock: datedClock(verdict.at, ctx.shell.clock.now() / 1000),
  });
  return (
    <div
      className="next-cockpit-reading-why"
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

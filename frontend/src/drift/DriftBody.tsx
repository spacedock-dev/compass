import { LiveMonitorNote } from './LiveMonitorNote';
import { UnaskedPermission } from './UnaskedPermission';
import { DirectionQuestion } from '../intent/DirectionQuestion';
import { nextNumber } from '../api/bootstrap';
import { datedClock } from '../observed/values';
import { useDrift } from './context';
import { steerOffer, steerWithheld } from './correction';
import { ProgressAnswer } from './DriftLevelView';
import { ReadingControl } from './ReadingControl';
import { ReadingResult, ResultFoot } from './ReadingResult';
import { routeRefusal } from './route';
import { steerFrom } from './sentences';
import { SteerBox, SteerButton, SteerSection, UpdateGoalButton } from './SteerBack';
import { resultStale } from './result';
import { useFollowCorrection } from './useFollowCorrection';
import { useRunBoard } from './useRunBoard';

export function DriftBody({ primary }: { readonly primary: boolean }) {
  const { ctx, model } = useDrift();
  const { session, payload, annotation, key, annotate, shape, raw, job } = model;
  const { board, refusal } = useRunBoard(true);
  const offered = steerOffer({
    session,
    annotation,
    source: model.source,
    shape,
    annotate,
    drafted: model.drafted,
  });
  const stale =
    raw && shape && annotation ? resultStale(shape, raw, annotation, model.entries) : null;
  const steerable = offered?.departed && model.harness !== 'codex' ? offered : null;
  useFollowCorrection(steerable !== null);
  const readAt = nextNumber(raw?.['read_at']);
  const from =
    steerable && readAt !== null && readAt > 0
      ? steerFrom(datedClock(readAt, ctx.shell.clock.now() / 1000))
      : '';
  const readable = annotate && raw && shape && !shape.malformed;
  const feedback = readable ? <ResultFoot /> : null;
  const steerLimit =
    readable && !steerable && !job
      ? steerWithheld({
          session,
          annotation,
          shape,
          offer: offered,
          canRetry: !routeRefusal(payload, session),
        })
      : '';
  return (
    <div className="contents" data-next-drift-body>
      {job ? (
        <div className="next-session-drift-check">
          <ReadingControl board={board} refusalOf={refusal} />
        </div>
      ) : null}
      <div
        className="grid gap-3"
        {...(job && readable
          ? { inert: true, 'aria-busy': true, 'data-next-result-dimmed': '' }
          : {})}
      >
        <ProgressAnswer focus={Boolean(readable && !job && !stale && !model.unsettled)} />
        {readable && !stale ? <ReadingResult /> : null}
        {readable || steerable ? (
          <SteerSection
            buttons={
              <div className="flex flex-wrap items-center gap-2">
                {steerable ? (
                  <>
                    <SteerButton primary={primary && !model.unsettled} />
                    <UpdateGoalButton />
                  </>
                ) : null}
                {feedback}
              </div>
            }
            box={steerable ? <SteerBox from={from} /> : null}
          />
        ) : null}
      </div>
      <div className="next-session-drift-check">
        {annotate && (!job || !readable) ? <DirectionQuestion primary={primary} /> : null}
        {!job ? <ReadingControl board={board} refusalOf={refusal} /> : null}
        {steerLimit ? (
          <p className="next-cockpit-reading-why" data-next-steer-off>
            {steerLimit}
          </p>
        ) : null}
      </div>
      <LiveMonitorNote />
      <UnaskedPermission key={key} payload={payload} session={session} />
    </div>
  );
}

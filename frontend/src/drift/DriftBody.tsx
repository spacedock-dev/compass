import { LiveMonitorNote } from './LiveMonitorNote';
import { UnaskedPermission } from './UnaskedPermission';
import { DirectionQuestion } from '../intent/DirectionQuestion';
import { nextNumber } from '../api/bootstrap';
import { datedClock } from '../observed/values';
import { useDrift } from './context';
import { steerOffer, steerWithheld } from './correction';
import { CheckProgressPress, ProgressDisclosure } from './DriftStamp';
import { ProgressAnswer } from './DriftLevelView';
import { ReadingControl } from './ReadingControl';
import { ReadingResult, ResultFoot } from './ReadingResult';
import { checkProgressShown, routeRefusal } from './route';
import { steerFrom } from './sentences';
import { SteerBox, SteerButton, SteerSection, UpdateGoalButton } from './SteerBack';
import { useFollowCorrection } from './useFollowCorrection';
import { useRunBoard } from './useRunBoard';

export function DriftBody({ primary }: { readonly primary: boolean }) {
  const { ctx, model } = useDrift();
  const { session, payload, annotation, key, annotate, shape, raw, job, stale } = model;
  const { board, refusal } = useRunBoard(true);
  const press = checkProgressShown(model);
  const offered = steerOffer({
    session,
    annotation,
    source: model.source,
    shape,
    annotate,
    drafted: model.drafted,
  });
  const steerable = Boolean(offered?.departed && (!stale || stale.kind === 'work'));
  const historical = Boolean(stale) || model.latestCheckWithheld;
  const held = ctx.drift.corrections.get(key);
  const keepEdited = Boolean(held?.open && held.edited);
  useFollowCorrection(steerable);
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
          offer: null,
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
        {readable && (!stale || (stale.kind === 'work' && steerable)) ? (
          <ReadingResult historical={historical} />
        ) : null}
        {readable || steerable || keepEdited ? (
          <SteerSection
            hasCorrection={steerable || keepEdited}
            buttons={
              <div className="flex flex-wrap items-center gap-2">
                {steerable ? (
                  <>
                    <SteerButton primary={primary && !model.unsettled && !historical} />
                    <UpdateGoalButton />
                  </>
                ) : null}
                {feedback}
              </div>
            }
            box={steerable || keepEdited ? <SteerBox from={from} canRecompose={steerable} /> : null}
          />
        ) : null}
      </div>
      <div className="next-session-drift-check">
        {annotate && (!job || !readable) ? <DirectionQuestion primary={primary} /> : null}
        {/* The header's press, again here beside the answer it fills: the same component, board and gating, so
            Not checked yet always sits next to the way to check (owner, 2026-11-24). The card's own primary
            stays its own: a later direction's question, Steer back, or a raise while the session waits. */}
        {press.shown ? (
          /* Room above and below, as the canvas spaces the card's button rows (owner, 2026-11-24): the press
             sat 4px under the explanation and read as cramped. */
          <div className="flex flex-col items-start gap-1.5 pt-4 pb-2" data-next-drift-card-press>
            <CheckProgressPress
              board={board}
              inCard
              primary={primary && !model.unsettled && !press.again}
            />
          </div>
        ) : null}
        {!job ? <ReadingControl board={board} refusalOf={refusal} /> : null}
        {steerLimit ? (
          <p className="next-cockpit-reading-why" data-next-steer-off>
            {steerLimit}
          </p>
        ) : null}
        <ProgressDisclosure />
      </div>
      <LiveMonitorNote />
      <UnaskedPermission key={key} payload={payload} session={session} />
    </div>
  );
}

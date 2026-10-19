import type { ReactNode } from 'react';
import { DirectionQuestion } from '../intent/DirectionQuestion';
import { endedAt } from '../observed';
import { directionsOpen, intentKey, intentUnsaved } from '../intent/derive';
import type { DirectionReading } from '../intent/directions';
import { useDisplayed } from '../shell/context';
import { keepReading } from './actions';
import { useDrift } from './context';
import { offeredDirection, steerOffer, steerTrigger, type SteerOffer } from './correction';
import { DriftLevelView } from './DriftLevelView';
import { readingBoard } from './flip';
import {
  DISCLOSURE_ID,
  DisclosureParts,
  ReadingControl,
  ReadingCount,
  REFUSED_ID,
  JobBox,
  TurnOff,
  ReadingNotice,
  ReadingsOffAsk,
  type SteerSlot,
} from './ReadingControl';
import { useNoticeShown } from './notice';
import { ReadingResult } from './ReadingResult';
import { disclosureParts, promptReadingRefusal, routeRefusal, readingsOff } from './route';
import {
  absenceAttr,
  READINGS_OFF,
  OFFER,
  READING_DEFINITION,
  SCOPE,
  UNKNOWN_KEY,
} from './sentences';
import { SteerBox, SteerButton, UpdateIntentButton } from './SteerBack';
import { useFollowCorrection } from './useFollowCorrection';
import { Why } from './Why';
import { READING_NOT_A_VERIFICATION } from '../intent/logModel';

/* The Drift section's body, in the page's order: the level, the one control (or the question before it, or the
   result that stands in its place), what analysis does, what the session launched, and a reading this build
   could not read. Everything here is drawn from the payload and the reader's held state; a press sends, and
   nothing else does. The legacy page's `nextCockpitDriftBlock` and `nextCockpitReadingParts` are the oracle,
   and `drift-parity.mjs` draws both over one board. */

/* A claim alone is a question and always secondary, including without a reader. */
function steerPrimary(offer: SteerOffer | null, noReader: boolean, primary: boolean): boolean {
  return Boolean(primary && offer && (offer.departed || (offer.failed && noReader)));
}

export function DriftBody({ primary }: { readonly primary: boolean }) {
  const { ctx, model } = useDrift();
  const { session, payload, annotation, key, annotate, shape } = model;
  const held = ctx.intent.held;
  /* One more pass of the drawn card: an entry the flip ledger last saw two passes ago was not drawn between. */
  const epoch = ctx.drift.nextEpoch();
  const saving = useDisplayed((snapshot) =>
    snapshot.pending.includes(`${intentKey(session)}:save`),
  );
  const request = held.requests.get(key);
  const now = ctx.shell.clock.now();
  const refusalInput = { input: model.input, saving, answered: request, nowMs: now };
  const refusal = promptReadingRefusal(refusalInput);
  const heldLive = promptReadingRefusal(refusalInput, true);
  const board = readingBoard(ctx, {
    session,
    reason: refusal,
    heldLive,
    payload: model.base,
    epoch,
    request,
  });
  const pending = annotate ? directionsOpen(model.input, model.source) : [];
  const hasQuestion = pending.length > 0;
  const steerable = steerOffer({
    session,
    annotation,
    source: model.source,
    shape,
    annotate,
    drafted: model.drafted,
  });
  useFollowCorrection(steerable !== null);
  const offer = hasQuestion ? null : steerable;
  const departed = Boolean(offer?.departed);
  const noReader = annotate ? routeRefusal(payload, session) : '';
  const slotted: SteerSlot | null = offer
    ? {
        lead: departed,
        button: (
          <>
            <SteerButton primary={steerPrimary(offer, Boolean(noReader), primary)} />
            {departed ? (
              <UpdateIntentButton
                factId={offeredDirection(annotation, model.entries, session, shape, model.draft)}
              />
            ) : null}
          </>
        ),
        box: (
          <>
            <TriggerLine offer={offer} />
            <SteerBox />
          </>
        ),
      }
    : null;
  /* Said once. The send disclosure already ends on the server's "never a verification that the work was
     done", so the page's own wording rides with what a reading is only where no disclosure was published. */
  const raw = model.raw;
  const about = raw
    ? ''
    : model.route?.['provider'] && model.route['disclosure']
      ? SCOPE
      : `${OFFER} ${READING_NOT_A_VERIFICATION}`;
  const job = model.job;
  const control = hasQuestion ? <QuestionWithAnalysis board={board} primary={primary} /> : null;
  let area: ReactNode;
  if (!annotate) {
    area = (
      <div className="next-session-drift-check">
        <ReadingControl board={board} primary={primary} refusalOf={refusal} />
      </div>
    );
  } else if (raw && shape && !shape.malformed && !job) {
    area = (
      <ReadingResult
        question={control}
        slotted={slotted}
        again={(steer, showRun = true) => (
          <ReadingControl
            board={board}
            primary={false}
            again
            showRun={showRun}
            steer={steer}
            refusalOf={refusal}
          />
        )}
      />
    );
  } else {
    area = (
      <div className="next-session-drift-check">
        {control ?? (
          <ReadingControl
            board={board}
            primary={primary && !departed}
            steer={slotted}
            about={about}
            refusalOf={refusal}
          />
        )}
      </div>
    );
  }
  return (
    <>
      {hasQuestion ? area : null}
      <DriftLevelView />
      {hasQuestion ? null : area}
      <ReadingSection />
    </>
  );
}

function TriggerLine({ offer }: { readonly offer: SteerOffer }) {
  const { model } = useDrift();
  const text = steerTrigger({
    offer,
    shape: model.shape,
    session: model.session,
    entries: model.entries,
    numbers: model.numbers,
    scan: model.source.scan,
    generated: model.generated,
  });
  return text ? <p className="next-cockpit-reading-why">{text}</p> : null;
}

/* The question before the press, in the Analyze control's place while a later direction is unsettled: Keep is
   then the stage's one primary. The question is the Intent step's; this adds the Analyze step's side of it: the
   reading Keep may start, the box a running analysis draws above it, Turn off readings beside it, and the
   disclosure, the count and the refusal under it. */
function QuestionWithAnalysis({
  board,
  primary,
}: {
  readonly board: ReturnType<typeof readingBoard>;
  readonly primary: boolean;
}) {
  const { ctx, model } = useDrift();
  const { session, annotation, route, identity, job } = model;
  const edited = intentUnsaved(model.input);
  const off = readingsOff(model.payload);
  const reason = off ? READINGS_OFF : board.reason;
  const provider = route?.['provider'] ? String(route['provider']) : '';
  const disclosure = provider && route?.['disclosure'] ? String(route['disclosure']) : '';
  const receiver = String(route?.['label'] || provider);
  const analyze = !edited && !reason && !job;
  const request = ctx.intent.held.requests.get(model.key);
  const noticeShown = useNoticeShown();
  const count = Number(annotation?.['reading_count']) || 0;
  const running = endedAt(session) === null && session['state'] !== 'idle';
  const reading: DirectionReading = {
    reason,
    job: Boolean(job),
    ...(disclosure ? { disclosureId: DISCLOSURE_ID } : {}),
    start: (request2) => {
      if (!identity) throw new Error('no identity');
      return keepReading(ctx, identity, request2);
    },
  };
  return (
    <DirectionQuestion
      reading={reading}
      primary={primary}
      before={job ? <JobBox job={job} running={running} /> : null}
      after={
        off ? (
          <ReadingsOffAsk refusedId={!edited} />
        ) : (
          <>
            <ReadingNotice />
            {board.changed ? (
              <p className="next-cockpit-reading-why next-cockpit-reading-change">
                {board.changed}
              </p>
            ) : null}
            {analyze && disclosure ? (
              /* The notice and this popover share the server's disclosure words. */
              <Why
                name="reading-sent"
                pop
                summary={
                  route?.['fallback'] === true || route?.['notice_due'] === true
                    ? `What is sent to ${receiver}`
                    : 'What is sent'
                }
              >
                <DisclosureParts
                  parts={disclosureParts(route, provider, disclosure)}
                  id={DISCLOSURE_ID}
                />
                <TurnOff />
              </Why>
            ) : noticeShown ? null : (
              <TurnOff />
            )}
            {annotation ? <ReadingCount count={count} /> : null}
            {!edited && reason ? <RefusedLine board={board} request={request} /> : null}
          </>
        )
      }
    />
  );
}

function RefusedLine({
  board,
  request,
}: {
  readonly board: ReturnType<typeof readingBoard>;
  readonly request:
    | { readonly refusal?: boolean | undefined; readonly announced?: boolean | undefined }
    | undefined;
}) {
  const { model } = useDrift();
  return (
    <>
      <p
        className="next-cockpit-reading-why"
        id={REFUSED_ID}
        {...(request?.refusal && !request.announced ? { role: 'status' } : {})}
        {...absenceAttr(board.reason)}
      >
        {board.settling ? <span className="next-wait-dot" aria-hidden="true" /> : null}
        {board.reason}
      </p>
      {board.inert && board.pressed ? (
        <Why
          name={`reading-why:${model.key}`}
          summary="Why it can't read"
          body={String(board.pressed['sentence'] || '')}
        />
      ) : null}
    </>
  );
}

/* A reading the board could not read is a substitution and never an omission: the block still renders, names
   the field it could not read, and draws no verdict of any kind. A stored reading this build refused on read
   back says so, because the count of readings asked for would otherwise stand above "No reading has been
   made" with the difference unaccounted for. The section is drawn only for these. */
function ReadingSection() {
  const { model } = useDrift();
  const { annotate, annotation, raw, shape } = model;
  if (!annotate) return null;
  if (!raw) {
    if (annotation?.['reading_refused'] !== true) return null;
    return (
      <section className="next-cockpit-reading">
        <header>
          <h2>READING</h2>
        </header>
        <p className="next-cockpit-define">{READING_DEFINITION}</p>
        <p className="next-cockpit-reading-why">
          A reading is stored for this session and this build could not read it, so nothing from it
          is shown. Asking again replaces it.
        </p>
      </section>
    );
  }
  if (!shape?.malformed) return null;
  return (
    <section className="next-cockpit-reading">
      <header>
        <h2>READING</h2>
      </header>
      <p className="next-cockpit-define">{READING_DEFINITION}</p>
      <p className="next-cockpit-reading-why">{UNKNOWN_KEY}</p>
      <p className="next-cockpit-reading-why">{`Unrecognised: ${shape.malformed}.`}</p>
    </section>
  );
}

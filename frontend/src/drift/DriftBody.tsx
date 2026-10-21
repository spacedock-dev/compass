import type { ReactNode } from 'react';
import { UnaskedPermission } from './UnaskedPermission';
import { DirectionQuestion } from '../intent/DirectionQuestion';
import { nextNumber } from '../api/bootstrap';
import { endedAt } from '../observed';
import { datedClock } from '../observed/values';
import { directionsOpen, intentUnsaved } from '../intent/derive';
import { useDrift } from './context';
import {
  offeredDirection,
  steerOffer,
  steerTrigger,
  steerWithheld,
  type SteerOffer,
} from './correction';
import { DriftLevelView } from './DriftLevelView';
import type { Board } from './flip';
import {
  ReadingControl,
  RunPress,
  ReadingCount,
  REFUSED_ID,
  JobBox,
  ReadingNotice,
  ReadingsOffAsk,
  WhatIsSent,
  type SteerSlot,
} from './ReadingControl';
import { DriftVerdict, ReadingResult } from './ReadingResult';
import { readingsOff } from './route';
import {
  absenceAttr,
  READINGS_OFF,
  OFFER,
  READING_DEFINITION,
  SCOPE,
  steerFrom,
  UNKNOWN_KEY,
  WHY_OFF,
} from './sentences';
import { CitedText } from './CitedText';
import { SteerBox, SteerButton, UpdateIntentButton } from './SteerBack';
import { resultStale } from './result';
import { useFollowCorrection } from './useFollowCorrection';
import { useRunBoard } from './useRunBoard';
import { Why } from './Why';
import { READING_NOT_A_VERIFICATION } from '../intent/logModel';

/* The Drift section's body, in the page's order: the answer in one sentence, the level, the one control (or the question before it, or the
   result that stands in its place), what analysis does, what the session launched, and a reading this build
   could not read. Everything here is drawn from the payload and the reader's held state; a press sends, and
   nothing else does. The legacy page's `nextCockpitDriftBlock` and `nextCockpitReadingParts` are the oracle,
   and `drift-parity.mjs` draws both over one board. */

export function DriftBody({ primary }: { readonly primary: boolean }) {
  const { ctx, model } = useDrift();
  const { session, payload, annotation, key, annotate, shape } = model;
  const { board, refusal } = useRunBoard(true);
  const pending = annotate ? directionsOpen(model.input, model.source) : [];
  const hasQuestion = pending.length > 0;
  const now = ctx.shell.clock.now();
  const offered = steerOffer({
    session,
    annotation,
    source: model.source,
    shape,
    annotate,
    drafted: model.drafted,
  });
  /* Steer back only where a departure stands behind it: a failed check or a claim the record does not show,
     with no departure from the intent, left it offered over "Not checked yet" and over readings that found
     nothing, with nothing to steer from. The server still composes a correction from them; the page no
     longer offers the press. */
  const steerable = offered?.departed ? offered : null;
  useFollowCorrection(steerable !== null);
  /* While a later direction stands, Steer back stays beside the departures it steers from (owner, 2026-10-20):
     the question owns the primary press, so Steer back is secondary there and offers no Update intent instead,
     which the question's own Add already is. */
  const offer = steerable;
  const readAt = nextNumber(model.raw?.['read_at']);
  const from =
    offer && readAt !== null && readAt > 0 ? steerFrom(datedClock(readAt, now / 1000)) : '';
  const slotted: SteerSlot | null = offer
    ? {
        lead: !hasQuestion,
        button: (
          <div className="flex flex-wrap items-center gap-3">
            <SteerButton primary={!hasQuestion} />
            {!hasQuestion ? (
              <UpdateIntentButton
                factId={offeredDirection(annotation, model.entries, session, shape, model.draft)}
              />
            ) : null}
          </div>
        ),
        box: (
          <>
            <TriggerLine offer={offer} />
            <SteerBox from={from} />
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
  const readable = annotate && Boolean(raw && shape && !shape.malformed);
  /* While an analysis runs over a reading the question waits: its box stands where the progress does. */
  const control =
    hasQuestion && !(readable && job) ? (
      <QuestionWithAnalysis board={board} primary={primary} />
    ) : null;
  const stale = Boolean(
    readable && shape && raw && annotation && resultStale(shape, raw, annotation, model.entries),
  );
  const result =
    readable && raw && shape ? (
      <ReadingResult
        question={control}
        slotted={slotted}
        steerOff={steerWithheld({ session, annotation, shape, offer })}
        again={(steer) => (
          <ReadingControl board={board} primary={false} again steer={steer} refusalOf={refusal} />
        )}
      />
    ) : null;
  const answer = (
    <>
      <DriftVerdict focus={!job && !hasQuestion && !stale} />
      <DriftLevelView />
    </>
  );
  /* The answer first, then the level, in every state: a later direction's question once drew above the level,
     so the verdict moved between visits (usability review, 2026-10-20). A run over a reading keeps that reading
     in view, dimmed and out of reach, under the progress that replaces it, until the new one lands. */
  let area: ReactNode;
  if (!annotate) {
    area = (
      <div className="next-session-drift-check">
        <ReadingControl board={board} primary={primary} refusalOf={refusal} />
      </div>
    );
  } else if (readable && !job) {
    area = result;
  } else if (readable && job) {
    area = (
      <>
        <div className="next-session-drift-check">
          <ReadingControl board={board} primary={false} refusalOf={refusal} />
        </div>
        <div className="flex flex-col opacity-45" aria-busy="true" inert data-next-result-dimmed>
          {answer}
          {result}
        </div>
      </>
    );
  } else {
    area = (
      <div className="next-session-drift-check">
        {control ?? (
          <ReadingControl
            board={board}
            primary={primary}
            steer={slotted}
            about={about}
            refusalOf={refusal}
          />
        )}
      </div>
    );
  }
  return (
    <div className="contents" data-next-drift-body>
      <UnaskedPermission key={key} payload={payload} session={session} />
      {readable && job ? null : answer}
      {area}
      <ReadingSection />
    </div>
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
  return text ? (
    <p className="next-cockpit-reading-why">
      <CitedText text={text} />
    </p>
  ) : null;
}

/* The question before the press, in the Analyze control's place while a later direction is unsettled: Keep is
   then the stage's one primary. The question is the Intent step's; this adds the Analyze step's side of it: the
   reading Keep may start, the box a running analysis draws above it, Pause model calls beside it, and the
   disclosure, the count and the refusal under it. */
function QuestionWithAnalysis({
  board,
  primary,
}: {
  readonly board: Board;
  readonly primary: boolean;
}) {
  const { ctx, model } = useDrift();
  const { session, annotation, route, job } = model;
  /* Over a reading the card's footer draws What is sent, once. */
  const kept = Boolean(model.raw && model.shape && !model.shape.malformed);
  const edited = intentUnsaved(model.input);
  const off = readingsOff(model.payload);
  const reason = off ? READINGS_OFF : board.reason;
  const provider = route?.['provider'] ? String(route['provider']) : '';
  const disclosure = provider && route?.['disclosure'] ? String(route['disclosure']) : '';
  const analyze = !edited && !reason && !job;
  const request = ctx.intent.held.requests.get(model.key);
  const count = Number(annotation?.['reading_count']) || 0;
  const running = endedAt(session) === null && session['state'] !== 'idle';
  return (
    <DirectionQuestion
      primary={primary}
      buttons={
        kept ? null : (
          <RunPress
            board={board}
            weight="secondary"
            label="Analyze drift"
            focusKey={`reading:${model.key}`}
          />
        )
      }
      before={job ? <JobBox job={job} running={running} again={kept} /> : null}
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
            {analyze && disclosure && !kept ? <WhatIsSent /> : null}
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
  readonly board: Board;
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
          summary={WHY_OFF}
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

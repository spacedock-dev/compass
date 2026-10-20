import { SampleBeside } from '../sample/SampleMark';
import { Card } from '../ui/card';
import { useEffect, type ReactNode } from 'react';
import { nextNumber } from '../api/bootstrap';
import { disclosureKey, useFocusKey } from '../controls';
import { ActionButton } from '../intent/ActionButton';
import { endedAt, readHint, type Row } from '../observed';
import { PROMPT_SOURCES } from '../sessions/intent';
import { askForReading, cancelReading, readingOff, readingOn } from './actions';
import { useDrift } from './context';
import type { Board } from './flip';
import {
  readingsOn,
  readingsOff,
  disclosureParts,
  readingJob,
  routeRefusal,
  withheldAge,
} from './route';
import {
  absenceAttr,
  BACKGROUND,
  CANCEL_FAILED,
  JOB_NOTE,
  JOB_NOTE_SO_FAR,
  JOB_TITLE,
  READINGS_OFF,
  MODEL_PAUSE_EXPLANATION,
} from './sentences';
import { Why } from './Why';
import { ModelNotice, DisclosureParts } from './ModelNotice';
import { noticeContentParts, noticeLabel, sessionNotice } from './notice';

/* The Analyze control in all of its states: idle, running, off, refused, and with no reader on
   this machine. Each state is drawn from the payload and the reader's held state alone, and nothing here
   sends a request: a press does, through `actions.ts`. */

export const REFUSED_ID = 'next-cockpit-reading-refused';
export const DISCLOSURE_ID = 'next-cockpit-reading-disclosure';

export { DisclosureParts } from './ModelNotice';

/* The attempt count beside the control, worded the same in every state: short to the eye, and the whole
   sentence to a screen reader, which the short form is hidden from. The store counts drift checks alone
   (`readings`), so it says so: "model requests" read 2 beside four model calls once summaries also ran
   (usability review, 2026-10-20). */
export function ReadingCount({ count }: { readonly count: number }) {
  const short = `${String(count)} drift check${count === 1 ? '' : 's'} requested`;
  return (
    <p className="next-cockpit-reading-count">
      <span aria-hidden="true">{short}</span>
      <span className="next-visually-hidden">{`${short} for this session.`}</span>
    </p>
  );
}

/* Pause model calls, drawn while readings are on. It sits in the Drift card's head in every state
   (`DriftHeadPause`), and in the notice and the "What is sent" popover beside what it stops, so the off
   switch is never only in a part the page did not draw.
   [The More inventory](../../../docs/design-reading-a-session.md#where-everything-in-more-went) */
export function TurnOff({
  closes = '',
  head = false,
}: {
  /** The popover this copy sits in, closed by the press so it does not stay open over a changed card. */
  readonly closes?: string;
  /** The Drift header's copy: the button alone, with its own focus key beside the other copies. */
  readonly head?: boolean;
}) {
  const { ctx, model } = useDrift();
  const off = readingsOff(model.payload);
  if (!off && !readingsOn(model.payload)) return null;
  const action = off ? 'reading-on' : 'reading-off';
  const button = (
    <ActionButton
      weight="secondary"
      label={off ? 'Resume model calls' : 'Pause model calls'}
      busyLabel={off ? 'Resuming…' : 'Pausing…'}
      pendingKey={`${action}:${model.key}`}
      action={action}
      focusKey={head ? `${action}-head:${model.key}` : `${action}:${model.key}`}
      {...(head ? { describes: MODEL_PAUSE_ID } : {})}
      onPress={() => {
        if (closes) {
          ctx.shell.controls.disclosures.set(
            disclosureKey({ project: model.project, scope: model.key, name: closes }),
            false,
          );
        }
        void (off ? readingOn : readingOff)(ctx, model.identity);
      }}
    />
  );
  if (head) {
    return (
      <>
        {button}
        <span id={MODEL_PAUSE_ID} className="next-visually-hidden">
          {MODEL_PAUSE_EXPLANATION}
        </span>
      </>
    );
  }
  return (
    <>
      {button}
      <p className="next-cockpit-reading-why">{MODEL_PAUSE_EXPLANATION}</p>
    </>
  );
}

const MODEL_PAUSE_ID = 'next-session-drift-pause-why';

/* Pause model calls in the Drift card's head, in every state where calls can be paused or resumed: after an
   analysis it was only inside the "What is sent" popover, two presses away from a reader looking for the off
   switch (usability review, 2026-10-20). The copies beside the notice and in the popover stay where they
   explain what they stop. */
export function DriftHeadPause() {
  return <TurnOff head />;
}

/* Each step's state comes from where the published phase sits among them. A finished step is a filled mark,
   never a check mark: a check beside a reading is the shape the ruling keeps off every result. An unknown
   phase marks every step still to come rather than guessing which one is running. The box has no role: it is
   inside a page every revision redraws, so a status role re-announced it on each revision while the job ran.
   Its start and its outcome go once each through the persistent region instead (`trackJobs`). */
export function JobBox({ job, running }: { readonly job: Row; readonly running: boolean }) {
  const { ctx, model } = useDrift();
  const { key } = model;
  const titleRef = useFocusKey<HTMLSpanElement>(ctx.shell.controls.focusLane, `reading:${key}`);
  const steps = Array.isArray(job['steps']) ? (job['steps'] as unknown[]) : [];
  const at = steps.findIndex((step) => Boolean(step) && (step as Row)['phase'] === job['phase']);
  const held = ctx.drift.cancels.get(key);
  const mine = held && held.job === job['id'] ? held : null;
  const finishing = job['cancelling'] === true || Boolean(mine?.pending);
  return (
    <Card
      variant="reading-job"
      className="next-cockpit-reading-job"
      data-next-analyzing={String(job['id'])}
    >
      <div className="next-cockpit-reading-job-head">
        {/* The press button's focus key goes to the title, not to Cancel: on Cancel, a keyboard press
            followed by a second Enter cancelled the analysis it had just started, which is a spent attempt.
            Cancel's own key falls back to the press, so focus lands there again when the box goes. */}
        <span
          ref={titleRef}
          className="next-cockpit-reading-job-title"
          tabIndex={-1}
          data-next-focus={`reading:${key}`}
        >
          {JOB_TITLE}
        </span>
        <ActionButton
          weight="secondary"
          label="Cancel"
          busyLabel="Cancelling…"
          pendingKey={`reading-cancel:${key}`}
          inert={finishing}
          action="reading-cancel"
          focusKey={`reading-cancel:${key}`}
          fallbackKey={`reading:${key}`}
          onPress={() => {
            if (model.identity) void cancelReading(ctx, model.identity);
          }}
        />
      </div>
      <ol className="next-cockpit-reading-steps">
        {steps.map((step, index) => {
          const state = at < 0 || index > at ? 'todo' : index < at ? 'done' : 'active';
          return (
            <li
              // The steps are the server's, in its order, with no ids of their own.
              key={index}
              className="next-cockpit-reading-step"
              data-state={state}
              {...(state === 'active' ? { 'aria-current': 'step' as const } : {})}
            >
              <span className="next-cockpit-reading-step-mark" aria-hidden="true" />
              <span>{String((step as Row | null)?.['text'] || '')}</span>
            </li>
          );
        })}
      </ol>
      <p className="next-cockpit-reading-job-note">{running ? JOB_NOTE_SO_FAR : JOB_NOTE}</p>
      {mine?.failed && !finishing ? (
        <p className="next-cockpit-reading-why">{CANCEL_FAILED}</p>
      ) : null}
    </Card>
  );
}

export interface SteerSlot {
  /** Steer back leads Analyze, as under a departure. */
  readonly lead: boolean;
  readonly button: ReactNode;
  readonly box: ReactNode;
}

export function ReadingControl({
  board,
  primary = true,
  steer = null,
  again = false,
  showRun = true,
  about = '',
  refusalOf,
}: {
  readonly board: Board;
  readonly primary?: boolean;
  readonly steer?: SteerSlot | null;
  readonly again?: boolean;
  readonly showRun?: boolean;
  /** What a reading is, drawn inside "What is sent" while no reading is stored. */
  readonly about?: string;
  /** The refusal as the card computed it before the board's ranking, to drop a stale one. */
  readonly refusalOf: string;
}) {
  const { ctx, model } = useDrift();
  const { session, payload, annotation, key, identity } = model;
  const held = ctx.intent.held;
  const raw = held.requests.get(key);
  /* A refusal is a state, not an event, and it stops being true the moment the reader does what it asks.
     Dropped as soon as that state has gone: one that nothing clears leaves "Nothing has been typed for this
     session" standing under a button that is no longer refused, which is the board asserting an absence after
     it stopped being true. A response is an event and is kept. */
  const stale = Boolean(raw?.refusal) && raw?.message !== refusalOf;
  const request = stale ? (raw?.notice !== undefined ? { notice: raw.notice } : undefined) : raw;
  useEffect(() => {
    if (stale) {
      if (request) held.requests.set(key, request);
      else held.requests.delete(key);
    }
  });
  const { reason, pressed, inert, changed, settling } = board;
  const pending = Boolean(request?.pending);
  const route = model.route;
  const provider = route?.['provider'] ? String(route['provider']) : '';
  const off = readingsOff(payload);
  const busyKey = `reading:${key}`;
  const enabled = !off && !reason && !pending;
  const count = nextNumber(annotation?.['reading_count']) || 0;
  const disclosure = provider && route?.['disclosure'] ? String(route['disclosure']) : '';
  const parts = disclosureParts(route, provider, disclosure);
  const partsList = parts.length ? <DisclosureParts parts={parts} id={DISCLOSURE_ID} /> : null;
  /* What an analysis will read, under the control, and only where a press could read it: a provider, no
     refusal beside it, saved words, and words given before any observed end, which the server withholds by
     the same time the later-direction floor does. */
  const given = nextNumber(
    annotation &&
      (PROMPT_SOURCES.includes(annotation['goal_source'] as string)
        ? annotation['goal_source_at']
        : annotation['at']),
  );
  const ended = endedAt(session);
  const hint =
    provider &&
    !reason &&
    String(annotation?.['goal'] || '').trim() &&
    !(ended !== null && given !== null && given > ended)
      ? readHint(session)
      : '';
  const readLine = hint && !again ? `${hint} ${BACKGROUND}` : '';
  const job = readingJob(payload, session);
  /* Only from a published annotation: with the store off there is no count to read, and "0 requests" would be
     a default standing in for one. */
  const counted = annotation ? <ReadingCount count={count} /> : null;
  /* What the last press or withdrawal came to, announced. Every arm prints it: a failed "Pause model calls"
     that says nothing leaves the reader believing a permission is gone that is still on record. */
  const answered = request?.message && !request.refusal ? String(request.message) : '';
  const said = (text: string): ReactNode =>
    text ? (
      <p
        className="next-cockpit-reading-why"
        {...(request?.announced ? {} : { role: 'status' })}
        {...absenceAttr(text)}
      >
        {text}
      </p>
    ) : null;
  /* While a job runs, the box stands where the button was, with the count after it in the idle order. A
     refusal is about a new press, which is not offered, so it waits. The notice stays under the box because
     the job carries it, so a reload mid-run still says where the words went. */
  if (job) {
    const running = ended === null && session['state'] !== 'idle';
    return (
      <>
        <JobBox job={job} running={running} />
        {said(answered)}
        {counted}
        {off ? said(READINGS_OFF) : null}
        <ReadingNotice />
      </>
    );
  }
  /* No reader on this machine: the route's reason stands where the button would be, and no inert button is
     drawn, because there is no press to refuse. A narrowing of
     [NUI-18](../../../docs/design-next-ui.md#nui-18-one-control-primitive-and-an-inert-control-stays-on-the-page)
     for this one case; every other refusal keeps the inert control and its sentence. `--no-annotations` is one
     of those, so the store's state is checked first. */
  const noReader = model.annotate ? routeRefusal(payload, session) : '';
  const aboutWhy = about ? (
    <Why name="reading-about" summary="What a reading reads" body={about} />
  ) : null;
  const steerButton = steer?.button ?? null;
  const steerBox = steer?.box ?? null;
  const lead = Boolean(steer?.lead);
  if (noReader) {
    return (
      <>
        <div className="next-cockpit-reading-ask next-cockpit-reading-ask--none">
          <NoReader reason={noReader} />
          {off ? <p className="next-cockpit-reading-why">{READINGS_OFF}</p> : null}
          {steerButton}
        </div>
        {steerBox}
        {said(answered === noReader ? '' : answered)}
        {counted}
        {aboutWhy}
      </>
    );
  }
  const described = off ? REFUSED_ID : reason ? REFUSED_ID : disclosure ? DISCLOSURE_ID : '';
  const label = again ? 'Check again' : 'Analyze drift';
  /* A current result keeps its one Analyze. Resume model calls is the Drift card head's, drawn whenever calls
     are paused, so Analyze stays in its place, refused, rather than becoming a second Resume beside it. */
  const press = showRun ? (
    <ActionButton
      weight={primary && provider && !inert && !off ? 'primary' : 'secondary'}
      label={label}
      busyLabel="Starting…"
      pendingKey={busyKey}
      inert={!enabled}
      describes={described}
      action="reading-ask"
      focusKey={`reading:${key}`}
      fallbackKey={`reading:${key}`}
      onPress={() => {
        if (off) return;
        if (identity) {
          void askForReading(ctx, identity, {
            route,
            revision: nextNumber(annotation?.['revision']) || 0,
          });
        }
      }}
    />
  ) : null;
  /* The announcement and the description are one node while a refusal stands. Printing the stored message and
     the reason separately rendered the same sentence twice, adjacent and identical, where the contract is that
     it renders exactly once. The press is still announced, because this node carries `role="status"` when it
     is the refusal. */
  /* Pausing is the reader's durable answer even when another refusal also applies. */
  const refusalText = off ? READINGS_OFF : reason;
  const refused = refusalText ? (
    <>
      <p
        className="next-cockpit-reading-why"
        id={REFUSED_ID}
        {...(request?.refusal && !request.announced ? { role: 'status' } : {})}
        {...absenceAttr(refusalText)}
      >
        {/* Waiting, not busy: the record is settling and Analyze opens by itself at `until`, so a dot pulses
            rather than the press's spinner. */}
        {settling ? <span className="next-wait-dot" aria-hidden="true" /> : null}
        {refusalText}
      </p>
      {inert && pressed ? (
        <Why
          name={`reading-why:${key}`}
          summary="Why it can't read"
          body={String(pressed['sentence'] || '')}
        />
      ) : null}
    </>
  ) : null;
  /* What the last press came to when it was withheld, from the store, so a reload and another tab say the same.
     Not announced here: the job's end already said it once through the persistent region. Left out when the
     inert line above already carries the same sentence. */
  const stored = String(annotation?.['reading_withheld'] || '');
  const age = withheldAge(annotation, model.generated);
  const outcome =
    stored && !(inert && String(pressed?.['sentence'] || '') === stored) ? (
      <p className="next-cockpit-reading-why next-cockpit-reading-outcome">
        {`${age ? `Last analysis, ${age}: ` : 'Last analysis: '}${stored}`}
      </p>
    ) : null;
  /* Every account of a press -- why it cannot run, what the last one came to, what this tab's press was
     answered with -- sits directly under the button's row, before the hint and the disclosure. */
  const accounts = (
    <>
      {refused}
      {said(answered)}
      {outcome}
      {steerBox}
      {readLine ? <p className="next-cockpit-reading-why">{readLine}</p> : null}
    </>
  );
  const changeLine = changed ? (
    <p className="next-cockpit-reading-why next-cockpit-reading-change">{changed}</p>
  ) : null;
  /* Idle: the provider disclosure one click away, in a popover so opening it moves nothing and covers no
     control above it. Its summary names the receiver while a press would record a new notice, and always on
     a fallback route, whose receiver is a second provider. */
  const receiver = provider ? String(route?.['label'] || provider) : '';
  const sent = disclosure ? (
    <Why
      name="reading-sent"
      pop
      summary={
        route?.['fallback'] === true || route?.['notice_due'] === true
          ? `What is sent to ${receiver}`
          : 'What is sent'
      }
    >
      {partsList}
      {about ? <p className="next-cockpit-reading-why">{about}</p> : null}
      {off ? null : <TurnOff closes="reading-sent" />}
    </Why>
  ) : (
    aboutWhy
  );
  return (
    <>
      <div className="next-cockpit-reading-ask">
        {lead ? (
          <>
            {steerButton}
            {press}
          </>
        ) : (
          <>
            {press}
            {steerButton}
          </>
        )}
      </div>
      {off ? <p className="next-cockpit-reading-why">{MODEL_PAUSE_EXPLANATION}</p> : null}
      {changeLine}
      {inert ? null : counted}
      {accounts}
      <ReadingNotice />
      <SampleBeside id="sent">{sent}</SampleBeside>
    </>
  );
}

function NoReader({ reason }: { readonly reason: string }) {
  const { ctx, model } = useDrift();
  /* The reason takes the button's focus key, so a reader whose focus was on Analyze drift when the reader went
     away lands on why, not on the page. */
  const ref = useFocusKey<HTMLParagraphElement>(
    ctx.shell.controls.focusLane,
    `reading:${model.key}`,
  );
  return (
    <p
      ref={ref}
      className="next-cockpit-reading-why"
      tabIndex={-1}
      data-next-focus={`reading:${model.key}`}
      data-next-reading-no-reader
      {...absenceAttr(reason)}
    >
      {reason}
    </p>
  );
}

export function ReadingNotice() {
  const { ctx, model } = useDrift();
  const notice = sessionNotice(ctx.intent.held.requests.get(model.key), model.job);
  if (!notice || readingsOff(model.payload)) return null;
  const route = model.route;
  /* The route's words describe what the route sends now; they stand beside the notice only while the route
     is still the provider the notice was recorded for. */
  const same = String(route?.['provider'] || '') === String(notice['provider'] || '');
  const parts = same
    ? disclosureParts(route, String(route?.['provider'] || ''), String(route?.['disclosure'] || ''))
    : [];
  return (
    <ModelNotice
      notice={notice}
      provider={noticeLabel(notice)}
      parts={parts.length ? parts : noticeContentParts(notice)}
    >
      <TurnOff />
    </ModelNotice>
  );
}

/* Why the question's Keep sends nothing while calls are paused. Resume is the Drift card head's, which stays
   available while an earlier analysis unwinds. The direction question owns its job box and Cancel; this slot
   adds neither again. */
export function ReadingsOffAsk({ refusedId }: { readonly refusedId: boolean }) {
  const { ctx, model } = useDrift();
  const { key } = model;
  const request = ctx.intent.held.requests.get(key);
  const id = refusedId ? REFUSED_ID : undefined;
  const answered = request?.message && !request.refusal ? String(request.message) : '';
  return (
    <>
      <p className="next-cockpit-reading-why">{MODEL_PAUSE_EXPLANATION}</p>
      <p className="next-cockpit-reading-why" id={id} {...absenceAttr(READINGS_OFF)}>
        {READINGS_OFF}
      </p>
      {answered ? (
        <p
          className="next-cockpit-reading-why"
          {...(request?.announced ? {} : { role: 'status' })}
          {...absenceAttr(answered)}
        >
          {answered}
        </p>
      ) : null}
    </>
  );
}

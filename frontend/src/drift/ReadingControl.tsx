import { SampleBeside } from '../sample/SampleMark';
import { Card } from '../ui/card';
import { Button } from '../ui/button';
import { useEffect, type ReactNode } from 'react';
import { nextNumber } from '../api/bootstrap';
import { useFocusKey } from '../controls';
import { ActionButton } from '../intent/ActionButton';
import { endedAt, readHint, type Row } from '../observed';
import { PROMPT_SOURCES } from '../sessions/intent';
import { useDisplayed } from '../shell/context';
import { askForReading, cancelReading, readingNotNow, readingOff } from './actions';
import { useDrift } from './context';
import type { Board } from './flip';
import {
  anyConsent,
  disclosureParts,
  needsAllow,
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
} from './sentences';
import { Why } from './Why';

/* The Analyze control in all of its states: idle, asking for consent, running, refused, and with no reader on
   this machine. Each state is drawn from the payload and the reader's held state alone, and nothing here
   sends a request: a press does, through `actions.ts`. */

export const REFUSED_ID = 'next-cockpit-reading-refused';
export const DISCLOSURE_ID = 'next-cockpit-reading-disclosure';

/* An item that opens with its own label ("Sent:", "To:", "Tool output, only after you allow it:") draws the
   label in weight and the rest after it, so the list reads as a short form to scan rather than as one
   paragraph. The words are the server's, unchanged and in order. */
const PART_LABEL = /^([A-Z][A-Za-z' ,]{1,40}?):\s+(\S[\s\S]*)$/;

export function DisclosureParts({
  parts,
  id,
}: {
  readonly parts: readonly string[];
  readonly id: string;
}) {
  return (
    <ul className="next-cockpit-reading-parts" id={id}>
      {parts.map((part, index) => {
        const labelled = parts.length > 1 ? PART_LABEL.exec(part) : null;
        return (
          <li key={index}>
            {labelled ? (
              <>
                <strong className="font-semibold text-foreground">{`${labelled[1] ?? ''}:`}</strong>
                {` ${labelled[2] ?? ''}`}
              </>
            ) : (
              part
            )}
          </li>
        );
      })}
    </ul>
  );
}

/* The attempt count beside the control, worded the same in every state: short to the eye, and the whole
   sentence to a screen reader, which the short form is hidden from. */
export function ReadingCount({ count }: { readonly count: number }) {
  const short = `${String(count)} model request${count === 1 ? '' : 's'}`;
  return (
    <p className="next-cockpit-reading-count">
      <span aria-hidden="true">{short}</span>
      <span className="next-visually-hidden">{`${short} recorded for this session.`}</span>
    </p>
  );
}

/* Turn off readings, busy state and all, drawn only while some receiver's permission is on record. It sits in
   the "What is sent" popover beside what it stops, and where no popover is drawn (a running job, no reader,
   the consent step, a route with no disclosure) under the control instead, so the off switch is never only in
   a part the page did not draw.
   [The More inventory](../../../docs/design-reading-a-session.md#where-everything-in-more-went) */
export function TurnOff() {
  const { ctx, model } = useDrift();
  if (!anyConsent(model.payload)) return null;
  return (
    <ActionButton
      weight="secondary"
      label="Turn off readings"
      busyLabel="Turning off…"
      pendingKey={`reading-off:${model.key}`}
      action="reading-off"
      focusKey={`reading-off:${model.key}`}
      onPress={() => void readingOff(ctx, model.identity)}
    />
  );
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
  const request = stale ? undefined : raw;
  useEffect(() => {
    if (stale) held.requests.delete(key);
  });
  const { reason, pressed, inert, changed, settling } = board;
  const pending = Boolean(request?.pending);
  const route = model.route;
  const provider = route?.['provider'] ? String(route['provider']) : '';
  const allowKey = `reading-allow:${key}`;
  const allowPending = useDisplayed((snapshot) => snapshot.pending.includes(allowKey));
  /* The question stays drawn while its Allow is being answered: the card is the consent, and taking it away
     mid-press left a bare hatched button. */
  const confirming = Boolean(
    provider && !inert && ((request?.consent && needsAllow(payload, route)) || allowPending),
  );
  const busyKey = confirming ? allowKey : `reading:${key}`;
  const enabled = !reason && !pending;
  const count = nextNumber(annotation?.['reading_count']) || 0;
  /* The route's disclosure, naming this session's own receiver, whose capacity is spent and where the words
     go. It is the owner's ruling where it sits: idle, under the button with the hint; confirming, before
     "Allow and analyze", because that press is the consent. Either way the button is described by it, unless
     a refusal is what describes it. */
  const disclosure = provider && route?.['disclosure'] ? String(route['disclosure']) : '';
  /* The server's own parts, a short list in its order and unreworded: in the consent step, and idle in the
     "What is sent" popover, so the two cannot differ. A route from before the parts were published shows its
     whole disclosure as one item. */
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
  /* What the last press or withdrawal came to, announced. Every arm prints it: a failed "Turn off readings"
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
  /* While a job runs, the box stands where the button was, as the design draws it, with the disclosure and the
     count after it in the idle order. A refusal is about a new press, which is not offered, so it waits. The
     disclosure is not drawn under the box: nothing more is sent by this job, and the reader allowed it, or it
     ran under an Allow, after the same words. */
  if (job) {
    const running = ended === null && session['state'] !== 'idle';
    return (
      <>
        <JobBox job={job} running={running} />
        {said(answered)}
        {counted}
        <TurnOff />
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
          {steerButton}
        </div>
        {steerBox}
        {said(answered === noReader ? '' : answered)}
        {counted}
        {aboutWhy}
        <TurnOff />
      </>
    );
  }
  const described = reason ? REFUSED_ID : disclosure ? DISCLOSURE_ID : '';
  const label = confirming ? 'Allow and analyze' : again ? 'Analyze again' : 'Analyze drift';
  const press = showRun ? (
    <ActionButton
      weight={primary && provider && !inert ? 'primary' : 'secondary'}
      label={label}
      busyLabel="Starting…"
      pendingKey={busyKey}
      inert={!enabled}
      describes={described}
      action={confirming ? 'reading-allow' : 'reading-ask'}
      focusKey={confirming ? allowKey : `reading:${key}`}
      {...(confirming ? { fallbackKey: `reading:${key}` } : {})}
      onPress={() => {
        if (identity) {
          void askForReading(ctx, identity, confirming, {
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
  const refused = reason ? (
    <>
      <p
        className="next-cockpit-reading-why"
        id={REFUSED_ID}
        {...(request?.refusal && !request.announced ? { role: 'status' } : {})}
        {...absenceAttr(reason)}
      >
        {/* Waiting, not busy: the record is settling and Analyze opens by itself at `until`, so a dot pulses
            rather than the press's spinner. */}
        {settling ? <span className="next-wait-dot" aria-hidden="true" /> : null}
        {reason}
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
  if (confirming) {
    /* The consent step stands in the button's slot: a question naming the receiver, the disclosure's parts in
       view, then the press that is the consent and the way out. The heading takes the press's focus key, as the
       job box's title does, so focus lands on the question rather than on Allow, and a second Enter or the
       rest of a double-click cannot give consent unread. */
    const receiver = String(route?.['label'] || provider);
    const steers = steerButton ? (
      <div className="next-cockpit-reading-ask">{steerButton}</div>
    ) : null;
    /* The server's line when an Allow is on record that no longer covers where the words go, so the step says
       why it is asking again. Never composed here: only the store knows it was given. */
    const policy = payload['reading'];
    const rebindMap = policy && typeof policy === 'object' ? (policy as Row)['rebind'] : null;
    const rebind =
      rebindMap && typeof rebindMap === 'object' ? String((rebindMap as Row)[provider] || '') : '';
    return (
      <>
        {lead ? steers : null}
        <ConsentCard
          receiver={receiver}
          rebind={rebind}
          partsList={partsList}
          press={press}
          allowBusy={allowPending || pending}
          onNotNow={() => {
            if (identity) readingNotNow(ctx, identity);
          }}
        />
        {changeLine}
        {lead ? null : steers}
        {accounts}
        {counted}
        {aboutWhy}
        <TurnOff />
      </>
    );
  }
  /* Idle: the button and its count, the accounts and the one hint line, then the provider disclosure one click
     away under a worded summary that names the receiver until it is allowed, and always on a fallback route,
     whose receiver is a second provider that an Allow given on another harness's session lets a press reach at
     once. Idle sends nothing: the press that would send either opens the consent step above or runs under an
     Allow given after these same words. A popover, so the body is taken out of flow under its summary and
     opening it moves nothing and covers no control above it. */
  const receiver = provider ? String(route?.['label'] || provider) : '';
  const sent = disclosure ? (
    <Why
      name="reading-sent"
      pop
      summary={
        route?.['fallback'] === true || needsAllow(payload, route)
          ? `What is sent to ${receiver}`
          : 'What is sent'
      }
    >
      {partsList}
      {about ? <p className="next-cockpit-reading-why">{about}</p> : null}
      <TurnOff />
    </Why>
  ) : (
    <>
      {aboutWhy}
      <TurnOff />
    </>
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
      {changeLine}
      {inert ? null : counted}
      {accounts}
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

function ConsentCard({
  receiver,
  rebind,
  partsList,
  press,
  allowBusy,
  onNotNow,
}: {
  readonly receiver: string;
  readonly rebind: string;
  readonly partsList: ReactNode;
  readonly press: ReactNode;
  readonly allowBusy: boolean;
  readonly onNotNow: () => void;
}) {
  const { ctx, model } = useDrift();
  const titleRef = useFocusKey<HTMLHeadingElement>(
    ctx.shell.controls.focusLane,
    `reading:${model.key}`,
  );
  const notNowRef = useFocusKey<HTMLButtonElement>(
    ctx.shell.controls.focusLane,
    `reading-not-now:${model.key}`,
    { fallback: `reading:${model.key}` },
  );
  return (
    <Card
      variant="reading-consent"
      className="next-cockpit-reading-consent"
      role="group"
      aria-labelledby="next-cockpit-reading-consent-title"
    >
      <h3
        ref={titleRef}
        className="next-cockpit-reading-consent-title"
        id="next-cockpit-reading-consent-title"
        tabIndex={-1}
        data-next-focus={`reading:${model.key}`}
      >
        {`Send this session to ${receiver} for analysis?`}
      </h3>
      {rebind ? <p className="next-cockpit-reading-why">{rebind}</p> : null}
      {partsList}
      <div className="next-cockpit-reading-ask">
        {press}
        <Button
          ref={notNowRef}
          type="button"
          data-next-cockpit-action="reading-not-now"
          data-next-focus={`reading-not-now:${model.key}`}
          {...(allowBusy ? { 'aria-disabled': true } : {})}
          onClick={(event) => {
            event.preventDefault();
            onNotNow();
          }}
        >
          Not now
        </Button>
      </div>
    </Card>
  );
}

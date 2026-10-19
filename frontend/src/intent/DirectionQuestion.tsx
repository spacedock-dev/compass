import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from '../ui/select';
import { Label } from '../ui/label';
import { useEffect, type ReactNode } from 'react';
import { compatSessKey } from '../api/identity';
import { useFocusKey } from '../controls';
import { clock } from '../observed';
import { useDisplayed } from '../shell/context';
import { DirectionActionButton } from './DirectionActionButton';
import { DirectionGoalButton } from './OutcomeLines';
import {
  directionSelected,
  directionsOpen,
  editedRefusal,
  intentDraft,
  intentKey,
  intentUnsaved,
  PROMPT_CHOSEN,
} from './derive';
import { keepIntent, openDirection, type DirectionReading } from './directions';
import { pickDirection } from './edit';
import { ADD_DIRECTION, DIRECTION_CLIPPED, KEEP, KEEP_ANALYZE } from './sentences';
import { entryNumbers, type WorkEntry } from './work';
import { usePanel } from './useIntent';

/* The question before the press: "You gave a later direction ...", asked in the Analyze control's place, so
   the answer has one home and is asked before a reading is spent rather than after one was demoted. It asks
   and never answers whether the direction conflicts: Compass does not write into a session, and deciding
   that a later instruction contradicts a typed goal is a reading of two prose strings, which the reader
   settles. The number comes from the entry list, and every unsettled later direction is drawn at its own
   number, so the "#<n>" named is on screen; the sentence drops the number rather than naming one the list
   did not give. */

const REFUSED_ID = 'next-cockpit-reading-refused';

function WholeList({
  pending,
  numbers,
}: {
  readonly pending: readonly WorkEntry[];
  readonly numbers: ReadonlyMap<string, string>;
}) {
  const { ctx, session } = usePanel();
  const key = compatSessKey(session);
  const held = ctx.held.wholes.get(key);
  /* Focusable by script alone, and named for the focus restore, so it keeps focus across the redraws while
     the reader reads. */
  const ref = useFocusKey<HTMLOListElement>(ctx.shell.controls.focusLane, `direction-whole:${key}`);
  if (!held || !held.drawn.size) return null;
  const items = pending.filter((entry) => held.drawn.has(String(entry.id || '')));
  if (!items.length) return null;
  return (
    <ol
      ref={ref}
      className="next-cockpit-direction-whole"
      data-next-cockpit-direction-whole
      tabIndex={-1}
      data-next-focus={`direction-whole:${key}`}
    >
      {items.map((entry) => {
        const id = String(entry.id || '');
        const opened = held.texts.get(id);
        const n = numbers.get(id);
        return (
          <li key={id} className="next-cockpit-direction-whole-item">
            {n === undefined ? null : (
              <span className="next-cockpit-source">{`#${String(n)}`}</span>
            )}
            <span className="next-cockpit-direction-whole-text">{opened?.text ?? ''}</span>
            {opened?.clipped ? <p className="next-cockpit-held-full">{DIRECTION_CLIPPED}</p> : null}
          </li>
        );
      })}
    </ol>
  );
}

export interface DirectionQuestionProps {
  /** The Analyze step's side of Keep. Absent, Keep only settles and sends nothing to a model. */
  readonly reading?: DirectionReading | null;
  /** The one primary action a question can have, while the session is not waiting on the reader. */
  readonly primary?: boolean;
  /** Controls the Analyze step draws beside Keep and Add (Turn off readings). */
  readonly buttons?: ReactNode;
  /** What the Analyze step draws under the answer: the disclosure, the count, the budget, a refusal. */
  readonly after?: ReactNode;
  /** The running analysis the question stands in front of, which the Analyze step draws above it. */
  readonly before?: ReactNode;
}

export function DirectionQuestion({
  reading = null,
  primary = false,
  buttons,
  after,
  before,
}: DirectionQuestionProps) {
  const { ctx, input, session, source, payload, projectKey } = usePanel();
  const key = compatSessKey(session);
  const pending = directionsOpen(input, source);
  const count = pending.length;
  // The whole texts go once no direction is open, as the legacy question dropped them.
  useEffect(() => {
    if (!count && ctx.held.wholes.has(key)) ctx.held.wholes.delete(key);
  }, [ctx, key, count]);
  const pickRef = useFocusKey<HTMLButtonElement>(
    ctx.shell.controls.focusLane,
    `direction-pick:${key}`,
  );
  const keepPending = useDisplayed((snapshot) =>
    snapshot.pending.includes(`direction-keep:${key}`),
  );
  if (!count) return null;
  const numbers = entryNumbers(session, source, payload);
  /* An unsaved edit outranks every other refusal: Keep would settle over words that are not on screen on any
     route, the no-reader one included. */
  const edited = intentUnsaved(input);
  const saving = ctx.shell.runtime.pending.has(`${intentKey(session)}:save`);
  const reason = edited ? editedRefusal(saving) : (reading?.reason ?? '');
  const job = reading?.job ?? false;
  const analyze = Boolean(reading) && !reason && !job;
  const request = ctx.held.requests.get(key);

  const earliest = directionSelected(ctx.held, session, pending);
  if (!earliest) return null;
  const draft = intentDraft(input);
  const typed = String(input.annotation?.['goal'] || '').trim();
  const since =
    typed || !draft
      ? 'since saving your intent'
      : draft.source === 'first-prompt'
        ? 'since your first prompt'
        : draft.source === PROMPT_CHOSEN
          ? 'since the prompt you chose'
          : 'since your latest prompt';
  const n = numbers.get(String(earliest.id || ''));
  const described = edited
    ? REFUSED_ID
    : reading?.disclosureId && analyze
      ? reading.disclosureId
      : '';

  return (
    <>
      {before}
      <div
        className="next-cockpit-direction-question gap-3 max-[760px]:gap-0.5"
        data-next-cockpit-direction-question
      >
        <p className="next-cockpit-direction-said">
          {`${String(count)} later direction${count === 1 ? '' : 's'}`}
          <span className="next-visually-hidden">{` ${since}`}</span>.
        </p>
        <WholeList pending={pending} numbers={numbers} />
        <div className="next-cockpit-reading-ask items-start [&>button]:flex-auto">
          <DirectionActionButton
            feedbackKey={`direction-keep:${key}`}
            weight={primary ? 'primary' : 'secondary'}
            label={analyze ? KEEP_ANALYZE : KEEP}
            busyLabel="Keeping…"
            pendingKey={`direction-keep:${key}`}
            inert={!keepPending && (edited || Boolean(request?.pending))}
            describes={described}
            action="direction-keep"
            focusKey={`direction-keep:${key}`}
            fallbackKey={`reading:${key}`}
            onPress={() => void keepIntent(ctx, session, projectKey, reading)}
          />
          <DirectionActionButton
            weight="secondary"
            feedbackKey={`direction-add:${key}`}
            label={ADD_DIRECTION}
            busyLabel="Opening…"
            pendingKey={`direction-add:${key}`}
            action="direction-add"
            arg={String(earliest.id || '')}
            focusKey={`direction-add:${key}`}
            onPress={() =>
              void openDirection(ctx, session, String(earliest.id || ''), n ?? null, true)
            }
          />
          <DirectionGoalButton factId={String(earliest.id || '')} scope="question" />
          {buttons}
        </div>
        {count > 1 ? (
          <Label className="next-direction-select">
            {'Direction '}
            <Select
              value={earliest.id}
              onValueChange={(value) => {
                if (value) pickDirection(ctx, session, value);
              }}
              items={pending.map((entry) => {
                const at = numbers.get(entry.id);
                return {
                  value: entry.id,
                  label: `${at !== undefined ? `#${String(at)}` : clock(Number(entry.at) || 0)} · ${entry.summary || 'Your direction'}`,
                };
              })}
            >
              <SelectTrigger
                ref={pickRef}
                data-next-direction-select
                data-next-focus={`direction-pick:${key}`}
                aria-label="Direction"
                title={String(earliest.summary || 'Your direction')}
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {pending.map((entry) => {
                  const at = numbers.get(entry.id);
                  return (
                    <SelectItem
                      key={entry.id}
                      value={entry.id}
                    >{`${at !== undefined ? `#${String(at)}` : clock(Number(entry.at) || 0)} · ${entry.summary || 'Your direction'}`}</SelectItem>
                  );
                })}
              </SelectContent>
            </Select>
          </Label>
        ) : null}
        {edited ? (
          <p className="next-cockpit-reading-why" id={REFUSED_ID}>
            {reason}
          </p>
        ) : null}
        {after}
      </div>
    </>
  );
}

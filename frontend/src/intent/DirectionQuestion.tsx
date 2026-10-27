import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from '../ui/select';
import { Label } from '../ui/label';
import { useEffect, type ReactNode } from 'react';
import { compatSessKey } from '../api/identity';
import { useFocusKey } from '../controls';
import { datedClock } from '../observed/values';
import { clock } from '../observed';
import { useDisplayed } from '../shell/context';
import { DirectionActionButton } from './DirectionActionButton';
import { DirectionGoalButton } from './OutcomeLines';
import {
  directionSelected,
  directionsOpen,
  editedRefusal,
  intentKey,
  intentUnsaved,
} from './derive';
import { keepIntent, loadWholes, openDirection } from './directions';
import { stripPasteWrapper } from './annotation';
import { pickDirection } from './edit';
import { ADD_DIRECTION, DIRECTION_CLIPPED, KEEP } from './sentences';
import { entryNumbers, type WorkEntry } from './work';
import { usePanel } from './useIntent';

/* The question before the press: "Your 11:05 message adds: ...", with the message quoted whole, asked beside
   the expected outcome so the answer has one home and is asked before a reading is spent. Each choice acts on
   its first press, because the words each acts on are drawn here before any press (`loadWholes`): Add as a
   line and Make it the goal open the rule in it for review, and Leave it settles what is shown. Analyze drift
   stays beside them. It asks and never answers whether the direction conflicts: Compass does not write into a
   session, and deciding that a later instruction contradicts a typed goal is a reading of two prose strings,
   which the reader settles. A direction is named by the time it was said, never by an entry number the
   reader has not been shown. */

const REFUSED_ID = 'next-cockpit-reading-refused';
/* Beside the direction the buttons act on, when several are listed: Add as a line and Make it the goal take
   the one the picker holds, and nothing else on the list said which that was. */
const ACTS_ON = 'the one the buttons below use';

/* A direction in the picker: the time it was said, then its words. Never a number: the entry number is the
   record's own bookkeeping and shows the reader nothing they said. */
function directionLabel(entry: WorkEntry): string {
  return `${clock(Number(entry.at) || 0)} · ${stripPasteWrapper(String(entry.summary || '')) || 'Your direction'}`;
}

function WholeList({
  pending,
  selected,
}: {
  readonly pending: readonly WorkEntry[];
  readonly selected: string;
}) {
  const { ctx, session } = usePanel();
  const key = compatSessKey(session);
  const held = ctx.held.wholes.get(key);
  /* Focusable by script alone, and named for the focus restore, so it keeps focus across the redraws while
     the reader reads. */
  const ref = useFocusKey<HTMLOListElement>(ctx.shell.controls.focusLane, `direction-whole:${key}`);
  const now = ctx.shell.clock.now() / 1000;
  const many = pending.length > 1;
  const items = held?.drawn.size
    ? pending.filter((entry) => held.drawn.has(String(entry.id || '')))
    : pending;
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
        const opened = held?.texts.get(id);
        return (
          <li
            key={id}
            className="next-cockpit-direction-whole-item"
            aria-current={many && id === selected ? 'true' : undefined}
          >
            {many ? (
              <span className="next-cockpit-source">
                {datedClock(Number(entry.at) || 0, now)}
                {id === selected ? ` · ${ACTS_ON}` : ''}
              </span>
            ) : null}
            <span className="next-cockpit-direction-whole-text">
              {opened?.text ?? stripPasteWrapper(String(entry.summary || ''))}
            </span>
            {opened?.clipped ? <p className="next-cockpit-held-full">{DIRECTION_CLIPPED}</p> : null}
          </li>
        );
      })}
    </ol>
  );
}

export interface DirectionQuestionProps {
  /** The one primary action a question can have, while the session is not waiting on the reader. */
  readonly primary?: boolean;
  /** Controls the Analyze step draws beside Keep and Add (Pause model calls). */
  readonly buttons?: ReactNode;
  /** What the Analyze step draws under the answer: the disclosure, the count, the budget, a refusal. */
  readonly after?: ReactNode;
  /** The running analysis the question stands in front of, which the Analyze step draws above it. */
  readonly before?: ReactNode;
}

export function DirectionQuestion({
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
  const drawnIds = pending.map((entry) => String(entry.id || '')).join(',');
  // biome-ignore lint/correctness/useExhaustiveDependencies: the open set is the trigger; the reads go through ctx.
  useEffect(() => {
    if (drawnIds) void loadWholes(ctx, session, projectKey);
  }, [ctx, key, drawnIds]);
  if (!count) return null;
  const numbers = entryNumbers(session, source, payload);
  /* An unsaved edit outranks every other refusal: Keep would settle over words that are not on screen on any
     route, the no-reader one included. */
  const edited = intentUnsaved(input);
  const saving = ctx.shell.runtime.pending.has(`${intentKey(session)}:save`);
  const reason = edited ? editedRefusal(saving) : '';
  const request = ctx.held.requests.get(key);

  const earliest = directionSelected(ctx.held, session, pending);
  if (!earliest) return null;
  const n = numbers.get(String(earliest.id || ''));
  const described = edited ? REFUSED_ID : '';
  const said =
    count === 1
      ? `Your ${datedClock(Number(earliest.at) || 0, ctx.shell.clock.now() / 1000)} message adds:`
      : `${String(count)} later directions:`;

  return (
    <>
      {before}
      <div
        className="next-cockpit-direction-question gap-3 max-[760px]:gap-0.5"
        data-next-cockpit-direction-question
      >
        <p className="next-cockpit-direction-said">{said}</p>
        <WholeList pending={pending} selected={String(earliest.id || '')} />
        <div className="next-cockpit-reading-ask items-start [&>button]:flex-auto">
          <DirectionActionButton
            weight={primary ? 'primary' : 'secondary'}
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
          <DirectionActionButton
            feedbackKey={`direction-keep:${key}`}
            weight="secondary"
            label={KEEP}
            busyLabel="Leaving…"
            pendingKey={`direction-keep:${key}`}
            inert={!keepPending && (edited || Boolean(request?.pending))}
            describes={described}
            action="direction-keep"
            focusKey={`direction-keep:${key}`}
            fallbackKey={`reading:${key}`}
            onPress={() => void keepIntent(ctx, session, projectKey)}
          />
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
              items={pending.map((entry) => ({ value: entry.id, label: directionLabel(entry) }))}
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
                {pending.map((entry) => (
                  <SelectItem key={entry.id} value={entry.id}>
                    {directionLabel(entry)}
                  </SelectItem>
                ))}
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

import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from '../ui/select';
import { Label } from '../ui/label';
import { useEffect, useId } from 'react';
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

/* The question dates and quotes the whole message, asked beside
   the expected outcome so the answer has one home and is asked before a reading is spent. Each choice acts on
   its first press, because the words each acts on are drawn here before any press (`loadWholes`): Add as a
   line and Make it the goal open the rule in it for review, and Leave it settles what is shown. Analyze drift
   stays beside them. It asks and never answers whether the direction conflicts: Compass does not write into a
   session, and deciding that a later instruction contradicts a typed goal is a reading of two prose strings,
   which the reader settles. A direction is named by the time it was said, never by an entry number the
   reader has not been shown. */

/* A direction in the picker: the time it was said, then its words. Never a number: the entry number is the
   record's own bookkeeping and shows the reader nothing they said. */
function directionLabel(entry: WorkEntry): string {
  return `${clock(Number(entry.at) || 0)} · ${stripPasteWrapper(String(entry.summary || '')) || 'Your direction'}`;
}

/* Only the direction the picker holds is quoted. Every unsettled one used to be quoted above a picker that
   listed them all again, which put 23 messages between the reader and the buttons on a long session (owner,
   2026-10-29). The picker is the list; this is the words the buttons act on. */
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
  const items = pending.filter((entry) => String(entry.id || '') === selected);
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
            className="next-cockpit-direction-whole-item border-l-2 border-[var(--line)] bg-card px-3 py-2"
          >
            {pending.length > 1 ? (
              <span className="next-cockpit-source">{datedClock(Number(entry.at) || 0, now)}</span>
            ) : null}
            <span className="next-cockpit-direction-whole-text wrap-anywhere" data-authored>
              {opened?.text ?? stripPasteWrapper(String(entry.summary || ''))}
            </span>
            {opened?.clipped ? <p className="next-cockpit-held-full">{DIRECTION_CLIPPED}</p> : null}
          </li>
        );
      })}
    </ol>
  );
}

interface DirectionQuestionProps {
  /** The one primary action a question can have, while the session is not waiting on the reader. */
  readonly primary?: boolean;
}

export function DirectionQuestion({ primary = false }: DirectionQuestionProps) {
  const { ctx, input, session, source, payload, projectKey } = usePanel();
  const key = compatSessKey(session);
  const refusalId = useId();
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
  const described = edited ? refusalId : '';
  const said =
    count === 1
      ? `You sent this message later, at ${datedClock(Number(earliest.at) || 0, ctx.shell.clock.now() / 1000)}.`
      : `You sent ${String(count)} messages after your goal. Choose one to add or make the goal, or leave them all:`;

  return (
    <div
      className="next-cockpit-direction-question gap-3 rounded-card border border-[var(--rule)] bg-muted p-4"
      data-next-cockpit-direction-question
    >
      <h3 className="m-0 text-body font-semibold">Is this part of your goal?</h3>
      <p className="next-cockpit-direction-said text-muted-foreground">{said}</p>
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
              data-authored={Boolean(earliest.summary) || undefined}
              title={String(earliest.summary || 'Your direction')}
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {pending.map((entry) => (
                <SelectItem key={entry.id} value={entry.id}>
                  <span data-authored>{directionLabel(entry)}</span>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Label>
      ) : null}
      <WholeList pending={pending} selected={String(earliest.id || '')} />
      <div className="next-cockpit-reading-ask items-start">
        <DirectionActionButton
          fit
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
          fit
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
      </div>
      {edited ? (
        <p className="next-cockpit-reading-why" id={refusalId}>
          {reason}
        </p>
      ) : null}
    </div>
  );
}

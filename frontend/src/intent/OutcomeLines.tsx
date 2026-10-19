import { useId } from 'react';
import { Label } from '../ui/label';
import { compatSessKey } from '../api/identity';
import { annotationLines, storeUnreadable, OUTCOME_LINES_MAX } from './annotation';
import { heldSentence } from './cues';
import { directionWhy, linesDraft, linesKey, linesToSend, lineSource } from './derive';
import { ActionButton } from './ActionButton';
import { DirectionActionButton } from './DirectionActionButton';
import {
  cancelDirection,
  replaceDirection,
  saveDirection,
  typeDirection,
  adoptDirectionAsGoal,
} from './directions';
import { addLine, escapeLines, removeLine, typeLine } from './edit';
import { HeldTextarea } from './HeldTextarea';
import { DIRECTION_CLIPPED, LINES_FULL } from './sentences';
import { entryNumbers } from './work';
import { usePanel } from './useIntent';

/* The expected outcome, as a checklist of up to six lines. One draft per session, an array held beside the
   goal's, so adding, removing and typing survive a redraw as the goal's draft does. A box a reader emptied is
   still a box until the save, where the store drops it. With nothing saved and nothing drafted, one empty box
   is offered rather than none. */

/* "Use this as my goal", over a direction the reader is looking at. Only on the harnesses that publish the
   prompts it is adopted from. */
export function DirectionGoalButton({
  factId,
  scope,
}: {
  readonly factId: string;
  readonly scope: string;
}) {
  const { ctx, session } = usePanel();
  if (!['claude', 'codex'].includes(String(session['harness'] || '')) || !factId) return null;
  const key = compatSessKey(session);
  const focus = `direction-goal:${key}:${scope}:${factId}`;
  return (
    <DirectionActionButton
      feedbackKey={focus}
      weight="secondary"
      label="Use this as my goal"
      pendingKey={`direction-goal:${key}`}
      busyLabel="Opening…"
      action="direction-goal"
      arg={factId}
      focusKey={focus}
      onPress={() => void adoptDirectionAsGoal(ctx, session, factId, focus)}
    />
  );
}

/* A later direction, opened for review as one pending outcome line, and saved only by the `add_direction`
   arm of `/api/annotate`. Per session, beside the lines draft. */
function DirectionLineView() {
  const boxId = useId();
  const { ctx, input, session, source, cap, payload } = usePanel();
  const key = compatSessKey(session);
  const held = ctx.held.directions.get(key);
  const annotation = input.annotation;
  const focus = `direction:${key}`;
  if (!held || typeof held.text !== 'string') return null;
  /* From its fact id on every render, as every "#<n>" on the page is, and gone once its direction is no
     longer open. The panel drops it after the render that finds it so. */
  const read = source.state === 'read' || source.state === 'empty';
  const n = read ? (entryNumbers(session, source, payload).get(held.factId) ?? null) : held.n;
  const text = held.text;
  const why = directionWhy(held, input, cap);
  const ready = !why && Boolean(text.trim()) && !held.pending;
  const full = annotationLines(annotation).length >= OUTCOME_LINES_MAX;
  const from = n !== null ? `from #${String(n)} · not saved` : 'from your direction · not saved';
  const cue = held.cue ? heldSentence(held.cue, null) : '';
  return (
    <li
      className="next-cockpit-held-line next-cockpit-direction-line"
      data-next-cockpit-direction-line
    >
      <HeldTextarea
        id={boxId}
        rows={3}
        className="max-[760px]:h-[44px]"
        memoryKey={focus}
        focusKey={focus}
        text={text}
        aria-label={from}
        data-next-cockpit-direction-key={key}
        data-next-focus={focus}
        onEdit={(raw) => typeDirection(ctx, session, raw)}
      />
      {/* The saved lines' pattern: the box, then the count and where it came from on the left, and Save
          and Remove on the right. */}
      <div className="next-cockpit-held-under">
        <span className="next-cockpit-held-count" data-next-cockpit-direction-count>
          {`${String(text.length)} / ${String(cap)}`}
        </span>
        <Label className="next-cockpit-held-source" htmlFor={boxId}>
          {from}
        </Label>
        <span className="next-cockpit-direction-tools">
          <ActionButton
            weight="none"
            label="Save"
            busyLabel="Saving…"
            reserve="Saving…"
            pendingKey={`direction-save:${key}`}
            inert={!ready}
            describedBy={why ? 'next-cockpit-direction-why' : ''}
            action="direction-save"
            focusKey={`direction-save:${key}`}
            onPress={() => void saveDirection(ctx, session)}
          />
          <ActionButton
            weight="none"
            label="Remove"
            action="direction-cancel"
            focusKey={`direction-cancel:${key}`}
            onPress={() => cancelDirection(ctx, session)}
          />
        </span>
      </div>
      {full ? (
        <span className="next-cockpit-direction-replace">
          <span>Replace line</span>
          {annotationLines(annotation).map((line, index) => (
            <ActionButton
              key={line.k}
              weight="none"
              label={String(index + 1)}
              ariaLabel={`Replace line ${String(index + 1)}`}
              ariaPressed={held.replace === index}
              action="direction-replace"
              arg={String(index)}
              focusKey={`direction-replace:${key}:${String(index)}`}
              onPress={() => replaceDirection(ctx, session, index)}
            />
          ))}
        </span>
      ) : null}
      <p
        className="next-cockpit-held-full"
        id="next-cockpit-direction-why"
        data-next-cockpit-direction-why
        hidden={!why}
      >
        {why}
      </p>
      <p className="next-cockpit-held-hint">Write the rule, not the moment.</p>
      {why || held.clipped ? <DirectionGoalButton factId={held.factId} scope="line" /> : null}
      {held.clipped ? <p className="next-cockpit-held-full">{DIRECTION_CLIPPED}</p> : null}
      {cue ? <small className="next-cockpit-held-cue">{cue}</small> : null}
    </li>
  );
}

function LineRow({
  index,
  text,
  boxId,
  used,
}: {
  readonly index: number;
  readonly text: string;
  readonly boxId: string | undefined;
  readonly used: boolean;
}) {
  const { ctx, input, session, cap, source, payload } = usePanel();
  const key = linesKey(session);
  const saved = annotationLines(input.annotation);
  /* Remove shares the box row so a saved outcome does not push Keep below the phone viewport.
     An entry source keeps its space during an edit, so the editor does not move under the caret. */
  const place = saved[index] ?? null;
  const line = place && place.text === text ? place : null;
  return (
    <li
      className={`next-cockpit-held-line ${used ? 'grid-cols-[auto_minmax(0,1fr)_auto]' : 'grid-cols-[auto_minmax(0,1fr)]'}`}
      data-next-cockpit-held-line={index}
    >
      <span
        aria-hidden="true"
        className="col-start-1 col-end-2 self-center min-w-[18px] [font-family:var(--mono)] text-label text-muted-foreground"
        data-next-cockpit-held-line-number={index}
      >
        {String(index + 1)}
      </span>
      <HeldTextarea
        id={boxId}
        className="col-start-2 col-end-3 max-[760px]:h-[44px]"
        aria-label={`Expected outcome line ${String(index + 1)}`}
        rows={3}
        maxLength={cap}
        memoryKey={`${key}:${String(index)}`}
        focusKey={`${key}:${String(index)}`}
        text={text}
        placeholder="One thing that should be true when it's done"
        data-next-cockpit-held-line-index={index}
        data-next-cockpit-held-lines-key={key}
        data-next-cockpit-held-saved={place ? place.text : ''}
        data-next-focus={`${key}:${String(index)}`}
        onEdit={(raw) => typeLine(input, index, raw)}
        onKeyDown={(event) => {
          if (event.key !== 'Escape') return;
          event.preventDefault();
          event.stopPropagation();
          escapeLines(ctx, input);
        }}
      />
      <div className="next-cockpit-held-under col-start-2 col-end-3">
        <span className="next-cockpit-held-count" data-next-cockpit-held-line-count={index}>
          {`${String(text.length)} / ${String(cap)}`}
        </span>
        {place && place.source === 'entry' ? (
          <span
            className="next-cockpit-held-source"
            data-next-cockpit-held-line-source={index}
            {...(line ? {} : { 'data-next-cockpit-held-line-source-stale': '' })}
          >
            {lineSource(place, session, source, payload)}
          </span>
        ) : null}
      </div>
      {used ? (
        <ActionButton
          weight="secondary"
          className="next-cockpit-held-remove col-start-3 row-start-1 row-span-2 self-start"
          label="Remove"
          action="held-line-remove"
          arg={String(index)}
          ariaLabel={`Remove line ${String(index + 1)}`}
          focusKey={`${key}:remove:${String(index)}`}
          onPress={() => removeLine(input, index)}
        />
      ) : null}
    </li>
  );
}

export function OutcomeLines() {
  const firstBoxId = useId();
  const { ctx, input, session, payload, cap } = usePanel();
  const { held } = ctx;
  const key = linesKey(session);
  const annotation = input.annotation;
  const draft = linesDraft(held, session, annotation);
  const boxes = draft.length ? draft : [''];
  const full = draft.length >= OUTCOME_LINES_MAX;
  const line = held.directions.get(compatSessKey(session));
  const used =
    draft.length > 1 ||
    draft.some((text) => text.trim()) ||
    annotationLines(annotation).length > 0 ||
    Boolean(line?.text?.trim());
  const why = storeUnreadable(payload) ? '' : String(annotation?.['lines_why'] || '');
  const cue = heldSentence(held.kind(key), null);
  /* Where an open later direction already says the list is full beside its own save, the list's sentence is
     hidden rather than drawn twice. Only then: the line checks saved lines and the list counts draft lines,
     and a line giving another reason would leave the disabled add control with none. It stays in the DOM for
     that control's `aria-describedby`. */
  const said =
    Boolean(line) &&
    typeof line?.text === 'string' &&
    directionWhy(line, input, cap) === LINES_FULL;
  return (
    <div
      className="next-cockpit-held-field next-cockpit-held-lines"
      data-next-cockpit-held-field="lines"
    >
      <div className="next-cockpit-held-heading">
        <Label className="next-cockpit-held-label" htmlFor={firstBoxId}>
          Expected outcome{' '}
          <span className="ms-1 font-normal text-[var(--ink3)]">{`· up to ${String(OUTCOME_LINES_MAX)} lines`}</span>
        </Label>
      </div>
      <ol className="next-cockpit-held-list">
        {boxes.map((text, index) => (
          // A line is its position: the list holds no ids, and an index is what the store sends.
          <LineRow
            key={index}
            index={index}
            text={text}
            used={Boolean(used)}
            boxId={index === 0 ? firstBoxId : undefined}
          />
        ))}
        <DirectionLineView />
      </ol>
      <p
        className="next-cockpit-held-full"
        id="next-cockpit-held-full"
        data-next-cockpit-held-full
        hidden={!(full && !said)}
      >
        {LINES_FULL}
      </p>
      {why ? (
        <p
          className="next-cockpit-held-absent next-visually-hidden"
          id="next-cockpit-held-absent-lines"
          data-next-cockpit-held-absent="lines"
          hidden={linesToSend(draft).length > 0}
        >
          {why}
        </p>
      ) : null}
      {cue ? <small className="next-cockpit-held-cue">{cue}</small> : null}
    </div>
  );
}

export function AddOutcomeLine() {
  const { ctx, input, session } = usePanel();
  const draft = linesDraft(ctx.held, session, input.annotation);
  const line = ctx.held.directions.get(compatSessKey(session));
  const used =
    draft.length > 1 ||
    draft.some((text) => text.trim()) ||
    annotationLines(input.annotation).length > 0 ||
    Boolean(line?.text?.trim());
  if (!used) return null;
  return (
    <ActionButton
      label="+ Add a line"
      action="held-line-add"
      arg="lines"
      inert={draft.length >= OUTCOME_LINES_MAX}
      describedBy="next-cockpit-held-full"
      focusKey={`${linesKey(session)}:add`}
      onPress={() => addLine(ctx, input)}
    />
  );
}

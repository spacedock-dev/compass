import { useId } from 'react';
import { Label } from '../ui/label';
import { endedAt } from '../observed';
import { ActionButton } from './ActionButton';
import { storeUnreadable } from './annotation';
import { heldSentence } from './cues';
import { clearGoal, escapeGoal, typeGoal } from './edit';
import {
  directionLinesQuestion,
  goalBaseline,
  goalKey,
  goalSourceLine,
  intentDraft,
} from './derive';
import { answerLines } from './directions';
import { HeldTextarea } from './HeldTextarea';
import { PromptSelect } from './PromptSelect';
import { ENDED_CAVEAT } from './sentences';
import { usePanel } from './useIntent';

/* "Keep your standing outcome lines with this goal?": asked once when a direction became the goal, and Save
   intent waits for the answer. */
function LinesQuestion() {
  const { ctx, session } = usePanel();
  if (!directionLinesQuestion(ctx.held, session)) return null;
  return (
    <>
      <p>Keep your standing outcome lines with this goal?</p>
      <ActionButton
        weight="none"
        label="Keep outcome lines"
        action="direction-lines-keep"
        focusKey="direction-lines-keep"
        onPress={() => answerLines(ctx, session, 'keep')}
      />
      <ActionButton
        weight="none"
        label="Clear outcome lines"
        action="direction-lines-clear"
        focusKey="direction-lines-clear"
        onPress={() => answerLines(ctx, session, 'clear')}
      />
    </>
  );
}

export function GoalField() {
  const boxId = useId();
  const { ctx, input, session, cap } = usePanel();
  const { held } = ctx;
  const key = goalKey(session);
  const drafted = intentDraft(input);
  const saved = goalBaseline(input);
  const text = held.goals.has(key) ? (held.goals.get(key) ?? saved) : saved;
  const untouched = Boolean(drafted) && text === drafted?.text;
  const sourceLine = goalSourceLine(input);
  const why = storeUnreadable(input.payload) ? '' : String(input.annotation?.['goal_why'] || '');
  const cue = heldSentence(held.kind(key), null);
  return (
    <div
      className="next-cockpit-held-field"
      data-next-cockpit-held-field="goal"
      {...(untouched ? { 'data-next-cockpit-drafted': '' } : {})}
    >
      <div className="next-cockpit-held-heading flex-nowrap [&_.next-intent-prompt-pick]:flex-none max-[760px]:[&_.next-intent-prompt-pick]:flex-1">
        <Label className="next-cockpit-held-label" htmlFor={boxId}>
          Goal
        </Label>
        <PromptSelect />
      </div>
      {endedAt(session) !== null ? (
        <p className="next-cockpit-held-absent" data-next-ended-goal>
          {ENDED_CAVEAT}
        </p>
      ) : null}
      <HeldTextarea
        id={boxId}
        rows={3}
        className="min-h-[44px] max-[760px]:h-[44px]"
        maxLength={cap}
        memoryKey={key}
        focusKey={key}
        text={text}
        placeholder="What should this session achieve?"
        data-next-cockpit-held-kind="goal"
        data-next-cockpit-held-key={key}
        data-next-focus={key}
        onEdit={(raw) => typeGoal(ctx, input, raw)}
        onKeyDown={(event) => {
          if (event.key !== 'Escape') return;
          event.preventDefault();
          event.stopPropagation();
          escapeGoal(ctx, input);
        }}
      />
      <div className="next-cockpit-held-under min-h-0 flex-wrap justify-between">
        {sourceLine ? (
          <small
            className="next-cockpit-held-source"
            data-next-cockpit-goal-source
            {...(untouched && drafted ? { 'data-next-cockpit-draft-marks': '' } : {})}
          >
            {sourceLine}
          </small>
        ) : null}
        <span className="next-cockpit-held-count ms-auto" data-next-cockpit-held-count="goal">
          {`${String(text.length)} / ${String(cap)}`}
        </span>
      </div>
      {/* The absence sentence answers "why is this empty", so it goes when the box stops being empty. It
          stays in the document, visually hidden, because the inert Save intent is described by it. */}
      {why ? (
        <p
          className="next-cockpit-held-absent next-visually-hidden"
          id="next-cockpit-held-absent-goal"
          data-next-cockpit-held-absent="goal"
          hidden={Boolean(text)}
        >
          {why}
        </p>
      ) : null}
      <LinesQuestion />
      {cue ? <small className="next-cockpit-held-cue">{cue}</small> : null}
    </div>
  );
}

export function ClearGoal() {
  const { ctx, input, session } = usePanel();
  const key = goalKey(session);
  const text = ctx.held.goals.get(key) ?? goalBaseline(input);
  return (
    <ActionButton
      label="Clear"
      action="held-clear"
      arg="goal"
      hidden={!text}
      focusKey={`${key}:clear`}
      onPress={() => clearGoal(ctx, input)}
    />
  );
}

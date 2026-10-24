import { useId } from 'react';
import { Label } from '../ui/label';
import { clock as clockText, endedAt } from '../observed';
import { promptClip } from './derive';
import { ActionButton } from './ActionButton';
import { storeUnreadable } from './annotation';
import { heldSentence } from './cues';
import { clearGoal, escapeGoal, keepSavedGoal, takeDetectedGoal, typeGoal } from './edit';
import {
  directionLinesQuestion,
  foundGoal,
  goalBaseline,
  goalKey,
  goalRefused,
  goalEndedNote,
  goalSourceLine,
  goalUpdate,
  intentDraft,
  SESSION_GOAL,
} from './derive';
import { GOAL_UNCLEAR } from '../drift/sentences';
import { answerLines } from './directions';
import { HeldTextarea } from './HeldTextarea';
import { FindGoal, FindGoalNote, FoundCites } from './FindGoal';
import { PromptSelect } from './PromptSelect';
import { ENDED_CAVEAT, GOAL_HINT, RULE_HINT } from './sentences';
import { usePanel } from './useIntent';

/* "Keep your standing outcome lines with this goal?": asked once when a direction became the goal, and Save
   intent waits for the answer. */
function LinesQuestion() {
  const { ctx, session } = usePanel();
  if (!directionLinesQuestion(ctx.held, session)) return null;
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1" data-next-direction-lines-question>
      <p>Keep your standing outcome lines with this goal?</p>
      <ActionButton
        weight="secondary"
        label="Keep outcome lines"
        action="direction-lines-keep"
        focusKey="direction-lines-keep"
        onPress={() => answerLines(ctx, session, 'keep')}
      />
      <ActionButton
        weight="secondary"
        label="Clear outcome lines"
        action="direction-lines-clear"
        focusKey="direction-lines-clear"
        onPress={() => answerLines(ctx, session, 'clear')}
      />
    </div>
  );
}

/* A /goal the session set after the reader saved their own goal: offered beside the field, naming the new
   condition and its time. Taking it fills the box as a pending adoption, so the saved words stay what they
   are until Save intent; keeping them declines this /goal and asks again only for a later one. */
function GoalUpdateOffer() {
  const { ctx, input } = usePanel();
  const update = goalUpdate(input);
  if (!update) return null;
  return (
    <div
      className="flex flex-wrap items-center gap-x-3 gap-y-1"
      role="group"
      aria-label="A newer goal from /goal"
      data-next-goal-update
    >
      <p title={update.text}>
        {`Your /goal changed at ${clockText(update.at)}: ${promptClip(update.text, 120)}`}
        {update.cut ? ' (cut to fit the goal limit)' : ''}
      </p>
      <ActionButton
        weight="secondary"
        label="Use this goal"
        action="goal-update-use"
        focusKey="goal-update-use"
        onPress={() => takeDetectedGoal(ctx, input)}
      />
      <ActionButton
        weight="secondary"
        label="Keep my goal"
        action="goal-update-keep"
        focusKey="goal-update-keep"
        onPress={() => keepSavedGoal(ctx, input)}
      />
    </div>
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
  /* A goal found in the prompts is marked as a /goal is, for as long as the box holds its words. */
  const found = foundGoal(input);
  const sourceLine = goalSourceLine(input);
  const endedGoal = goalEndedNote(input);
  const why = storeUnreadable(input.payload) ? '' : String(input.annotation?.['goal_why'] || '');
  const cue = heldSentence(held.kind(key), null);
  /* The refusal says it for the words that were read, so it goes the moment the box differs from them. */
  const refused = goalRefused(input) && !drafted && text === saved;
  return (
    <div
      className="next-cockpit-held-field"
      data-next-cockpit-held-field="goal"
      {...(untouched || found ? { 'data-next-cockpit-drafted': '' } : {})}
    >
      <div className="next-cockpit-held-heading flex-nowrap max-[760px]:flex-wrap [&_.next-intent-prompt-pick]:flex-none max-[760px]:[&_.next-intent-prompt-pick]:flex-1">
        <Label className="next-cockpit-held-label shrink-0 whitespace-nowrap" htmlFor={boxId}>
          Goal
        </Label>
        {found || (untouched && drafted?.source === SESSION_GOAL) ? (
          <span
            className="next-cockpit-held-detected text-label text-muted-foreground"
            data-next-goal-detected
          >
            Goal detected
          </span>
        ) : null}
        <span className="ms-auto flex min-w-0 max-w-full items-center gap-2 max-[760px]:w-full [&_.next-intent-prompt-pick]:ms-0">
          <FindGoal />
          <PromptSelect />
        </span>
      </div>
      <FindGoalNote />
      {endedGoal ? (
        <p className="next-cockpit-held-absent" data-next-goal-ended>
          {endedGoal}
        </p>
      ) : null}
      {endedAt(session) !== null ? (
        <p className="next-cockpit-held-absent" data-next-ended-goal>
          {ENDED_CAVEAT}
        </p>
      ) : null}
      {sourceLine ? (
        <small
          className="next-cockpit-held-source col-span-full"
          data-next-cockpit-goal-source
          {...((untouched && drafted) || found ? { 'data-next-cockpit-draft-marks': '' } : {})}
        >
          {sourceLine}
        </small>
      ) : null}
      <HeldTextarea
        id={boxId}
        rows={3}
        className="min-h-[5.5rem]"
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
      {refused ? (
        <p
          className="m-0 py-0.5 pl-2.5 text-body leading-[1.5] text-foreground [border-left:3px_solid_var(--clay)]"
          data-next-goal-unclear
        >
          {GOAL_UNCLEAR}
        </p>
      ) : null}
      <div className="next-cockpit-held-under min-h-0 flex-wrap justify-between">
        {/* The hint takes the left of the count's row and wraps inside its own width on a narrow card. The
            source line is above the box, where a change in its length cannot move the row under it. */}
        <p className="next-cockpit-held-hint" data-next-goal-hint>
          {GOAL_HINT}
        </p>
        <FoundCites />
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
      {held.chosen.get(key)?.direction ? (
        <p className="next-cockpit-held-hint">{RULE_HINT}</p>
      ) : null}
      <GoalUpdateOffer />
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

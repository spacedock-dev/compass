import { SampleMark } from '../sample/SampleMark';
import { Card } from '../ui/card';
import { compatSessKey } from '../api/identity';
import { nextNumber } from '../api/bootstrap';
import { useFocusKey } from '../controls';
import { Icon } from '../ui/icons';
import { formatTimestamp } from '../shell/format';
import { FindGoalNote } from './FindGoal';
import { endedAt } from '../observed';
import { GLOSSARY, GOAL_LABEL } from '../language/glossary';
import { useDisplayed } from '../shell/context';
import { ActionButton } from './ActionButton';
import { annotationDiscarded, discardStamp, heldCap, storeUnreadable } from './annotation';
import { heldSentence } from './cues';
import {
  directionLinesQuestion,
  directionWhy,
  intentChanges,
  intentOverLimit,
  goalKey,
  goalSourceLine,
  DRAFT_UNSAVED,
  intentUnsaved,
  savedLines,
  intentDrafted,
  intentKey,
  intentStatus,
  noDraftWhy,
} from './derive';
import { openGoalEditor, undoChanges } from './edit';
import { ArmedDiscard, CaveatNotes, DiscardOffer, LaterDirections } from './Caveats';
import { ClearGoal, GoalField, GoalUpdateOffer } from './GoalField';
import { OutcomeLines } from './OutcomeLines';
import { saveIntent } from './save';
import { saveIntentAndLine } from './directions';
import { ENDED_CAVEAT, INTENT_EDITED_ADD, READ_FROM_NOW_WHY, isReadsFrom } from './sentences';
import { PromptSelect } from './PromptSelect';
import { usePanel } from './useIntent';
import { GoalExplanation } from './HowTo';

/* The controls sit together on the left and are always drawn, as the design has them: Save goal and Undo
   changes, inert until there is something to undo. Add a line lives inside the Expected outcome accordion. */
function Footer() {
  const { ctx, input, session, payload } = usePanel();
  const key = intentKey(session);
  const changes = intentChanges(input);
  const unreadable = Boolean(storeUnreadable(payload));
  const absent = unreadable
    ? []
    : (
        [
          ['goal', 'goal_why'],
          ['lines', 'lines_why'],
        ] as const
      )
        .filter(([, why]) => input.annotation?.[why])
        .map(([kind]) => `next-cockpit-held-absent-${kind}`);
  /* Not while the save is still busy: the outcome is drawn and said together, when the button settles, and a
     redraw in between drew "Saved" beside "Saving…". */
  const saving = useDisplayed((snapshot) => snapshot.pending.includes(`${key}:save`));
  const kind = saving ? '' : ctx.held.kind(key);
  const cue = [
    heldSentence(kind, null, ctx.held.refusals.get(key)),
    (kind === 'saved' || isReadsFrom(kind)) && endedAt(session) !== null ? ENDED_CAVEAT : '',
  ]
    .filter(Boolean)
    .join(' ');
  const question = directionLinesQuestion(ctx.held, session);
  /* The one save for the card, and for a pending line beside it: an open later-direction line is added by this
     same press, so the card never draws a second Save. */
  const line = ctx.held.directions.get(compatSessKey(session));
  const lineLive =
    Boolean(line) &&
    typeof line?.text === 'string' &&
    Boolean(line.text.trim()) &&
    !line.pending &&
    !question &&
    [INTENT_EDITED_ADD, ''].includes(directionWhy(line, input, heldCap(input.payload)));
  const saveLive =
    !intentOverLimit(input) && (((changes.any || changes.adoptable) && !question) || lineLive);
  /* Offered only over words that are saved: the first save opens the window by itself, so beside it the
     choice would be a second button for one act. `revision_count` is the store's own count and is 0 for none. */
  const reopenable =
    (nextNumber(input.annotation?.['revision_count']) ?? 0) > 0 &&
    !annotationDiscarded(input.annotation);
  /* Undo is inert while its save is in flight: reverting the box would leave the words being sent unseen. */
  return (
    <div className="next-cockpit-held-footer">
      <span className="next-cockpit-held-tools">
        <ClearGoal />
        <ActionButton
          label="Save goal"
          className={`font-bold px-4 ${saveLive || saving ? 'border-[var(--accent)] text-[color:var(--accent)]' : ''}`}
          busyLabel="Saving…"
          pendingKey={`${key}:save`}
          action="held-save"
          arg="intent"
          inert={!saveLive}
          describedBy={absent.join(' ')}
          focusKey={`${key}:save`}
          onPress={() => void saveIntentAndLine(ctx, session)}
        />
        {reopenable ? (
          <ActionButton
            label="Read from my latest message"
            busyLabel="Saving…"
            pendingKey={`${key}:save`}
            action="held-save-from-now"
            arg="intent"
            title={READ_FROM_NOW_WHY}
            inert={!saveLive}
            focusKey={`${key}:save-from-now`}
            onPress={() => void saveIntent(ctx, session, true)}
          />
        ) : null}
        <ActionButton
          label="Undo changes"
          action="held-undo"
          arg="intent"
          inert={!(changes.undoable && !saving)}
          focusKey={`${key}:undo`}
          onPress={() => undoChanges(ctx, input)}
        />
      </span>
      {cue ? <small className="next-cockpit-held-cue">{cue}</small> : null}
    </div>
  );
}

function SavedGoal({ goal }: { readonly goal: string }) {
  const { input, payload } = usePanel();
  const annotation = input.annotation;
  const source = goalSourceLine(input);
  const written = !source || source.startsWith('You typed this');
  const savedAt =
    nextNumber(annotation?.['goal_saved_at']) ??
    (written || annotation?.['revision'] === 1 ? nextNumber(annotation?.['at']) : null);
  const provenance = written ? 'You wrote this' : source.replace(/ · saved.*$/, '');
  const time = formatTimestamp(savedAt, payload['generated'], { style: 'clock' });
  const when = time ? `saved ${time}` : 'saved';
  const lines = savedLines(annotation);
  return (
    <div className="grid gap-3">
      <p className="text-label text-muted-foreground" data-next-cockpit-goal-source>
        {`${provenance} · ${when}`}
        {written ? '' : (source.match(/ · saved( · .*)$/)?.[1] ?? '')}
      </p>
      <p className="wrap-anywhere text-value font-bold" data-authored>
        {goal}
      </p>
      {lines.length ? (
        <div>
          <h3 className="text-body font-semibold">{GLOSSARY.doneLooksLike.shown}</h3>
          <ul className="mt-1 grid gap-1">
            {lines.map((line, index) => (
              <li key={index} className="flex items-start gap-2 wrap-anywhere">
                <Icon name="check" className="mt-0.5 shrink-0 text-[var(--accent)]" />
                <span className="min-w-0" data-authored>
                  {line}
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

export function IntentSection({ editable }: { readonly editable: boolean }) {
  const { input, session, payload } = usePanel();
  const { ctx } = usePanel();
  const heading = useFocusKey<HTMLHeadingElement>(
    ctx.shell.controls.focusLane,
    `intent:${compatSessKey(session)}`,
  );
  const status = useDisplayed((snapshot) => intentStatus(input, snapshot.pending));
  const annotation = input.annotation;
  const generated = nextNumber(payload['generated']);
  const stamp = discardStamp(annotation, generated);
  const drafted = intentDrafted(input);
  const why = drafted ? '' : noDraftWhy(session, annotation, payload);
  const unreadable = storeUnreadable(payload);
  const key = goalKey(session);
  const saved =
    !editable || unreadable || annotationDiscarded(annotation)
      ? ''
      : String(annotation?.['goal'] ?? '').trim();
  const draft = intentChanges(input);
  const pending =
    intentUnsaved(input) ||
    draft.any ||
    draft.adoptable ||
    Boolean(ctx.held.directions.get(compatSessKey(session))) ||
    status === 'Saving…';
  const explicit = ctx.held.editingGoals.has(key);
  const showEditor = editable && (!saved || explicit || pending);
  return (
    <Card
      variant="intent-panel"
      as="section"
      className="next-cockpit-held"
      aria-labelledby="next-session-intent-heading"
    >
      <header className="flex-wrap">
        {/* The mark beside the heading it notes, not spread to the middle of the row. */}
        <span className="flex items-baseline">
          <h2
            id="next-session-intent-heading"
            className="m-0 text-head font-bold"
            ref={heading}
            tabIndex={-1}
            data-next-focus={`intent:${compatSessKey(session)}`}
          >
            {GOAL_LABEL}
          </h2>
          <SampleMark id="intent" />
        </span>
        <span className="ms-auto flex flex-wrap items-baseline gap-x-3 gap-y-1">
          {showEditor ? (
            <span
              className={`text-label ${status === 'Saved' || status === DRAFT_UNSAVED ? 'text-muted-foreground' : 'text-[var(--amber)]'}`}
              data-next-intent-status
            >
              {status || (unreadable ? '' : 'Not saved')}
            </span>
          ) : editable && saved ? (
            <>
              <ActionButton
                label="Edit goal"
                focusKey={`${key}:edit`}
                onPress={() => openGoalEditor(ctx, session)}
              />
              <PromptSelect compact offerWithoutCandidates />
            </>
          ) : null}
        </span>
      </header>
      {showEditor ? (
        <>
          {why ? (
            <p className="next-cockpit-held-lede" data-next-intent-no-draft>
              {why}
            </p>
          ) : null}
          {unreadable ? <p className="next-cockpit-held-absent">{unreadable}</p> : null}
          {stamp ? (
            <div className="next-cockpit-held-stamp">
              <span className="next-cockpit-held-revision">{stamp}</span>
            </div>
          ) : null}
          <div className="next-cockpit-held-fields max-[760px]:gap-1">
            <GoalField />
            <OutcomeLines />
          </div>
          <Footer />
          <div className="flex flex-wrap items-center gap-2" data-next-intent-kept>
            <DiscardOffer />
            {saved && explicit && !pending ? (
              <ActionButton
                label="Done editing"
                onPress={() => {
                  ctx.held.editingGoals.delete(key);
                  ctx.held.requestFocus(`${key}:edit`);
                }}
              />
            ) : null}
          </div>
          <ArmedDiscard />
        </>
      ) : saved ? (
        <>
          <SavedGoal goal={saved} />
          {editable ? (
            <>
              <GoalUpdateOffer />
              <FindGoalNote />
            </>
          ) : null}
        </>
      ) : null}
      <CaveatNotes />
      <GoalExplanation />
      {editable ? <LaterDirections /> : null}
    </Card>
  );
}

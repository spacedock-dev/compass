import { SampleMark } from '../sample/SampleMark';
import { Card } from '../ui/card';
import { compatSessKey } from '../api/identity';
import { nextNumber } from '../api/bootstrap';
import { Disclosure, disclosureKey, useFocusKey } from '../controls';
import { clock, endedAt } from '../observed';
import { useDisplayed } from '../shell/context';
import { ActionButton } from './ActionButton';
import { annotationDiscarded, discardStamp, revisionLine, storeUnreadable } from './annotation';
import { heldSentence } from './cues';
import {
  directionLinesQuestion,
  intentChanges,
  intentDrafted,
  intentKey,
  intentStatus,
  DRAFT_UNSAVED,
  noDraftWhy,
} from './derive';
import { undoChanges } from './edit';
import { CaveatNotes, Caveats, LaterDirections } from './Caveats';
import { ClearGoal, GoalField } from './GoalField';
import { OutcomeLines, AddOutcomeLine } from './OutcomeLines';
import { saveIntent } from './save';
import {
  ENDED_CAVEAT,
  INTENT_LEDE,
  INTENT_MEASURED,
  READ_FROM_NOW_WHY,
  isReadsFrom,
} from './sentences';
import { usePanel } from './useIntent';
import { HowTo } from './HowTo';

/* The three controls sit together on the left and are always drawn, as the design has them: Add a line, Save
   intent, and Undo changes, inert until there is something to undo. */
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
    heldSentence(kind, null),
    (kind === 'saved' || isReadsFrom(kind)) && endedAt(session) !== null ? ENDED_CAVEAT : '',
  ]
    .filter(Boolean)
    .join(' ');
  const question = directionLinesQuestion(ctx.held, session);
  const saveLive = (changes.any || changes.adoptable) && !question;
  /* Offered only over words that are saved: the first save opens the window by itself, so beside it the
     choice would be a second button for one act. `revision_count` is the store's own count and is 0 for none. */
  const reopenable =
    (nextNumber(input.annotation?.['revision_count']) ?? 0) > 0 &&
    !annotationDiscarded(input.annotation);
  /* Undo is inert while its save is in flight: reverting the box would leave the words being sent unseen. */
  return (
    <div className="next-cockpit-held-footer">
      <span className="next-cockpit-held-tools">
        <AddOutcomeLine />
        <ActionButton
          label="Save intent"
          className="border-[var(--accent)] text-[color:var(--accent)] font-bold px-4 aria-disabled:not-aria-busy:border-solid aria-disabled:not-aria-busy:bg-none aria-disabled:not-aria-busy:text-[color:var(--accent)]"
          busyLabel="Saving…"
          pendingKey={`${key}:save`}
          action="held-save"
          arg="intent"
          inert={!saveLive}
          describedBy={absent.join(' ')}
          focusKey={`${key}:save`}
          onPress={() => void saveIntent(ctx, session)}
        />
        {reopenable ? (
          <ActionButton
            label="Read from now"
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

/* "Saved", without a check mark: a check in this panel reads as a verdict, and "Confirmed" would claim what
   nothing did, since a saved revision is the reader's own words. The store key is in its details because the
   reader may need whose words these are, and the page's title already names the session. */
export function SavedStamp() {
  const { input, session, project } = usePanel();
  const annotation = input.annotation;
  const generated = nextNumber(input.payload['generated']);
  const stamp = discardStamp(annotation, generated);
  const line = stamp ? '' : revisionLine(annotation, generated);
  if (!line) return null;
  const start = nextNumber(annotation?.['window_start']);
  return (
    <Disclosure
      disclosureKey={disclosureKey({
        project,
        scope: compatSessKey(session),
        name: 'held-stamp',
      })}
      summary={`Saved${start !== null && start > 0 ? ` · reads from ${clock(start)}` : ''}`}
      className="next-cockpit-held-stamp"
    >
      <p>Editing the goal or adding a line keeps this start. Read from now moves it.</p>
      <span className="next-cockpit-held-revision">{line}</span>
      <span className="next-cockpit-define">Each save is a revision.</span>
      <span className="next-cockpit-held-bound">{compatSessKey(session)}</span>
    </Disclosure>
  );
}

/* What the retired session More held about the reader's words, reduced to what the design has: the reading's
   start beside the card, and one quiet menu for the rest (the sentence saying drift is measured against these
   words, Clear, how Intent and drift works, the caveats, Discard everything and the state of later
   directions). What became of discarded words stays in the card, because it says what became of the reader's
   words. Each part draws nothing when it has nothing to say.
   [The More inventory](../../../docs/design-reading-a-session.md#where-everything-in-more-went) */
function Kept() {
  const { project, session } = usePanel();
  const menu = disclosureKey({ project, scope: compatSessKey(session), name: 'intent-menu' });
  return (
    <div
      className="flex flex-wrap items-center gap-x-3 gap-y-1 text-label text-muted-foreground [&_.next-session-drift-caveats]:contents [&_.next-cockpit-held-discard]:mt-0 [&_.next-cockpit-held-hint]:flex-initial [&_.next-cockpit-held-hint]:text-label"
      data-next-intent-kept
    >
      <SavedStamp />
      <CaveatNotes />
      <Disclosure
        disclosureKey={menu}
        summary="More"
        summaryLabel="More about these words"
        variant="popover"
        focusKey={`intent-menu:${compatSessKey(session)}`}
      >
        <p className="next-cockpit-held-hint" data-next-intent-measured>
          {INTENT_MEASURED}
        </p>
        <ClearGoal />
        <Caveats />
        <LaterDirections />
        <HowTo />
      </Disclosure>
    </div>
  );
}

export function IntentSection() {
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
            ref={heading}
            tabIndex={-1}
            data-next-focus={`intent:${compatSessKey(session)}`}
          >
            Intent
          </h2>
          <SampleMark id="intent" />
        </span>
        <span className="ms-auto flex flex-wrap items-baseline gap-x-3 gap-y-1">
          {status ? (
            <span
              className={`[font-family:var(--mono)] text-label ${status === 'Saved' || status === DRAFT_UNSAVED ? 'text-muted-foreground' : 'text-[var(--amber)]'}`}
              data-next-intent-status
            >
              {status}
            </span>
          ) : null}
        </span>
      </header>
      <p className="next-cockpit-held-lede text-muted-foreground" data-next-intent-lede>
        {INTENT_LEDE}
      </p>
      {/* Under the heading rather than in its header, so the revision line keeps the sentence tier. */}
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
      <Kept />
    </Card>
  );
}

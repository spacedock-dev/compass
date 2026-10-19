import { SampleMark } from '../sample/SampleMark';
import { Card } from '../ui/card';
import { compatSessKey } from '../api/identity';
import { nextNumber } from '../api/bootstrap';
import { Disclosure, disclosureKey, useFocusKey } from '../controls';
import { clock, endedAt } from '../observed';
import { useDisplayed } from '../shell/context';
import { ActionButton } from './ActionButton';
import { discardStamp, revisionLine, storeUnreadable } from './annotation';
import { heldSentence } from './cues';
import {
  directionLinesQuestion,
  intentChanges,
  intentDrafted,
  intentKey,
  intentStatus,
  noDraftWhy,
} from './derive';
import { undoChanges } from './edit';
import { Caveats, LaterDirections } from './Caveats';
import { ClearGoal, GoalField } from './GoalField';
import { OutcomeLines, AddOutcomeLine } from './OutcomeLines';
import { saveIntent } from './save';
import { ENDED_CAVEAT, INTENT_LEDE, INTENT_MEASURED } from './sentences';
import { usePanel } from './useIntent';
import { HowTo } from './HowTo';

/* Save remains in view over an untouched prompt draft; Undo appears after a goal edit or a pending
   prompt choice. Outcome-only edits retain native undo and Escape without adding a first-view control. */
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
    kind === 'saved' && endedAt(session) !== null ? ENDED_CAVEAT : '',
  ]
    .filter(Boolean)
    .join(' ');
  const question = directionLinesQuestion(ctx.held, session);
  /* Undo is inert while its save is in flight: reverting the box would leave the words being sent unseen. */
  return (
    <div className="next-cockpit-held-footer">
      <AddOutcomeLine />
      <span className="next-cockpit-held-tools">
        <ActionButton
          label="Save intent"
          busyLabel="Saving…"
          pendingKey={`${key}:save`}
          action="held-save"
          arg="intent"
          inert={!((changes.any || changes.adoptable) && !question)}
          describedBy={absent.join(' ')}
          focusKey={`${key}:save`}
          onPress={() => void saveIntent(ctx, session)}
        />
        {changes.goal || changes.pending ? (
          <ActionButton
            label="Undo changes"
            action="held-undo"
            arg="intent"
            inert={!(changes.undoable && !saving)}
            focusKey={`${key}:undo`}
            onPress={() => undoChanges(ctx, input)}
          />
        ) : null}
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
      <p>Adding a line keeps this window; saving new goal words opens another.</p>
      <span className="next-cockpit-held-revision">{line}</span>
      <span className="next-cockpit-define">Each save is a revision.</span>
      <span className="next-cockpit-held-bound">{compatSessKey(session)}</span>
    </Disclosure>
  );
}

/* What the retired session More held about the reader's words, under the save that makes them: the saved
   stamp, the sentence saying drift is measured against these words, Clear, the caveats and Discard
   everything, and the state of later directions. Each part draws nothing when it has nothing to say, so an
   untouched intent adds only the one sentence.
   [The More inventory](../../../docs/design-reading-a-session.md#where-everything-in-more-went) */
function Kept() {
  return (
    <div
      className="flex flex-wrap items-center gap-x-3 gap-y-1 pt-2 border-t border-[var(--rule)] text-label text-muted-foreground [&_.next-session-drift-caveats]:contents [&_.next-cockpit-held-discard]:mt-0 [&_.next-cockpit-held-hint]:flex-initial [&_.next-cockpit-held-hint]:text-label"
      data-next-intent-kept
    >
      <SavedStamp />
      <ClearGoal />
      <p className="next-cockpit-held-hint" data-next-intent-measured>
        {INTENT_MEASURED}
      </p>
      <Caveats />
      <LaterDirections />
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
              className={`[font-family:var(--mono)] text-label ${status === 'Saved' ? 'text-muted-foreground' : 'text-[var(--amber)]'}`}
              data-next-intent-status
            >
              {status}
            </span>
          ) : null}
          <HowTo />
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

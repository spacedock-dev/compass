import { compatSessKey } from '../api/identity';
import { nextNumber } from '../api/bootstrap';
import { Disclosure, disclosureKey } from '../controls';
import { durationSince, endedAt } from '../observed';
import { ActionButton } from './ActionButton';
import { annotationLines, discardAccount } from './annotation';
import { heldSentence, publishedDiscard } from './cues';
import { disarmDiscard, pressDiscard } from './save';
import { discardKey, intentDraft } from './derive';
import { usePanel } from './useIntent';
import { conflictCandidates, workAbsence } from './work';

/* The caveats under the reading: what became of words that were discarded, the offer to discard, and the
   state of later directions that need no answer. The question a later direction asks is drawn in the
   control's place (`DirectionQuestion`), so this block says only the neutral states. */

function useKey(name: string): string {
  const { project, session } = usePanel();
  return disclosureKey({ project, scope: compatSessKey(session), name });
}

/* The block, gated on the annotation alone rather than on a reading existing, so a later direction that
   raises no departure falls out of the layout rather than needing a rule. It sits directly under the reading
   it constrains, below the one control, so the control stays on the first screen.

   The window is the record's own. A direction older than the tail the reader keeps is not in the entries and
   cannot be counted here, so the block says what it read rather than implying it read everything. Three
   states, and the unread one is not silence. */
export function LaterDirections() {
  const { input, session, source, payload } = usePanel();
  const key = useKey('later-direction');
  const annotation = input.annotation;
  const typed = String(annotation?.['goal'] || '').trim() || annotationLines(annotation).length;
  if (!typed) return null;
  const block = (state: string, body: string, className: string) => (
    <section className="next-cockpit-conflict">
      <Disclosure disclosureKey={key} summary={`Later directions: ${state}`}>
        <p className={className}>{body}</p>
        <p className="next-cockpit-conflict-why">
          Nothing here decides whether it changes what you are asking for. That is yours, and
          Compass does not write into the session either way.
        </p>
      </Disclosure>
    </section>
  );
  if (source.state !== 'read' && source.state !== 'empty') {
    return block(
      'unknown (record unread)',
      `${workAbsence(source)} So whether you have given a later direction is unknown, not none.`,
      'next-cockpit-conflict-why',
    );
  }
  const pending = conflictCandidates(
    annotation,
    source.all || source.entries,
    session,
    intentDraft(input),
  );
  if (pending.length) return null;
  const settledAt = nextNumber(annotation?.['settled_at']);
  if (settledAt === null) {
    return block(
      'none',
      'Nothing you have said since you saved these words is in the observed record read for this session.',
      'next-cockpit-conflict-why',
    );
  }
  const generated = nextNumber(payload['generated']);
  const age = durationSince(generated, settledAt);
  return block(
    age === null ? 'settled' : `settled ${age} ago`,
    `You settled this${age === null ? '' : ` ${age} ago`}. A direction given after that will raise it again.`,
    'next-cockpit-conflict-settled',
  );
}

/* The act the endpoint has always had and no control reached. Armed by the first press and performed by the
   second, through the cue lane and its 30 second TTL rather than a dialog. Every sentence here is the
   server's: the success one claims the departure store no longer quotes these words, and the page never reads
   that store, so it must not compose the claim. */
interface DiscardView {
  readonly offer: boolean;
  readonly armed: boolean;
  readonly landed: string;
  readonly warning: string;
  readonly why: string;
}

function discardView(panel: ReturnType<typeof usePanel>): DiscardView | null {
  const { ctx, input, session, payload } = panel;
  const kind = ctx.held.kind(discardKey(session));
  const armed = kind === 'discard-armed';
  const published = publishedDiscard(payload);
  const landed = kind && !armed ? heldSentence(kind, published) : '';
  /* `revision_count` is the length of the store's revisions for a real entry and 0 for none, so the OFFER is
     a measured value and not a structurally-present default: it never offers to discard nothing. The account
     of a discard that already happened is not gated on it, because a landed discard deletes the entry and the
     next payload publishes 0. */
  const offer = (nextNumber(input.annotation?.['revision_count']) ?? 0) > 0;
  if (!offer && !landed) return null;
  return {
    offer,
    armed,
    landed,
    warning: armed ? heldSentence('discard-armed', published) : '',
    why: String(published['why'] || ''),
  };
}

/* What became of discarded words stays on the card, outside the menu that holds the offer to discard. */
export function CaveatNotes() {
  const panel = usePanel();
  const { input, session, payload } = panel;
  const discard = discardView(panel);
  const account = discardAccount(
    input.annotation,
    session['departures'],
    publishedDiscard(payload),
    !discard?.landed,
  );
  if (!account.length && !discard?.landed) return null;
  return (
    <div className="next-session-drift-caveats">
      {account.map((said) => (
        <p key={said} className="next-cockpit-held-absent">
          {said}
        </p>
      ))}
      {discard?.landed ? (
        <div className="next-cockpit-held-discard">
          <small className="next-cockpit-held-cue">{discard.landed}</small>
        </div>
      ) : null}
    </div>
  );
}

/* The armed offer is drawn outside the menu, in the card, from the press that arms it until it is confirmed,
   kept or lapses. In the menu its warning was hidden whenever the menu was closed, which an Escape, a focus
   move or a refresh did, and the menu moved between the first press and the second. Escape keeps the words,
   as the Keep button does. */
export function ArmedDiscard() {
  const panel = usePanel();
  const { ctx, session } = panel;
  const view = discardView(panel);
  if (!view?.offer || !view.armed) return null;
  const key = discardKey(session);
  return (
    <div
      className="next-cockpit-held-discard basis-full"
      role="group"
      aria-label="Discard everything"
      data-next-intent-armed-discard
      onKeyDown={(event) => {
        if (event.key !== 'Escape' || !disarmDiscard(ctx, session)) return;
        event.preventDefault();
        event.stopPropagation();
      }}
    >
      {view.why ? <p className="next-cockpit-held-absent">{view.why}</p> : null}
      <p className="next-cockpit-held-absent" id="next-cockpit-discard-armed">
        {view.warning}
      </p>
      <span className="flex flex-wrap gap-2">
        <ActionButton
          weight="secondary"
          tone="muted"
          strongBorder
          label="Confirm discard"
          busyLabel="Discarding…"
          pendingKey={key}
          action="held-discard"
          focusKey={key}
          describes="next-cockpit-discard-armed"
          onPress={(detail) => pressDiscard(ctx, session, detail)}
        />
        <ActionButton
          weight="secondary"
          label="Keep my words"
          action="held-discard-keep"
          onPress={() => void disarmDiscard(ctx, session)}
        />
      </span>
    </div>
  );
}

function DiscardBlock({ view }: { readonly view: DiscardView }) {
  const { ctx, session } = usePanel();
  const key = discardKey(session);
  const name = useKey('held-discard');
  const { offer, armed, why } = view;
  // While armed, the question is the card's (`ArmedDiscard`), so the menu holds no second copy of it.
  if (!offer || armed) return null;
  return (
    <div className="next-cockpit-held-discard">
      <Disclosure
        disclosureKey={name}
        summary="Discard everything"
        className="next-cockpit-held-discard-offer"
      >
        {why ? <p className="next-cockpit-held-absent">{why}</p> : null}
        <ActionButton
          weight="secondary"
          tone="muted"
          label="Discard everything"
          busyLabel="Discarding…"
          pendingKey={key}
          action="held-discard"
          focusKey={key}
          onPress={(detail) => pressDiscard(ctx, session, detail)}
        />
      </Disclosure>
    </div>
  );
}

/* The ended note and the binding stay in the document but behind one summary: neither is the next thing to
   do. The discard account stays in view, because it says what became of the reader's words. */
export function Caveats() {
  const panel = usePanel();
  const { input, session } = panel;
  const key = useKey('held-saved-about');
  const annotation = input.annotation;
  const ended = endedAt(session) !== null;
  const binding =
    annotation?.['binding_why'] && (annotation['goal'] || annotationLines(annotation).length)
      ? String(annotation['binding_why'])
      : '';
  const discard = discardView(panel);
  if (!(ended || binding) && !discard?.offer) return null;
  return (
    <div className="next-session-drift-caveats">
      {ended || binding ? (
        <Disclosure disclosureKey={key} summary="About these saved words">
          {ended ? (
            <p className="next-cockpit-held-absent">
              This session has ended. Anything you save against it is kept, and nothing is promised
              to read it.
            </p>
          ) : null}
          {binding ? <p className="next-cockpit-held-absent">{binding}</p> : null}
        </Disclosure>
      ) : null}
      {discard?.offer ? <DiscardBlock view={discard} /> : null}
    </div>
  );
}

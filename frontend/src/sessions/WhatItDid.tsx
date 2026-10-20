import { useEffect, useRef, useState } from 'react';
import { contextKey } from '../api/identity';
import { parseOutline } from '../api/outline';
import { useControls } from '../controls';
import { entriesHeld } from '../drift/citations';
import { afterPanelSettles } from '../drift/panelSettle';
import { CitationLink } from '../drift/CitationLink';
import { landOnEntry } from '../drift/jumpToEntry';
import { useDrift } from '../drift/context';
import { SampleMark } from '../sample/SampleMark';
import { useDisplayed, useShell } from '../shell/context';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '../ui/tooltip';
import { Card } from '../ui/card';
import { Disclosure, disclosureKey } from '../controls';
import { SummaryControls, SummaryView } from './SummaryParts';
import { summaryHeader, useOpenSummary, useSummaryState } from './summaryState';
import { fullActivityKey } from './fullActivityKey';
import {
  missingSentence,
  NO_PROMPT,
  OUTLINE_EMPTY,
  OUTLINE_FAILED,
  OUTLINE_LABEL,
  OUTLINE_LOADING,
  outlineStamp,
  outlineView,
  type BlockView,
} from './outline';
import { useSteadyOutline } from './steadyOutline';

export const WHAT_IT_DID_PLACEHOLDER =
  'An outline of what this session did is not drawn here yet. Every entry it recorded is under Full activity below.';

/* An entry chip: its `#n` where the page holds and numbers the entry. Pressing it opens Full activity and lands
   on the entry, reading older record pages for it first when the page does not hold it, as Show cited entries
   does (docs/design-reader-state.md#the-inventory). An entry from before the intent's window keeps its number,
   muted, and says why Analyze does not read it. */
export const OUTSIDE_WINDOW = 'Before your intent’s start; not read by Analyze';
/* A chip never reads as the bare word "entry". An entry with no number says why it has none: counted numbers start
   at the intent's window, so an earlier entry has none to keep, and a message the page has not read yet has none
   until its record page arrives (the press reads for it). */
export const UNNUMBERED_BEFORE = 'before your intent';
export const UNNUMBERED_OLDER = 'older entry';
export function EntryChip({
  id,
  purpose,
  onOpen,
  cite = false,
}: {
  readonly id: string;
  readonly purpose: string;
  readonly onOpen: (id: string, n: string | null) => void;
  /** A citation in a line of text: its number in brackets, as a footnote. Otherwise `#n` in running words. */
  readonly cite?: boolean;
}) {
  const { model } = useDrift();
  const n = model.labels.get(id) ?? null;
  const outside = model.outside.has(id);
  const word = n
    ? cite
      ? `[${n}]`
      : `#${n}`
    : cite
      ? '[?]'
      : outside
        ? UNNUMBERED_BEFORE
        : UNNUMBERED_OLDER;
  const label = `Open ${n ? `entry #${n}` : outside ? 'the entry before your intent’s start' : 'an older entry the page has not read yet'}, ${purpose}, in Full activity${outside ? `. ${OUTSIDE_WINDOW}` : ''}`;
  const marks = {
    'data-next-outline-entry': id,
    'data-next-cockpit-action': 'finding-jump',
    ...(outside ? { 'data-next-entry-outside': '' } : {}),
    ...(n ? {} : { 'data-next-entry-unnumbered': '' }),
  };
  const tone = outside ? ' text-muted-foreground opacity-70' : '';
  const chip = cite ? (
    <CitationLink
      id={id}
      className={tone}
      aria-label={label}
      onJump={() => onOpen(id, n)}
      {...marks}
    >
      {word}
    </CitationLink>
  ) : (
    <a
      href="#"
      className={`text-cite no-underline hover:underline focus-visible:outline-2 focus-visible:outline-solid focus-visible:outline-[var(--accent)] focus-visible:outline-offset-1 font-[family-name:var(--mono)] text-label rounded-control min-h-0 min-w-0${tone}`}
      aria-label={label}
      {...marks}
      onClick={(event) => {
        event.preventDefault();
        onOpen(id, n);
      }}
    >
      {word}
    </a>
  );
  if (!outside) return chip;
  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger render={chip} />
        <TooltipContent>{OUTSIDE_WINDOW}</TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

/* Which entries get a chip. A prompt's id is the record page's own message id, so a prompt the page does not
   hold yet is read for. A check or file id is the outline's own and does not yet name a record row
   (docs/design-session-summary.md#open-questions), so it gets a chip only once the page holds an entry under
   it, and a press never reads pages for an id no page carries. */
function useChips(block: BlockView) {
  const { model } = useDrift();
  const chip = (id: string) => model.byId.has(id) || id === block.promptId;
  return {
    first: chip(block.first),
    last: block.first !== block.last && chip(block.last),
    failure: chip,
  };
}

function Span({
  block,
  onOpen,
}: {
  readonly block: BlockView;
  readonly onOpen: (id: string, n: string | null) => void;
}) {
  const chips = useChips(block);
  if (!chips.first && !chips.last) return null;
  const single = block.first === block.last;
  const first = chips.first ? (
    <EntryChip
      id={block.first}
      purpose={single ? 'this part of the session' : 'where this part starts'}
      onOpen={onOpen}
    />
  ) : null;
  const last = chips.last ? (
    <EntryChip id={block.last} purpose="where this part ends" onOpen={onOpen} />
  ) : null;
  const lead = single ? 'Entry' : first && last ? 'Entries' : first ? 'Starts at' : 'Ends at';
  return (
    <p
      className="m-0 flex flex-wrap items-center gap-x-1 text-label text-muted-foreground"
      data-next-outline-span
    >
      <span>{lead}</span>
      {first}
      {first && last ? <span>to</span> : null}
      {last}
    </p>
  );
}

function Block({
  block,
  onOpen,
}: {
  readonly block: BlockView;
  readonly onOpen: (id: string, n: string | null) => void;
}) {
  const chips = useChips(block);
  return (
    <li
      className="flex flex-col gap-1 border-l-2 border-[var(--rule)] pl-3"
      data-next-outline-block={block.first}
      {...(block.failures.length ? { 'data-next-outline-failed': '' } : {})}
    >
      <p className="m-0 text-body text-foreground [overflow-wrap:anywhere]">
        {block.at ? (
          <span className="mr-2 font-[family-name:var(--mono)] text-label text-muted-foreground">
            {block.at}
          </span>
        ) : null}
        {block.prompt === null ? (
          <span className="text-muted-foreground" data-next-outline-prompt="none">
            {NO_PROMPT}
          </span>
        ) : (
          <q data-next-outline-prompt title={block.promptFull ?? undefined}>
            {block.prompt}
          </q>
        )}
      </p>
      <p className="m-0 text-label text-muted-foreground" data-next-outline-counts>
        {block.counts.join(' · ')}
      </p>
      {block.failures.length ? (
        <ul className="m-0 flex list-none flex-col gap-1 p-0" aria-label="Failures in this part">
          {block.failures.map((failure) => (
            <li
              key={failure.factId}
              className="flex flex-wrap items-center gap-x-2 text-label text-destructive"
              data-next-outline-failure={failure.factId}
            >
              <span className="[overflow-wrap:anywhere]">
                {`Failed as the tool reported: ${failure.title || 'a check'}`}
              </span>
              {chips.failure(failure.factId) ? (
                <EntryChip id={failure.factId} purpose="the failed check" onOpen={onOpen} />
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
      <Span block={block} onOpen={onOpen} />
    </li>
  );
}

/* Long enough for a smooth scroll over a long record to end; short enough that a reader's own scroll after it is
   not mistaken for the landing's. */

/* The What the session has done card: a stable region between the Intent card and the Drift card. Until a
   summary exists it holds Compass's outline, one block per message of the reader's, read from the focused
   context and updated with the board; once one is saved, the summary stands in the slot and the outline is one
   press below it, where every gap points. `data-next-session-summary-controls` holds the summary's notice and
   controls, and is empty where this server publishes no summaries. */
export function WhatItDid({
  running,
  harness,
}: {
  readonly running: boolean;
  readonly harness: string;
}) {
  const { model } = useDrift();
  const { runtime } = useShell();
  const controls = useControls();
  const read = useDisplayed((snapshot) =>
    snapshot.contexts.get(contextKey(model.projectKey, model.session as never)),
  );
  const entry = useSteadyOutline(read, contextKey(model.projectKey, model.session as never));
  const generated = useDisplayed((snapshot) => snapshot.data?.generated);
  const identity = model.identity;
  /* The card's own passive read of the focused context, once per board revision. It is not gated on
     annotations as the Intent card's is: the outline is not an annotation, and with them off nothing else on
     this page reads the context. A repeat for a revision the runtime has settled is a no-op. */
  // biome-ignore lint/correctness/useExhaustiveDependencies: the revision is the refetch trigger, not a value the body reads.
  useEffect(() => {
    if (!identity) return;
    runtime.loadContext({
      projectKey: model.projectKey,
      focus: { harness: identity.harness, sid: identity.sid },
    });
  }, [runtime, model.projectKey, identity?.harness, identity?.sid, generated]);
  const outline = parseOutline(entry?.data);
  const view = outlineView(
    outline,
    { loaded: Boolean(entry?.data), failed: Boolean(entry?.error) && !entry?.data },
    harness,
  );
  /* Which surface the press came from, so the line saying an entry could not be shown stands where it was made:
     the summary, or the outline folded beneath it. */
  const [missing, setMissing] = useState<{
    readonly what: string;
    readonly from: 'summary' | 'outline';
  } | null>(null);
  // The latest press: a read that ends after another press began says nothing about the one now standing.
  const latestPress = useRef<object | null>(null);
  const summary = useSummaryState(entry, running, harness);
  useOpenSummary(summary);
  /* A summary's citations read as numbers, and a message the page has not read yet has none until its record
     page arrives. The pages are read once for the cited messages so the numbers are there before a press. */
  const stored = summary.stored;
  const pending = stored
    ? [
        ...new Set(
          stored.blocks.flatMap((block) =>
            block.phases.flatMap((phase) =>
              phase.bullets.flatMap((bullet) =>
                (bullet.kind === 'said' || bullet.kind === 'asked' ? bullet.cites : []).filter(
                  (id) => !model.byId.has(id),
                ),
              ),
            ),
          ),
        ),
      ]
    : [];
  const prefetched = useRef('');
  // biome-ignore lint/correctness/useExhaustiveDependencies: the joined ids are the trigger; the rest is read once per set.
  useEffect(() => {
    const key = `${model.projectKey}|${model.session}|${pending.join(',')}`;
    if (!identity || !pending.length || prefetched.current === key) return;
    prefetched.current = key;
    const scope = { projectKey: model.projectKey, session: model.session, cited: pending };
    void runtime.resolveRecord({ projectKey: model.projectKey, focus: identity }, (snapshot) =>
      entriesHeld(snapshot, scope),
    );
  }, [runtime, identity, model.projectKey, model.session, pending.join(',')]);
  const stamp = summary.stored
    ? summaryHeader(summary)
    : outline?.state === 'ok'
      ? outlineStamp(entry?.revision ?? null, running, Boolean(entry?.error))
      : '';

  const land = landOnEntry;
  const open = (from: 'summary' | 'outline') => (id: string, n: string | null) => {
    const press = {};
    latestPress.current = press;
    setMissing(null);
    controls.disclosures.set(fullActivityKey(model.project, model.session), true);
    /* After Full activity has finished opening. A smooth scroll begun while its panel still grew was clamped
       at the foot of a page not yet tall enough, and left the row at the bottom edge (top 728 of 729 px). */
    const settle = () =>
      requestAnimationFrame(() => {
        if (latestPress.current !== press) return;
        const panel = document.querySelector('[data-next-full-activity-body]');
        const growing = panel?.getAnimations?.() ?? [];
        void Promise.allSettled(growing.map((animation) => animation.finished)).then(() => {
          afterPanelSettles(() => {
            if (latestPress.current !== press) return;
            if (!land(id)) setMissing({ what: missingSentence(n, model.outside.has(id)), from });
          });
        });
      });
    if (model.byId.has(id) || !identity) {
      settle();
      return;
    }
    const scope = { projectKey: model.projectKey, session: model.session, cited: [id] };
    void runtime
      .resolveRecord({ projectKey: model.projectKey, focus: identity }, (snapshot) =>
        entriesHeld(snapshot, scope),
      )
      .finally(settle);
  };

  return (
    <Card
      variant="drift-panel"
      as="section"
      className="flex flex-col gap-3 px-4 pt-4 pb-4"
      aria-labelledby="next-session-summary-heading"
      data-next-session-summary
    >
      <header className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        {/* The sample's mark beside the heading, outside it, so the card's name stays the heading's words. */}
        <span className="flex items-baseline">
          <h2 id="next-session-summary-heading" className="next-session-drift-heading">
            What the session has done
          </h2>
          <SampleMark id="summary" />
        </span>
        {stamp ? (
          <span
            className="font-[family-name:var(--mono)] text-label text-muted-foreground"
            data-next-outline-stamp
          >
            {stamp}
          </span>
        ) : null}
      </header>
      <div className="flex flex-col gap-2 empty:hidden" data-next-session-summary-controls>
        <SummaryControls state={summary} outline={outlineSize(outline)} />
      </div>
      <div className="flex flex-col gap-3" data-next-session-summary-slot>
        {summary.stored ? (
          <>
            {missing?.from === 'summary' ? <MissingLine missing={missing.what} /> : null}
            <SummaryView
              state={summary}
              startsAt={
                summary.stored.startsAt && model.numbers.get(summary.stored.startsAt)
                  ? `#${model.numbers.get(summary.stored.startsAt) ?? ''}`
                  : ''
              }
              chip={(id, purpose) => (
                <EntryChip id={id} purpose={purpose} onOpen={open('summary')} cite />
              )}
            />
            <Disclosure
              disclosureKey={disclosureKey({
                project: model.project,
                scope: model.key,
                name: 'summary-outline',
              })}
              summary="Compass's outline of this session"
            >
              <Outline
                view={view}
                missing={missing?.from === 'outline' ? missing.what : null}
                onOpen={open('outline')}
              />
            </Disclosure>
          </>
        ) : (
          <Outline
            view={view}
            missing={missing?.from === 'outline' ? missing.what : null}
            onOpen={open('outline')}
          />
        )}
      </div>
    </Card>
  );
}

function Outline({
  view,
  missing,
  onOpen,
}: {
  readonly view: ReturnType<typeof outlineView>;
  readonly missing: string | null;
  readonly onOpen: (id: string, n: string | null) => void;
}) {
  if (view.kind === 'loading')
    return (
      <p className="next-cockpit-define" role="status" data-next-outline="loading">
        {OUTLINE_LOADING}
      </p>
    );
  if (view.kind === 'failed')
    return (
      <p className="next-cockpit-define" data-next-outline="failed">
        {OUTLINE_FAILED}
      </p>
    );
  if (view.kind === 'absent')
    return (
      <p className="next-cockpit-define" data-next-session-summary-empty data-next-outline="absent">
        {WHAT_IT_DID_PLACEHOLDER}
      </p>
    );
  if (view.kind === 'none')
    return (
      <p className="next-cockpit-define" data-next-outline="none">
        {view.sentence}
      </p>
    );
  return (
    <section className="flex flex-col gap-2" aria-label="Outline" data-next-outline="blocks">
      <p
        className="m-0 font-[family-name:var(--mono)] text-label text-muted-foreground"
        data-next-outline-label
      >
        {OUTLINE_LABEL}
      </p>
      {view.notes.map((note) => (
        <p key={note} className="next-cockpit-define" data-next-outline-note>
          {note}
        </p>
      ))}
      {view.empty ? <p className="next-cockpit-define">{OUTLINE_EMPTY}</p> : null}
      {missing ? <MissingLine missing={missing} /> : null}
      {view.blocks.length ? (
        <ol className="m-0 flex list-none flex-col gap-3 p-0">
          {view.blocks.map((block) => (
            <Block key={block.key} block={block} onOpen={onOpen} />
          ))}
        </ol>
      ) : null}
    </section>
  );
}

/* A chip whose entry Full activity could not show, said where the press was made. */
function MissingLine({ missing }: { readonly missing: string }) {
  return (
    <p className="next-cockpit-define" role="status" data-next-outline-missing>
      {missing}
    </p>
  );
}

/* How many entries the outline counted, for the size of a read before a summary plans its parts. */
function outlineSize(outline: ReturnType<typeof parseOutline>): {
  readonly entries: number | null;
  readonly more: boolean;
} {
  if (outline?.state !== 'ok' || !outline.blocks.length) return { entries: null, more: false };
  const entries = outline.blocks.reduce((sum, block) => sum + block.span.entries, 0);
  const partial =
    outline.moreBlocks > 0 ||
    (outline.coverage !== null &&
      (outline.coverage.startOffset > 0 || outline.coverage.unread.length > 0));
  return { entries, more: partial };
}

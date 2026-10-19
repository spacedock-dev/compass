import { useEffect, useRef, useState } from 'react';
import { contextKey } from '../api/identity';
import { parseOutline } from '../api/outline';
import { useControls } from '../controls';
import { entriesHeld } from '../drift/citations';
import { useDrift } from '../drift/context';
import { useDisplayed, useShell } from '../shell/context';
import { Button } from '../ui/button';
import { Card } from '../ui/card';
import { fullActivityKey } from './fullActivityKey';
import {
  NO_PROMPT,
  OUTLINE_EMPTY,
  OUTLINE_FAILED,
  OUTLINE_LABEL,
  OUTLINE_LOADING,
  outlineStamp,
  outlineView,
  type BlockView,
} from './outline';

export const WHAT_IT_DID_PLACEHOLDER =
  'An outline of what this session did is not drawn here yet. Every entry it recorded is under Full activity below.';

/* An entry chip: its `#n` where the page holds and numbers the entry. Pressing it opens Full activity and lands
   on the entry, reading older record pages for it first when the page does not hold it, as Show cited entries
   does (docs/design-reader-state.md#the-inventory). */
function EntryChip({
  id,
  purpose,
  onOpen,
}: {
  readonly id: string;
  readonly purpose: string;
  readonly onOpen: (id: string, n: string | null) => void;
}) {
  const { model } = useDrift();
  const n = model.numbers.get(id) ?? null;
  return (
    <Button
      type="button"
      variant="quiet"
      className="px-2 py-0 font-[family-name:var(--mono)] text-label"
      aria-label={`Open ${n ? `entry #${n}` : 'the entry'}, ${purpose}, in Full activity`}
      data-next-outline-entry={id}
      onClick={() => onOpen(id, n)}
    >
      {n ? `#${n}` : 'entry'}
    </Button>
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

/* The What the session has done card: a stable region between the Intent card and the Drift card. Until a
   summary exists it holds Compass's outline, one block per message of the reader's, read from the focused
   context and updated with the board. `data-next-session-summary-slot` is the hook the outline sits in, and
   `data-next-session-summary-controls` the empty region the summary's controls take beside it. */
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
  const entry = useDisplayed((snapshot) =>
    snapshot.contexts.get(contextKey(model.projectKey, model.session as never)),
  );
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
  const [missing, setMissing] = useState<string | null>(null);
  // The latest press: a read that ends after another press began says nothing about the one now standing.
  const latestPress = useRef<object | null>(null);
  const stamp =
    outline?.state === 'ok'
      ? outlineStamp(entry?.revision ?? null, running, Boolean(entry?.error))
      : '';

  const land = (id: string): boolean => {
    const node = document.querySelector<HTMLElement>(
      `[data-next-cockpit-work] [data-next-entry-id="${CSS.escape(id)}"]`,
    );
    if (!node) return false;
    node.focus({ preventScroll: true });
    node.scrollIntoView({
      behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches
        ? 'instant'
        : 'smooth',
      block: 'center',
    });
    return true;
  };
  const open = (id: string, n: string | null) => {
    const press = {};
    latestPress.current = press;
    setMissing(null);
    controls.disclosures.set(fullActivityKey(model.project, model.session), true);
    const settle = () =>
      requestAnimationFrame(() => {
        if (latestPress.current !== press) return;
        if (!land(id)) setMissing(n ? `entry #${n}` : 'that entry');
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
        <h2 id="next-session-summary-heading" className="next-session-drift-heading">
          What the session has done
        </h2>
        {stamp ? (
          <span
            className="font-[family-name:var(--mono)] text-label text-muted-foreground"
            data-next-outline-stamp
          >
            {stamp}
          </span>
        ) : null}
      </header>
      {/* The summary's own controls (Summarize, what is sent, its notice) arrive here in a later part. */}
      <div className="flex flex-col gap-2 empty:hidden" data-next-session-summary-controls />
      <div className="flex flex-col gap-3" data-next-session-summary-slot>
        <Outline view={view} missing={missing} onOpen={open} />
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
      {missing ? (
        <p className="next-cockpit-define" role="status" data-next-outline-missing>
          {`Full activity does not show ${missing}: it could not be loaded, or it sits in a folded run of checks.`}
        </p>
      ) : null}
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

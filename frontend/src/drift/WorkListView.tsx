import { Card } from '../ui/card';
import { useDrift } from './context';
import { missingCites, WORK_AS_REPORTED } from './sentences';
import {
  foldRuns,
  lastTurnLead,
  newestFirst,
  rowWords,
  rowsByNumber,
  workList,
  type CheckRunModel,
} from './workList';
import { EntryHead } from './EntrySource';
import { afterPanelSettles } from './panelSettle';
import { ActivityLegend } from './ActivityMarks';
import { CheckRun } from './CheckRun';
import { TooltipProvider } from '../ui/tooltip';
import { disclosureKey, useControls } from '../controls';
import { useControlledDisclosureState } from '../controls/useDisclosureState';
import { Why } from './Why';
import {
  useEffect,
  useLayoutEffect,
  useRef,
  useSyncExternalStore,
  type KeyboardEvent,
  type ReactNode,
} from 'react';
import { Button } from '../ui/button';
import { contextKey } from '../api/identity';
import { parseFocusedSummary } from '../api/summary';
import { activityStamp, entryWindow, personAuthored, recordPastWindow } from '../intent/work';
import { useDisplayed, useShell } from '../shell/context';
import { ShowMore } from './ShowMore';
import { ACTIVITY_LOG_FILTER_LABELS, GLOSSARY } from '../language/glossary';
import { fullActivityKey, TECHNICAL_EVIDENCE } from '../sessions/fullActivityKey';
import { readingCitationIds } from './citations';
import { summaryCitationIds } from '../sessions/summary';
import { agentMessage, evidenceAt } from './shape';
import type { WorkRow } from './workList';
import { cn } from '../lib/utils';

type ActivityFilter = keyof typeof ACTIVITY_LOG_FILTER_LABELS;
const filters = Object.keys(ACTIVITY_LOG_FILTER_LABELS) as ActivityFilter[];

function matchesFilter(row: WorkRow, filter: ActivityFilter, cited: ReadonlySet<string>): boolean {
  const { entry } = row;
  switch (filter) {
    case 'all':
      return true;
    case 'you':
      return personAuthored(entry);
    case 'agent':
      return agentMessage(entry);
    case 'commands':
      return (
        (entry.type === 'tool_report' &&
          ['command', 'ci_command', 'check'].includes(entry.subject)) ||
        (entry.work && entry.type === 'result' && entry.subject === 'check')
      );
    case 'files':
      return entry.type === 'tool_report' && entry.subject === 'write';
    case 'cited':
      return cited.has(entry.id);
  }
}

function HeldCheckRun({
  run,
  project,
  scope,
  turn,
  children,
}: {
  readonly run: CheckRunModel;
  readonly project: string;
  readonly scope: string;
  readonly turn: string | null;
  readonly children: ReactNode;
}) {
  const controls = useControls();
  // The newest end grows during work; the oldest member keeps the reader's opening attached to this run.
  // docs/design-reader-state.md#the-inventory owns this identity and its lifetime.
  const key = disclosureKey({ project, scope, name: `check-run:${run.last.entry.id}` });
  const open = useControlledDisclosureState(controls.disclosures, key);
  return (
    <CheckRun
      run={run}
      turn={turn}
      open={open}
      onOpenChange={(value, details) => {
        if (details.reason === 'trigger-press') controls.noteToggle();
        controls.disclosures.set(key, value);
      }}
    >
      {children}
    </CheckRun>
  );
}

function land(node: HTMLElement): void {
  if (!node.isConnected || node.closest('[hidden]')) return;
  node.focus({ preventScroll: true });
  node.scrollIntoView({
    behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth',
    block: 'center',
  });
}

/* The numbered activity list in technical details. The record's footer is tiered: where the harness's work
   results are read, one clause stays in view and the mix, the bounds, the scan and the full limit sit behind
   "About this record"; where none are read, the limit is the absence and stays in view. The route's
   tool-output sentence is not repeated here: "What is sent" beside the control owns it.

   Newest first: the rows are drawn from the last entry to the first, so a reader opens on what just happened.
   The numbers stay the ones the list assigns oldest-first, which every "#<n>" on the page and every citation
   names, so the column reads #32 down to #1. */
export function WorkListView() {
  const { model, finding, jump, jumpMissing, entryJump } = useDrift();
  const { runtime, controls } = useShell();
  const filterKey = fullActivityKey(model.project, model.session);
  const filterStore = controls.activityLogFilters;
  const savedFilter = useSyncExternalStore(filterStore.subscribe, () =>
    filterStore.read(filterKey),
  );
  const filter = filters.find((choice) => choice === savedFilter) ?? 'all';
  const focusedKey = contextKey(model.projectKey, model.identity);
  const record = useDisplayed((snapshot) => snapshot.records.get(focusedKey));
  const focused = useDisplayed((snapshot) => snapshot.contexts.get(focusedKey));
  const summary = parseFocusedSummary(focused?.data)?.summary;
  const harness = model.identity?.harness;
  const sid = model.identity?.sid;
  useEffect(() => {
    if (!harness || !sid) return;
    return runtime.openRecord({ projectKey: model.projectKey, focus: { harness, sid } });
  }, [runtime, model.projectKey, harness, sid]);
  /* The newest page again whenever the session's published activity changes: the opening read is a snapshot,
     and the board's context only reaches back over the newest 400 KB of the transcript, so without this an
     entry that arrives and then leaves that tail is held nowhere and drops off the list, taking every number
     above it along. docs/design-reader-state.md#the-inventory owns the lifetime. */
  const stamp = activityStamp(model.session, model.generated);
  /* The revision is called every time, and the loader reads only for a new stamp or to retry a read that went
     unanswered, so a transient failure on a session's last write is tried again on the next poll. */
  // biome-ignore lint/correctness/useExhaustiveDependencies: the revision is the retry trigger, not a value the body reads.
  useEffect(() => {
    if (!harness || !sid) return;
    void runtime.refreshRecord({ projectKey: model.projectKey, focus: { harness, sid } }, stamp);
  }, [runtime, model.projectKey, harness, sid, stamp, model.generated]);
  const panel = useRef<HTMLDivElement>(null);
  const jumped = useRef<object | null>(null);
  const noted = useRef<object | null>(null);
  const pagingFocus = useRef<{ button: HTMLElement; before: ReadonlySet<string> } | null>(null);
  const opened = entryWindow(model.session, model.payload);
  const pastWindow = recordPastWindow(record, opened);
  const beforeWindow = ({ entry }: WorkRow) => {
    const time = evidenceAt(entry);
    return opened !== null && time !== null && time > 0 && time < opened;
  };
  const readMore = () => {
    if (!model.identity || pastWindow) return;
    const before = new Set(list.rows.map((row) => row.entry.id));
    const button = panel.current?.querySelector<HTMLElement>('[data-record-more]');
    if (button && document.activeElement === button) pagingFocus.current = { button, before };
    // An appended older page stays below the existing rows. Focus must never scroll that page into view.
    void runtime.readMoreRecord({ projectKey: model.projectKey, focus: model.identity });
  };
  /* Back to the control the jump was pressed on, or, when a redraw replaced it, the one that names the same
     finding now. */
  const press = jump ?? jumpMissing?.press ?? null;
  const back = () => {
    if (!press) return;
    const returnToFinding = () => {
      const root = press.fromTechnicalEvidence
        ? document.querySelector('[data-next-technical-evidence]')
        : document.querySelector('[data-next-drift-body]');
      const finding = `[data-next-cockpit-action="finding-jump"][data-next-finding="${CSS.escape(press.key)}"]`;
      const origin = press.origin?.isConnected
        ? press.origin
        : (root?.querySelector<HTMLElement>(
            `${finding}[data-next-cite="${CSS.escape(press.entry ?? '')}"]`,
          ) ?? root?.querySelector<HTMLElement>(finding));
      if (origin) land(origin);
    };
    if (press.fromTechnicalEvidence) {
      controls.technicalTabs.remember(filterKey, TECHNICAL_EVIDENCE);
      requestAnimationFrame(() => afterPanelSettles(returnToFinding));
    } else {
      returnToFinding();
    }
  };
  const backOnEscape = (event: KeyboardEvent<HTMLElement>) => {
    if (event.key !== 'Escape' || event.target !== event.currentTarget) return;
    event.preventDefault();
    back();
  };
  const backButton = press ? (
    <Button
      type="button"
      variant="bare"
      className="inline border-[var(--line-hi)] underline"
      data-next-jump-back
      onClick={back}
      onKeyDown={(event) => {
        // Inside the row or the note, so the page's own Escape (back to the session's home) must not see it.
        if (event.key !== 'Escape') return;
        event.preventDefault();
        back();
      }}
    >
      Back to the finding
    </Button>
  ) : null;
  const cited = new Set([...readingCitationIds(model), ...summaryCitationIds(summary)]);
  const list = workList({
    session: model.session,
    payload: model.payload,
    source: model.source,
    annotation: model.annotation,
    draft: model.draft,
    cited: model.cited,
    generated: model.generated,
  });
  useLayoutEffect(() => {
    const request = pagingFocus.current;
    if (
      !request ||
      record?.status === 'loading' ||
      (record?.status === 'stale' && record.error === null) ||
      !panel.current
    )
      return;
    pagingFocus.current = null;
    if (document.activeElement !== request.button && document.activeElement !== document.body)
      return;
    const retained = panel.current.querySelector<HTMLElement>('[data-record-more]');
    const firstNew = [...panel.current.querySelectorAll<HTMLElement>('[data-next-entry-id]')].find(
      (row) => !request.before.has(row.dataset['nextEntryId'] ?? ''),
    );
    const boundary = panel.current.querySelector<HTMLElement>('[data-record-stop]');
    (retained ?? firstNew ?? boundary)?.focus({ preventScroll: true });
  }, [record]);
  const ordered = rowsByNumber(list.rows);
  const shown = newestFirst(ordered).filter((row) => matchesFilter(row, filter, cited));
  const reveal = entryJump ?? jump;
  const explicitId = entryJump?.id ?? jump?.entry ?? null;
  const requested = new Set(explicitId === null ? finding?.citedIds : [explicitId]);
  const hasTarget = ordered.some((row) => requested.has(row.entry.id));
  const targetId = shown.find((row) => requested.has(row.entry.id))?.entry.id;
  const adjusted = useRef<typeof reveal>(null);
  useLayoutEffect(() => {
    if (!reveal || adjusted.current === reveal || !hasTarget) return;
    adjusted.current = reveal;
    if (targetId === undefined) filterStore.forget(filterKey);
  }, [reveal, hasTarget, targetId, filterStore, filterKey]);
  const visibleIds = new Set(shown.map((row) => row.entry.id));
  const datedEarlier = shown.filter(beforeWindow);
  // A filtered count has one visible row per match. All keeps the record's compact command groups.
  const items =
    filter === 'all'
      ? foldRuns(
          shown,
          new Set([
            ...requested,
            ...(finding?.citedIds ?? []),
            ...datedEarlier.map((row) => row.entry.id),
          ]),
        )
      : shown.map((row) => ({ kind: 'row' as const, row }));
  const turnLead = lastTurnLead(
    ordered.filter((row) => visibleIds.has(row.entry.id)),
    items,
  );
  /* A finding press lands once the requested row is visible. A finished read with no drawn target
     leaves focus on the sentence that explains where it stopped. */
  useEffect(() => {
    if (jump && jumped.current !== jump && targetId !== undefined) {
      const target = panel.current?.querySelector<HTMLElement>(
        `[data-next-entry-id="${CSS.escape(targetId)}"]`,
      );
      if (target && !target.closest('[hidden]')) {
        let cancelled = false;
        afterPanelSettles(() => {
          if (cancelled || !target.isConnected || target.closest('[hidden]')) return;
          jumped.current = jump;
          land(target);
        });
        return () => {
          cancelled = true;
        };
      }
    }
    if (
      !jumpMissing ||
      noted.current === jumpMissing ||
      jumped.current === jumpMissing.press ||
      (jump && hasTarget)
    )
      return;
    const note = panel.current?.querySelector<HTMLElement>('[data-next-jump-missing]');
    if (!note) return;
    noted.current = jumpMissing;
    land(note);
  }, [jump, jumpMissing, targetId, hasTarget]);
  const hidden = ordered.length - shown.length;
  const countKnown = ordered.length > 0 || model.source.state === 'empty';
  const partial = record?.reachedStart !== true;
  const count = (size: number) => `${size} ${size === 1 ? 'entry' : 'entries'}`;
  const hasChecks = list.rows.some((row) => 'check' in row.head && row.head.check);
  const about = (
    <>
      {hasChecks ? <ActivityLegend /> : null}
      {list.mix ? <p className="next-cockpit-work-mix">{list.mix}</p> : null}
      {list.checks ? <p className="next-cockpit-work-checks">{list.checks}</p> : null}
      {list.bound ? <p className="next-cockpit-work-dropped">{list.bound}</p> : null}
      {list.reads ? <p className="next-cockpit-work-limit">{list.limit}</p> : null}
    </>
  );
  const hasAbout = Boolean(hasChecks || list.mix || list.checks || list.bound || list.reads);
  return (
    <TooltipProvider>
      <Card
        ref={panel}
        variant="work-panel"
        as="section"
        className="next-cockpit-work px-0"
        data-next-cockpit-work
      >
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="m-0 text-value font-semibold">
            {GLOSSARY.activityLog.plain}
            {countKnown ? ` · ${count(ordered.length)}${partial ? ' loaded' : ''}` : null}
          </h3>
          <div className="flex flex-wrap gap-2" role="group" aria-label="Filter activity log">
            {filters.map((choice) => (
              <Button
                key={choice}
                type="button"
                variant="filter-option"
                className="rounded-pill aria-pressed:bg-[var(--ink)] aria-pressed:text-[var(--raise)]"
                aria-pressed={filter === choice}
                disabled={!countKnown}
                onClick={() =>
                  choice === 'all'
                    ? filterStore.forget(filterKey)
                    : filterStore.remember(filterKey, choice)
                }
              >
                {ACTIVITY_LOG_FILTER_LABELS[choice]}
              </Button>
            ))}
          </div>
        </div>
        {countKnown && filter !== 'all' ? (
          <p className="next-cockpit-work-limit" role="status">
            {count(hidden)} hidden
          </p>
        ) : null}
        {list.anchor ? <p className="next-cockpit-work-anchor">{list.anchor}</p> : null}
        {jumpMissing ? (
          <p
            className="next-cockpit-work-absent"
            role="status"
            tabIndex={-1}
            data-next-jump-missing
            onKeyDown={backOnEscape}
          >
            {missingCites(jumpMissing.count, jumpMissing.reason)} {backButton}
          </p>
        ) : null}
        {list.unnumbered ? <p className="next-cockpit-work-absent">{list.unnumbered}</p> : null}
        {shown.length ? (
          <div className="next-cockpit-work-rows" role="list">
            {items.map((item) => {
              const renderRow = (row: (typeof list.rows)[number]) => {
                const { entry } = row;
                const type = entry.type;
                const before = beforeWindow(row);
                const highlighted = finding?.citedIds.includes(entry.id) === true;
                return (
                  <div
                    key={entry.id}
                    className={cn(
                      'next-cockpit-work-row border-t border-t-[var(--rule)] border-l-0 py-1',
                      before && 'text-muted-foreground',
                      before && !highlighted && 'bg-muted',
                      highlighted &&
                        'border-l-[3px] border-l-[var(--accent)] pl-[7px] rounded-r-control bg-[color-mix(in_srgb,var(--accent)_13%,transparent)]',
                    )}
                    data-next-cited={highlighted ? '' : undefined}
                    role="listitem"
                    data-before-window={before ? '' : undefined}
                    data-next-cockpit-work-type={type}
                    {...(row.n === null ? {} : { 'data-next-entry': String(row.n) })}
                    data-next-entry-id={entry.id}
                    data-next-entry-words={
                      'report' in row.head ? row.head.report : `${row.head.actor}${row.head.type}`
                    }
                    data-next-entry-turn={row.turn ? 'true' : undefined}
                    tabIndex={-1}
                    onKeyDown={highlighted ? backOnEscape : undefined}
                  >
                    <span className="next-cockpit-work-n">
                      {row.n === null ? (
                        <span className="next-visually-hidden">not numbered</span>
                      ) : (
                        `#${String(row.n)}`
                      )}
                    </span>
                    <div className="next-cockpit-work-body">
                      <EntryHead
                        row={row}
                        turnRange={turnLead?.id === entry.id ? turnLead.range : null}
                        project={model.project}
                        scope={model.key}
                        summary={
                          entry.modelDerived ? (
                            <em className="next-cockpit-work-derived">{rowWords(entry)}</em>
                          ) : (
                            <span
                              className={`next-cockpit-work-summary ${type === 'tool_report' ? '[font-family:var(--mono)]' : ''}`}
                            >
                              {rowWords(entry)}
                            </span>
                          )
                        }
                      />
                      {before ? (
                        <span className="text-label text-muted-foreground">
                          Before reading window
                        </span>
                      ) : null}
                      {highlighted && finding ? (
                        <p className="next-cockpit-reading-evidence" data-next-finding-entry>
                          {`Cited for “${finding.detail || finding.clause || finding.label}” · ${row.n === null ? 'Entry not numbered in this view' : `#${String(row.n)}`}`}
                        </p>
                      ) : null}
                      {highlighted && backButton ? (
                        <span className="self-start">{backButton}</span>
                      ) : null}
                    </div>
                  </div>
                );
              };
              return item.kind === 'row' ? (
                renderRow(item.row)
              ) : (
                <div key={item.last.entry.id} role="listitem">
                  <HeldCheckRun
                    run={item}
                    project={model.project}
                    scope={model.key}
                    turn={turnLead?.run === item.last.entry.id ? turnLead.range : null}
                  >
                    {item.rows.map(renderRow)}
                  </HeldCheckRun>
                </div>
              );
            })}
          </div>
        ) : list.rows.length ? (
          <p className="next-cockpit-work-absent">No loaded entries match this filter.</p>
        ) : list.unnumbered ? null : (
          <p className="next-cockpit-work-absent">{list.absent}</p>
        )}
        {datedEarlier.length ? (
          <p className="next-cockpit-work-limit">
            A progress check for your current goal leaves out entries before the reading window.
          </p>
        ) : null}
        <ShowMore
          {...(record ? { record } : {})}
          pastWindow={pastWindow}
          ordinals={list.ordinals}
          onMore={readMore}
        />
        {list.reads ? (
          <p className="next-cockpit-work-limit next-cockpit-work-reported">{WORK_AS_REPORTED}</p>
        ) : (
          <p className="next-cockpit-work-limit">{list.limit}</p>
        )}
        {hasAbout ? (
          <Why name="work-about" summary="About this record">
            {about}
          </Why>
        ) : null}
      </Card>
    </TooltipProvider>
  );
}

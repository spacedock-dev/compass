import { Icon, SESSION_STATE_ICONS } from '../ui/icons';
import { groupName, groupOf, nestRows } from './declared';
import { RelationshipLabels } from './DeclaredRelationships';
import { Card } from '../ui/card';
import { titleLink } from '../ui/link';
import { Button } from '../ui/button';
import { Badge } from '../ui/badge';
import { StatusTile } from '../ui/status-tile';
import { TooltipProvider } from '../ui/tooltip';
import { SESSION_ROW_WORDS } from '../language/glossary';
import { Fragment, memo, useDeferredValue, useEffect, useMemo, useRef } from 'react';
import { IntentHowTo } from '../intent/HowTo';
import { CapacityStrip } from '../capacity';
import { Disclosure, disclosureKey } from '../controls';
import { gapNames, isRecord, sessionStateLimit, trimmed, type Row } from '../observed';
import { nextNumber } from '../api/bootstrap';
import { selectObserved } from '../observed/select';
import { selectHarnessSources } from '../store/selectors';
import { useDisplayed, useShell } from '../shell/context';
import { windowHours } from '../shell/derive';
import { datedClock } from '../observed/values';
import type { TimerHandle } from '../transport/ports';
import { RouteAnchor } from './RouteAnchor';
import {
  announcement,
  applyFilters,
  EMPTY_FILTERS,
  groupEmptyLine,
  harnessMeta,
  indexScreen,
  prepare,
  type Filtered,
  type FilterState,
} from './filters';
import { useFilterState } from './filterStore';
import {
  SEARCH_KEY,
  SessionsFilters,
  type FilterActions,
  type FilterBoard,
} from './SessionsFilters';
import {
  analysisAvailable,
  buildSessionsScreen,
  NOT_CHECKED,
  readingDeparts,
  rowState,
  type SessionRow,
} from './rows';
import { assignmentOf, type PromptCandidate } from './intent';
import { goalFocusFor } from './heldState';
import { worktreeLabel } from './worktree';
import {
  BOARD_WHY,
  DUPLICATE_LABEL_LIMIT,
  GOAL_SOURCES_OFF,
  GOAL_SOURCES_ON,
  RECENT_WHY,
  SCAN_ONLY_NOTE,
  UNREAD_SOURCE_NOTE,
} from './notes';
import './sessions.css';

/* The Sessions screen: one row per exact session, the blocked and moving ones first, each with the goal
   it was given and whether it has drifted. A pure render of one payload: every figure comes from the
   model read from the rows being drawn, so the fleet facts, the groups and the header cannot disagree.
   Nothing here fetches, polls or acts; a row's controls act only when pressed. */

const SESSION_LEGEND = [
  ...Object.entries(SESSION_STATE_ICONS),
  [SESSION_ROW_WORDS.worthALook, 'worth-a-look'],
] as const;

function StatusLegend() {
  return (
    <section className="mt-3 text-label text-muted-foreground">
      <h2 id="sessions-icon-legend" className="font-semibold">
        What the icons mean
      </h2>
      <ul aria-labelledby="sessions-icon-legend" className="flex flex-wrap gap-x-4 gap-y-1">
        {SESSION_LEGEND.map(([word, icon]) => (
          <li key={word} className="inline-flex items-center gap-2">
            <Icon name={icon} />
            {word}
          </li>
        ))}
      </ul>
    </section>
  );
}

function Fact({
  kind,
  label,
  value,
  detail = '',
  tone = '',
}: {
  readonly kind: string;
  readonly label: string;
  readonly value: string;
  readonly detail?: string;
  readonly tone?: string;
}) {
  return (
    <span
      className={tone ? `next-operation-fact next-operation-fact--${tone}` : 'next-operation-fact'}
      data-next-operation-fact={kind}
    >
      <small>{label}</small>
      <strong {...(tone === 'unknown' ? { className: 'next-absence' } : {})}>{value}</strong>
      {/* A held question can run to 2,000 characters: the row shows its opening, the session page all of it. */}
      {detail ? <em className="line-clamp-3">{detail}</em> : null}
    </span>
  );
}

/* A fact is toned only while it is known: an unknown value is a stated absence and wears `.next-absence`,
   so "not published" never reads as a quieter version of a value. */
function ObservedFact({
  kind,
  label,
  text,
  known,
  note = '',
  tone = '',
}: {
  readonly kind: string;
  readonly label: string;
  readonly text: string;
  readonly known: boolean;
  readonly note?: string;
  readonly tone?: string;
}) {
  return (
    <Fact kind={kind} label={label} value={text} detail={note} tone={known ? tone : 'unknown'} />
  );
}

function Identity({ row, hints }: { readonly row: SessionRow; readonly hints: readonly string[] }) {
  const { session, source, history } = row;
  const assignment = history ? '' : assignmentOf(source);
  const names = source ? gapNames(source) : [];
  const state = rowState(session);
  const limit = sessionStateLimit(session, state);
  const tile = state !== 'State not published' && state !== 'Waiting on child';
  return (
    <div className="next-operation-identity flex items-start gap-3 pl-3">
      {tile ? <StatusTile state={state} live={session.isLive && state === 'Working'} /> : null}
      <div className="min-w-0">
        <RouteAnchor
          route={row.route}
          className={`next-operation-route block ${titleLink}`}
          label={`Open session ${session.titleText}`}
          focusKey={`sessions-row:${row.key}`}
          fallback={SEARCH_KEY}
        >
          <strong
            className={`mt-0 font-semibold${session.titleKnown ? '' : ' next-operation-title--unknown next-absence'}`}
          >
            {session.titleText}
          </strong>
          <span className="next-operation-harness block text-label text-muted-foreground">
            {row.harnessLabel}
          </span>
        </RouteAnchor>
        {limit && state !== 'Waiting on child' ? (
          <span
            className="next-operation-scan-only"
            title={session.scanOnly ? SCAN_ONLY_NOTE : undefined}
            data-next-row-state={tile ? undefined : state}
          >
            {limit}
          </span>
        ) : null}
        {!session.titleKnown && session.promptKnown ? (
          <span className="next-operation-assignment block">{`LAST PROMPT · ${session.promptText}`}</span>
        ) : null}
        <RelationshipLabels
          source={source}
          relations={row.relations}
          waitingIsState={state === 'Waiting on child'}
          focusScope={`sessions-row:${row.key}`}
          fallback={SEARCH_KEY}
        />
        {hints.map((hint) => (
          <span
            key={hint}
            className="mt-1 block text-label leading-[1.5] text-muted-foreground"
            data-next-row-hint
          >
            {hint}
          </span>
        ))}
        {assignment ? (
          <span className="next-operation-assignment block">{`Current task · ${assignment}`}</span>
        ) : null}
        {session.sharedLabelKnown ? (
          <span className="next-operation-collision block" title={DUPLICATE_LABEL_LIMIT}>
            {session.sharedLabelText}
          </span>
        ) : null}
        {names.length ? (
          <span className="next-operation-unread" title={UNREAD_SOURCE_NOTE}>
            {`Source not fully read: ${names.join(', ')}`}
          </span>
        ) : null}
      </div>
    </div>
  );
}

function GoalCellView({ row }: { readonly row: SessionRow }) {
  const shell = useShell();
  const { goal } = row;
  if (goal.kind === 'off')
    return <Fact kind="goal" label="GOAL" value={goal.text} tone="unknown" />;
  const onGoal = () =>
    goalFocusFor(shell.controls).request({ harness: row.session.harness, sid: row.session.sid });
  return (
    <span className="next-operation-fact" data-next-operation-fact="goal">
      <small>{goal.label}</small>
      <RouteAnchor
        route={row.route}
        /* A goal holds 1,000 characters since 2026-10-27: the list shows three lines, the session page the rest. */
        className={
          goal.known
            ? 'next-operation-goal-link line-clamp-3'
            : 'next-operation-goal-link line-clamp-3 next-absence'
        }
        extra={{ 'data-next-goal-focus': '' }}
        before={onGoal}
        focusKey={`sessions-row-goal:${row.key}`}
        fallback={SEARCH_KEY}
      >
        {goal.text}
      </RouteAnchor>
    </span>
  );
}

const PROGRESS_SLOT =
  'next-operation-progress col-span-full max-w-full self-start justify-self-start px-3 pb-2 text-left [overflow-wrap:anywhere] min-[1101px]:[grid-area:1/-2/2/-1] min-[1101px]:justify-self-end min-[1101px]:pt-[13px] min-[1101px]:pb-0 min-[1101px]:text-right';

const PROGRESS_WORDS = {
  medium: SESSION_ROW_WORDS.slightlyOffCourse,
  high: SESSION_ROW_WORDS.offCourse,
} as const;

const PROGRESS_ABSENCES = {
  not_enough: SESSION_ROW_WORDS.tooEarlyToTell,
  cant_tell: SESSION_ROW_WORDS.cantTell,
  goal_unclear: SESSION_ROW_WORDS.goalTooVague,
  out_of_date: SESSION_ROW_WORDS.outOfDate,
} as const;

function progressAbsence(source: Row, result: unknown): string | null {
  if (typeof result === 'string' && Object.hasOwn(PROGRESS_ABSENCES, result)) {
    return PROGRESS_ABSENCES[result as keyof typeof PROGRESS_ABSENCES];
  }
  if (result != null || source['annotation_assessment'] || source['annotation_reading_refused']) {
    return null;
  }
  if (!trimmed(source['annotation_goal'])) return SESSION_ROW_WORDS.noGoalYet;
  const checked =
    source['departure_checked'] === true ||
    (nextNumber(source['annotation_reading_count']) ?? 0) > 0;
  return checked ? null : SESSION_ROW_WORDS.notCheckedYet;
}

function Progress({ row, enabled }: { readonly row: SessionRow; readonly enabled: boolean }) {
  const { source, session } = row;
  if (!enabled || !source || (session.harness !== 'claude' && session.harness !== 'codex')) {
    return null;
  }
  const result = source['stored_progress'];
  const raw = source['annotation_assessment'];
  const current =
    isRecord(raw) &&
    nextNumber(raw['revision_read']) !== null &&
    nextNumber(raw['revision_read']) === nextNumber(source['annotation_revision']) &&
    raw['scope'] !== 'withdrawn' &&
    source['annotation_not_accurate'] !== true;
  if (
    (result === 'medium' || result === 'high') &&
    session.harness === 'claude' &&
    current &&
    readingDeparts(source)
  ) {
    return (
      <span className={PROGRESS_SLOT}>
        <Badge variant="progress" tone={result} data-next-row-drift-level={result}>
          {PROGRESS_WORDS[result]}
        </Badge>
      </span>
    );
  }
  const absence = progressAbsence(source, result);
  return absence ? (
    <span
      className={`${PROGRESS_SLOT} [font-family:var(--sans)] text-label text-muted-foreground`}
      data-next-row-progress-absence
    >
      {absence}
    </span>
  ) : null;
}

const NO_HINTS: readonly string[] = [];

/* Memoized with `Group`, so the urgent render a keystroke makes, which still holds the deferred result,
   passes every row the same props and redraws none of them. */
const RowView = memo(function RowView({
  row,
  hints = NO_HINTS,
  depth = 0,
  progressEnabled,
}: {
  readonly row: SessionRow;
  readonly hints?: readonly string[];
  readonly depth?: number;
  readonly progressEnabled: boolean;
}) {
  const { session, history } = row;
  const nowKind = 'NOW';
  const outcome = session.outcomeKnown ? (
    <span className={`next-operation-outcome next-operation-outcome--${session.tone}`}>
      {session.outcomeIcon ? (
        <Icon name={session.outcomeIcon} className="mr-1 inline-block align-text-bottom" />
      ) : null}
      {session.outcomeText}
      <span
        className={
          session.gitKnown
            ? 'next-operation-outcome'
            : 'next-operation-outcome next-operation-outcome--unknown'
        }
      >
        {session.gitText}
      </span>
    </span>
  ) : null;
  const now = (
    <ObservedFact
      kind="now"
      label={nowKind}
      text={session.nowText}
      known={session.nowKnown}
      note={row.endedSince}
    />
  );
  return (
    <Card
      as="article"
      variant="session-row"
      className={`next-operation-row relative cursor-pointer no-underline next-operation-row--${session.tone}${depth ? ' ml-4 w-auto border-l-2 border-l-border' : ''}`}
      {...(depth ? { 'data-declared-depth': depth } : {})}
      data-next-harness={session.harness}
      data-next-session={session.sid}
      {...(history ? { 'data-next-operation-history': 'true' } : {})}
    >
      <Identity row={row} hints={hints} />
      <Progress row={row} enabled={progressEnabled} />
      {/* The project label alone: "Exact location not published" sat hatched on every row and read as an
          error, for a location no harness publishes here. */}
      <Fact
        kind="where"
        label="PROJECT"
        value={session.project}
        detail={worktreeLabel(row.source)}
      />
      <GoalCellView row={row} />
      {history ? (
        <>
          <div className="next-operation-history-now">
            {now}
            {outcome}
          </div>
        </>
      ) : (
        <>
          {now}
          <ObservedFact
            kind="next"
            label="NEXT"
            text={session.nextText}
            known={session.nextKnown}
          />
          <ObservedFact
            kind="blocked"
            label={`BLOCKED${row.responsibility}`}
            text={session.blockText}
            known={session.blockKnown}
            note={session.blockNote}
            tone={session.isNeeds || session.askKnown ? 'blocked' : 'clear'}
          />
          {outcome ? <div className="next-operation-end-note">{outcome}</div> : null}
        </>
      )}
    </Card>
  );
});

const Group = memo(function Group({
  kind,
  title,
  label,
  rows,
  empty,
  caveat,
  filter,
  byGroup = false,
  progressEnabled,
}: {
  readonly byGroup?: boolean;
  readonly progressEnabled: boolean;
  readonly kind: 'active' | 'history';
  readonly title: string;
  readonly label: string;
  readonly rows: readonly SessionRow[];
  readonly empty: string;
  readonly caveat?: { readonly summary: string; readonly body: string };
  /** Set while the reader's filters are on: what they keep of this group, and how to take them off. */
  readonly filter?: {
    readonly filtered: Filtered;
    readonly onClear: () => void;
  };
}) {
  const kept = filter?.filtered.active
    ? rows.filter((row) => filter.filtered.keys.has(row.key))
    : rows;
  const buckets = byGroup
    ? [...new Set(kept.map((row) => groupOf(row.source)))]
        .sort((a, b) => (a ? (b ? a.localeCompare(b, 'en') : -1) : 1))
        .map((group) => ({ group, rows: kept.filter((row) => groupOf(row.source) === group) }))
    : [{ group: '', rows: kept }];
  return (
    <section
      className={`next-operation-group next-operation-group--${kind} [--operation-progress-track:0px] data-[next-progress-enabled]:[--operation-progress-track:176px]`}
      data-next-operation-group={kind}
      data-next-progress-enabled={progressEnabled ? true : undefined}
    >
      <header>
        <h2>{title}</h2>
        {label ? <p>{label}</p> : null}
        {caveat ? (
          <Disclosure
            disclosureKey={disclosureKey({
              project: null,
              scope: null,
              name: `sessions-${kind}-why`,
            })}
            summary={caveat.summary}
            variant="popover"
          >
            <p className="next-why-body">{caveat.body}</p>
          </Disclosure>
        ) : null}
      </header>
      {/* A sibling after the header, never inside it, so a filtered header reads exactly as an unfiltered one. */}
      {filter?.filtered.active && rows.length ? (
        <p
          className="m-0 flex flex-wrap items-center gap-x-2 text-body text-muted-foreground"
          data-next-sessions-shown={kind}
        >
          <span
            data-next-sessions-shown-count
          >{`${String(kept.length)} of ${String(rows.length)} shown`}</span>
          <span aria-hidden="true">·</span>
          <Button type="button" emphasis="quiet" className="px-2" onClick={filter.onClear}>
            Clear filters
          </Button>
        </p>
      ) : null}
      <div className="next-operations-columns" aria-hidden="true">
        <span>SESSION</span>
        <span>PROJECT</span>
        <span>GOAL</span>
        <span>NOW</span>
        {kind === 'history' ? null : (
          <>
            <span>NEXT</span>
            <span>BLOCKED</span>
          </>
        )}
        {progressEnabled ? <span /> : null}
      </div>
      <TooltipProvider>
        <div className="next-operation-rows">
          {kept.length ? (
            buckets.map((bucket) => (
              <Fragment key={bucket.group}>
                {byGroup ? (
                  <h3 className="my-2 text-label font-semibold [overflow-wrap:anywhere]">
                    {groupName(bucket.group)}
                  </h3>
                ) : null}
                {nestRows(bucket.rows).map(({ row, depth }) => (
                  <RowView
                    key={row.key}
                    row={row}
                    depth={depth}
                    progressEnabled={progressEnabled}
                    hints={filter?.filtered.hints.get(row.key) ?? NO_HINTS}
                  />
                ))}
              </Fragment>
            ))
          ) : rows.length ? (
            <p data-next-sessions-filtered-empty className="next-absence">
              {groupEmptyLine(rows.length, title)}
            </p>
          ) : (
            <p className="next-sessions-empty next-absence">{empty}</p>
          )}
        </div>
      </TooltipProvider>
    </section>
  );
});

const RECENT_CAVEAT = { summary: 'What recent means', body: RECENT_WHY };

const FACT_KEYS = ['active', 'working', 'requests', 'reported-blocks'] as const;

/* The harnesses whose store could not be read, named, because "no sessions" under one of them would be
   a claim about a store nobody could open. */
function SourceGaps() {
  const harnesses = useDisplayed(selectHarnessSources);
  const failed = harnesses.rows.filter((row) => row.error !== null);
  if (!failed.length) return null;
  return (
    <ul className="next-sessions-sources" data-next-source-gaps>
      {failed.map((row) => (
        <li
          key={row.key}
        >{`${row.label ?? row.key}: Harness source could not be read; its sessions are missing here, not absent.`}</li>
      ))}
    </ul>
  );
}

export interface SessionsViewProps {
  /** The Intent step's prompt the reader picked and has not saved, for a session's goal cell. */
  readonly chosenFor?: (session: Row) => PromptCandidate | null;
}

const ANNOUNCE_KEY = 'sessions-filter';
/* A reader still typing hears nothing; one who pauses hears the count once. */
const TYPING_PAUSE_MS = 600;

/* The reader's own changes, and only those, speak in the cue region: a poll that re-filters the board says
   nothing, and the words typed are never read back. */
function useFilterActions(
  store: ReturnType<typeof useFilterState>[1],
  indexed: ReturnType<typeof indexScreen>,
  generated: number | null,
  annotated: boolean,
): FilterActions {
  const shell = useShell();
  const latest = useRef({ indexed, generated, annotated });
  const timer = useRef<TimerHandle | null>(null);
  useEffect(() => {
    latest.current = { indexed, generated, annotated };
  });
  useEffect(
    () => () => {
      if (timer.current !== null) shell.clock.clearTimeout(timer.current);
    },
    [shell],
  );
  /* The choices as they stood before the change being spoken, held across a burst of typing, so the cue
     says "Filters cleared" only when the change took the last choice away. */
  const since = useRef<FilterState | null>(null);
  return useMemo(() => {
    const speak = (next: FilterState) => {
      const now = latest.current;
      const before = since.current ?? next;
      since.current = null;
      const result = applyFilters(now.indexed, prepare(next, now.generated, now.annotated), (at) =>
        datedClock(at, now.generated ?? at),
      );
      // Forgotten first, so the same sentence after a second press is spoken again.
      shell.announcer.forget(ANNOUNCE_KEY);
      shell.announcer.announce(ANNOUNCE_KEY, announcement(result, next, before));
    };
    const cancel = () => {
      if (timer.current === null) return;
      shell.clock.clearTimeout(timer.current);
      timer.current = null;
    };
    const hold = () => {
      since.current ??= store.get();
    };
    return {
      change(next, how) {
        hold();
        store.set(next);
        cancel();
        if (how === 'press') {
          speak(next);
          return;
        }
        timer.current = shell.clock.setTimeout(() => {
          timer.current = null;
          speak(store.get());
        }, TYPING_PAUSE_MS);
      },
      clearAll() {
        hold();
        cancel();
        store.reset();
        speak(EMPTY_FILTERS);
        shell.controls.focusLane.focus(SEARCH_KEY);
      },
    };
  }, [shell, store]);
}

export function SessionsView({ chosenFor }: SessionsViewProps = {}) {
  const shell = useShell();
  const data = useDisplayed((snapshot) => snapshot.data);
  const model = useDisplayed(selectObserved);
  const screen = useMemo(
    () => (data ? buildSessionsScreen(data as unknown as Row, model, chosenFor) : null),
    [data, model, chosenFor],
  );
  const [filters, store] = useFilterState(shell.controls);
  /* The rows follow the choices a frame behind under load. The keystroke's own render keeps the deferred
     result, and `Group` and `RowView` are memoized on it, so that render redraws the toolbar and no row. */
  const deferred = useDeferredValue(filters);
  const indexed = useMemo(() => (screen ? indexScreen(screen) : []), [screen]);
  const generated = screen ? screen.context.generated : null;
  const annotated = screen ? screen.context.annotate && !screen.context.unreadable : false;
  const prepared = useMemo(
    () => prepare(deferred, generated, annotated),
    [deferred, generated, annotated],
  );
  const filtered = useMemo(
    () => applyFilters(indexed, prepared, (at) => datedClock(at, generated ?? at)),
    [indexed, prepared, generated],
  );
  const actions = useFilterActions(store, indexed, generated, annotated);
  const board = useMemo((): FilterBoard | null => {
    if (!data || !screen) return null;
    const payload = data as unknown as Row;
    return {
      generated,
      hours: windowHours(data),
      showAll: shell.runtime.bootstrap.showAll || payload['show_all'] === true,
      cleared: nextNumber(payload['cleared']) ?? 0,
      harnesses: harnessMeta(payload),
      annotate: screen.context.annotate,
      unreadable: screen.context.unreadable,
    };
  }, [data, screen, generated, shell]);
  const groupFilter = useMemo(() => ({ filtered, onClear: actions.clearAll }), [filtered, actions]);
  if (!screen || !board) return null;
  const canAnalyze = analysisAvailable(data as unknown as Row);
  return (
    <section className="next-operations" data-next-view-body="sessions">
      <header className="next-operations-header">
        <h1>Session operations</h1>
        {/* [DEC-27](docs/design-reading-a-session.md#dec-27-the-first-view-of-a-session-is-the-goal-analyze-drift-and-the-result) */}
        <p data-next-sessions-orientation>
          {canAnalyze
            ? 'Open a session, set its goal and press Analyze drift to see how far it moved from it.'
            : 'Open a session to see what it is doing and where it stands.'}
          {canAnalyze && screen.lede ? ` ${NOT_CHECKED}` : ''}
        </p>
        <IntentHowTo payload={data as unknown as Row} project="">
          <p className="next-why-body">{BOARD_WHY}</p>
          <p className="next-why-body">
            {screen.context.annotate ? GOAL_SOURCES_ON : GOAL_SOURCES_OFF}
          </p>
        </IntentHowTo>
      </header>
      <StatusLegend />
      <SourceGaps />
      <section className="next-operations-fleet" aria-label="Fleet facts">
        {screen.counters.slice(0, 2).map((counter, index) => (
          <section key={FACT_KEYS[index]} data-next-fleet-fact={FACT_KEYS[index]}>
            <span>{counter.label}</span>
            <strong>{counter.value}</strong>
            <small>{counter.noteText}</small>
          </section>
        ))}
      </section>
      {/* No toolbar over an empty board: the existing sentences say why there is nothing to find. */}
      {indexed.length ? (
        <SessionsFilters
          indexed={indexed}
          filters={filters}
          prepared={prepared}
          filtered={filtered}
          board={board}
          actions={actions}
        />
      ) : null}
      <Group
        kind="active"
        title="Active now"
        label="working, waiting on you, an exact request, or recorded drift"
        rows={screen.active}
        empty="No exact session has active evidence right now."
        filter={groupFilter}
        byGroup={filters.byGroup}
        progressEnabled={annotated}
      />
      <Group
        kind="history"
        title="Recent history"
        label=""
        rows={screen.history}
        empty="No recent-history rows in this payload."
        caveat={RECENT_CAVEAT}
        filter={groupFilter}
        byGroup={filters.byGroup}
        progressEnabled={annotated}
      />
      <CapacityStrip />
    </section>
  );
}

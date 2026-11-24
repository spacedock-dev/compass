import { StatusLegend } from '../ui/status-legend';
import { groupName, groupOf, nestRows } from './declared';
import { RelationshipLabels } from './DeclaredRelationships';
import { Card } from '../ui/card';
import { Badge } from '../ui/badge';
import { titleLink } from '../ui/link';
import { Button } from '../ui/button';
import { StatusTile } from '../ui/status-tile';
import { TooltipProvider } from '../ui/tooltip';
import {
  EXPLANATIONS,
  PROGRESS_LEVEL_WORDS,
  SESSION_LIST_WORDS,
  SESSION_ROW_WORDS,
} from '../language/glossary';
import { selectAttentionSelection } from '../attention/select';
import { WorthALookFlag } from '../attention/WorthALookFlag';
import { Fragment, memo, useDeferredValue, useEffect, useMemo, useRef } from 'react';
import { CapacityStrip } from '../capacity';
import { Disclosure, disclosureKey } from '../controls';
import {
  SESSION_TEXT_ORIGIN,
  gapNames,
  sessionStateLimit,
  sessionTile,
  type Row,
} from '../observed';
import { selectObserved } from '../observed/select';
import { selectHarnessSources } from '../store/selectors';
import { useDisplayed, useShell } from '../shell/context';
import { windowHours } from '../shell/derive';
import { formatTimestamp } from '../shell/format';
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
  type RowHint,
} from './filters';
import { useFilterState } from './filterStore';
import {
  SEARCH_KEY,
  SessionsFilters,
  SessionsWindowLink,
  type FilterActions,
  type FilterBoard,
} from './SessionsFilters';
import { buildSessionsScreen, outcomeLine, rowState, type SessionRow } from './rows';
import { SessionsGlance } from './SessionsGlance';
import { assignmentOf, type PromptCandidate } from './intent';
import { goalFocusFor } from './heldState';
import { worktreeOf } from './worktree';
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
   it was given. Every summary figure comes from the shared selection over the rows being drawn.
   Nothing here fetches, polls or acts; a row's controls act only when pressed. */

/* The goal cell's label, as the redesign canvas draws it: a small bold line over the goal. */
const GOAL_LABEL = 'block text-label font-semibold leading-[1.5] text-muted-foreground';

/* The goal cell's label and its stated absence, while annotations are off and there is no goal to link. */
function Fact({
  kind,
  label,
  value,
}: {
  readonly kind: string;
  readonly label: string;
  readonly value: string;
}) {
  return (
    <span
      className="next-operation-fact next-operation-fact--unknown"
      data-next-operation-fact={kind}
    >
      <small className={GOAL_LABEL}>{label}</small>
      {/* Plain quiet text, as "No goal yet" is drawn: no hatch or dashed box inside the list (owner, 2026-11-24). */}
      <strong className="mt-0.5 block text-label leading-[1.5] font-normal text-[var(--ink2)]">
        {value}
      </strong>
    </span>
  );
}

/* One line under the title, as the redesign canvas gives it: harness, project, worktree, when the session
   started and, once it has, when it ended. Every row says when it started: a session that published no start
   says so in quiet text. A start with no usable age is left out, as every other age is. */
function Descriptor({ row }: { readonly row: SessionRow }) {
  const { session } = row;
  const worktree = worktreeOf(row.source);
  return (
    <span
      className="next-operation-descriptor mt-0.5 block text-label text-muted-foreground"
      data-next-row-descriptor
    >
      <span className="next-operation-harness">{row.harnessLabel}</span>
      {session.project.trim() ? (
        <>
          {' · '}
          <span data-authored>{session.project}</span>
        </>
      ) : null}
      {worktree ? (
        <>
          {' · worktree '}
          <span data-authored>{worktree}</span>
        </>
      ) : null}
      {row.startedSince || !row.startPublished ? (
        <span data-next-row-started>
          {' · '}
          {row.startedSince || 'start time not published'}
        </span>
      ) : null}
      {row.endedSince ? (
        <>
          {' · '}
          <span data-next-row-ended>{row.endedSince}</span>
        </>
      ) : null}
    </span>
  );
}

/* What the session is doing now, under the descriptor. With nothing published about now, a current task
   stands in for it; with neither, the absence words, in plain quiet text. */
function NowLine({ row, assignment }: { readonly row: SessionRow; readonly assignment: string }) {
  const { session } = row;
  if (session.nowWordsKnown)
    return (
      <span
        className="next-operation-now mt-2 block text-body leading-[1.5] text-foreground"
        data-next-operation-fact="now"
        data-authored={session[SESSION_TEXT_ORIGIN].now || undefined}
      >
        {session.nowWords}
      </span>
    );
  if (assignment)
    return (
      <span
        className="next-operation-now mt-2 line-clamp-2 text-body leading-[1.5] text-foreground"
        data-next-operation-fact="now"
      >
        {'Current task · '}
        <span data-authored>{assignment}</span>
      </span>
    );
  return (
    <span
      className="next-operation-now mt-2 block text-body leading-[1.5] text-muted-foreground"
      data-next-operation-fact="now"
    >
      {session.nowWords}
    </span>
  );
}

function Identity({
  row,
  hints,
}: {
  readonly row: SessionRow;
  readonly hints: readonly RowHint[];
}) {
  const shell = useShell();
  const { session, source, history } = row;
  const assignment = history ? '' : assignmentOf(source);
  const names = source ? gapNames(source) : [];
  /* A row with no goal offers no goal action; opening it lands in the empty goal box instead, where the goal
     is added (owner, 2026-11-24). */
  const toGoal =
    row.goal.kind === 'none'
      ? () => goalFocusFor(shell.controls).request({ harness: session.harness, sid: session.sid })
      : undefined;
  const state = rowState(session);
  const limit = sessionStateLimit(session, state);
  /* Every row draws a tile (owner, 2026-11-24). A row whose state word is a text line (State not published,
     Waiting on child) keeps that line as its state, and its tile shows what Compass can say underneath. */
  const wordIsTile = state !== 'State not published' && state !== 'Waiting on child';
  const tile = sessionTile(session, state);
  /* The Waiting on you tile carries the block; what the session is waiting on stays under the Now line. A held
     question can run to 2,000 characters: the row shows three lines, the session page all of it. A note that
     only repeats the Now line is said once. */
  const note =
    !history && session.blockNote.trim() && session.blockNote.trim() !== session.nowWords.trim()
      ? session.blockNote
      : '';
  const outcomeTone =
    session.outcomeIcon === 'worth-a-look' ? '' : ` next-operation-outcome--${session.tone}`;
  const facts = row.showOutcome ? outcomeLine(session.outcomeText, session.gitText) : '';
  return (
    <div className="next-operation-identity flex items-start gap-4 max-[620px]:gap-3">
      {/* A fixed 44 px column, so titles, descriptors and Now lines line up whatever a row's tile is. */}
      <span
        className="next-operation-tile flex w-11 shrink-0 justify-center"
        data-next-row-tile-slot
      >
        <StatusTile
          state={tile}
          rowState={wordIsTile ? state : null}
          live={session.isLive && tile === 'Working'}
        />
      </span>
      <div className="min-w-0">
        <RouteAnchor
          route={row.route}
          /* The row is the 44 px target: the link's ::after covers the whole card. The title's own box keeps
             its line height, so the descriptor sits directly under it. */
          className={`next-operation-route block [min-block-size:0]! ${titleLink}`}
          label={`Open session ${session.titleText}`}
          {...(toGoal ? { before: toGoal } : {})}
          focusKey={`sessions-row:${row.key}`}
          fallback={SEARCH_KEY}
        >
          {/* An unknown title is a calm absence: the title's size in quiet ink, with no hatch, dashed edge or
              box, and still the row's link (owner, 2026-11-24). */}
          <strong
            data-authored={session.titleKnown || undefined}
            className={`mt-0 text-value leading-[1.4]${session.titleKnown ? ' font-bold' : ' next-operation-title--unknown font-semibold text-[var(--ink2)]'}`}
          >
            {session.titleText}
          </strong>
        </RouteAnchor>
        <Descriptor row={row} />
        <NowLine row={row} assignment={assignment} />
        {note ? (
          <span
            className="next-operation-block-note mt-1 line-clamp-3 text-body leading-[1.5] text-muted-foreground"
            data-next-row-block-note
            data-authored={session[SESSION_TEXT_ORIGIN].blockNote || undefined}
          >
            {note}
          </span>
        ) : null}
        {facts ? (
          <span className={`next-operation-outcome${outcomeTone}`} data-next-row-outcome>
            {facts}
          </span>
        ) : null}
        {limit && state !== 'Waiting on child' ? (
          <span
            className="next-operation-scan-only"
            title={session.scanOnly ? SCAN_ONLY_NOTE : undefined}
            data-next-row-state={wordIsTile ? undefined : state}
          >
            {limit}
          </span>
        ) : null}
        {!session.titleKnown &&
        session.promptKnown &&
        session.promptText.trim() !== row.goal.text.trim() ? (
          <span className="next-operation-assignment block">
            {'Last prompt · '}
            <span data-authored>{session.promptText}</span>
          </span>
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
            key={hint.text}
            className="mt-1 block text-label leading-[1.5] text-muted-foreground"
            data-next-row-hint
          >
            {hint.text}
            {hint.authoredExcerpt === undefined ? null : (
              <>
                {': "'}
                <span data-authored>{hint.authoredExcerpt}</span>
                {'"'}
              </>
            )}
          </span>
        ))}
        {/* Where the Now line already says what the session is doing, the task keeps its own line. */}
        {assignment && session.nowWordsKnown ? (
          <span className="next-operation-assignment block">
            {'Current task · '}
            <span data-authored>{assignment}</span>
          </span>
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
        {row.worthALook ? <WorthALookFlag reason={row.worthALook} /> : null}
      </div>
    </div>
  );
}

function GoalCellView({ row }: { readonly row: SessionRow }) {
  const shell = useShell();
  const { goal } = row;
  if (goal.kind === 'off') return <Fact kind="goal" label="Goal" value={goal.text} />;
  /* No goal: the ruled absence word in plain quiet text, and no action. The list cannot add a goal; the
     reader opens the row and adds one on the session page (owner, 2026-11-24). */
  if (goal.kind === 'none')
    return (
      <span className="next-operation-fact" data-next-operation-fact="goal">
        <small className={GOAL_LABEL}>{goal.label}</small>
        <span
          className="mt-0.5 block text-label leading-[1.5] text-muted-foreground"
          data-next-goal-absent
        >
          {goal.text}
        </span>
      </span>
    );
  const onGoal = () =>
    goalFocusFor(shell.controls).request({ harness: row.session.harness, sid: row.session.sid });
  return (
    <span className="next-operation-fact" data-next-operation-fact="goal">
      <small className={GOAL_LABEL}>{goal.label}</small>
      <RouteAnchor
        route={row.route}
        /* A goal holds 1,000 characters since 2026-10-27: the list shows three lines, the session page the rest.
           Plain ink at rest, as the canvas draws it; like a row title it underlines on hover and focus. */
        className={`next-operation-goal-link relative z-[1] mt-0.5 line-clamp-3 text-body font-normal leading-[1.5] [overflow-wrap:anywhere] ${titleLink}`}
        extra={{ 'data-next-goal-focus': '', 'data-authored': '' }}
        before={onGoal}
        focusKey={`sessions-row-goal:${row.key}`}
        fallback={SEARCH_KEY}
      >
        {goal.text}
      </RouteAnchor>
    </span>
  );
}

const NO_HINTS: readonly RowHint[] = [];

/* Memoized with `Group`, so the urgent render a keystroke makes, which still holds the deferred result,
   passes every row the same props and redraws none of them. */
/* The progress mark sits outside the row link, under the card's cover. */
function ProgressCell({ row }: { readonly row: SessionRow }) {
  const { progress, absence } = row;
  if (progress === 'medium' || progress === 'high' || progress === 'extreme') {
    return (
      <Badge
        variant="progress"
        tone={progress}
        className={
          progress === 'medium'
            ? 'justify-self-start bg-card py-[3px] leading-5'
            : 'justify-self-start py-[3px] leading-5'
        }
        data-next-drift-pill
        data-level={progress}
      >
        {PROGRESS_LEVEL_WORDS.get(progress)}
      </Badge>
    );
  }
  const word = progress ?? absence;
  if (!word) return null;
  return (
    <span
      className="self-start pt-[3px] text-label leading-[1.5] text-muted-foreground max-[620px]:pt-0"
      data-next-row-absence={SESSION_ROW_WORDS[word]}
    >
      {SESSION_ROW_WORDS[word]}
    </span>
  );
}

const RowView = memo(function RowView({
  row,
  hints = NO_HINTS,
  depth = 0,
}: {
  readonly row: SessionRow;
  readonly hints?: readonly RowHint[];
  readonly depth?: number;
}) {
  const { session, history } = row;
  /* Three columns, as the redesign canvas draws a row: the session and what it is doing, its goal, and its
     progress at the far right. A phone stacks them. A declared child is indented, never striped: the style board allows no
     left-border stripes. */
  return (
    <Card
      as="article"
      variant="session-row"
      className={`next-operation-row relative cursor-pointer no-underline grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)_9rem] max-[620px]:grid-cols-1 next-operation-row--${session.tone}${depth ? ' pl-12 max-[620px]:pl-8' : ''}`}
      {...(depth ? { 'data-declared-depth': depth } : {})}
      data-next-harness={session.harness}
      data-next-session={session.sid}
      {...(history ? { 'data-next-operation-history': 'true' } : {})}
    >
      <Identity row={row} hints={hints} />
      <GoalCellView row={row} />
      <ProgressCell row={row} />
    </Card>
  );
});

/* An empty group says so in plain quiet text, padded as a row inside the list card, with no hatch, dashed edge
   or tinted box: the style board draws absences as plain grey text (owner, 2026-11-24). */
const EMPTY_LINE =
  'm-0 border-0 border-t border-solid border-[var(--sunk)] px-6 py-5 text-body leading-[1.5] text-[var(--ink2)] max-[620px]:p-4';

const Group = memo(function Group({
  kind,
  title,
  rows,
  empty,
  countsAvailable,
  caveat,
  filter,
  byGroup = false,
}: {
  readonly byGroup?: boolean;
  readonly kind: 'active' | 'history';
  readonly title: string;
  readonly rows: readonly SessionRow[];
  readonly empty: string;
  readonly countsAvailable: boolean;
  readonly caveat?: readonly string[];
  /** Set while the reader's filters are on: what they keep of this group, and how to take them off. */
  readonly filter?: {
    readonly filtered: Filtered;
    readonly onClear: () => void;
  };
}) {
  const kept = filter?.filtered.active
    ? rows.filter((row) => filter.filtered.keys.has(row.key))
    : rows;
  const noMatches = countsAvailable && filter?.filtered.active && filter.filtered.shown === 0;
  const buckets = byGroup
    ? [...new Set(kept.map((row) => groupOf(row.source)))]
        .sort((a, b) => (a ? (b ? a.localeCompare(b, 'en') : -1) : 1))
        .map((group) => ({ group, rows: kept.filter((row) => groupOf(row.source) === group) }))
    : [{ group: '', rows: kept }];
  return (
    /* One band of the list card: a small header, then rows split by hairline dividers. History sits on the
       card's tinted ground, under a divider. */
    <section
      className={`next-operation-group next-operation-group--${kind}${kind === 'history' ? ' border-0 border-t border-solid border-[var(--rule)] bg-[var(--raise)]' : ''}`}
      data-next-operation-group={kind}
    >
      <header
        className={`flex flex-wrap items-baseline justify-between gap-x-3 px-6 pb-2 max-[620px]:px-4 ${kind === 'history' ? 'pt-6 max-[620px]:pt-4' : 'pt-4 max-[620px]:pt-3'}`}
      >
        {/* The canvas draws group names in the quiet tile's ink. */}
        <h2 className="m-0 text-label font-bold text-[var(--status-quiet-ink)]">{title}</h2>
        {countsAvailable ? (
          <span className="text-label text-muted-foreground" data-sessions-group-count>
            {kept.length} {kept.length === 1 ? 'session' : 'sessions'}
          </span>
        ) : null}
      </header>
      {noMatches && kind === 'active' ? (
        <div
          className="flex flex-wrap items-center gap-x-2 border-0 border-t border-solid border-[var(--sunk)] px-6 py-3 max-[620px]:px-4"
          data-sessions-nothing
        >
          <p className="m-0 text-body text-muted-foreground">{SESSION_LIST_WORDS.nothingMatches}</p>
          <Button
            type="button"
            variant="native"
            className="inline-flex cursor-pointer items-center border-0 bg-transparent px-1 text-body text-primary underline [font-family:var(--sans)]"
            onClick={filter?.onClear}
          >
            {SESSION_LIST_WORDS.showEverything}
          </Button>
        </div>
      ) : null}
      {countsAvailable && caveat && !noMatches ? (
        <Disclosure
          disclosureKey={disclosureKey({
            project: null,
            scope: null,
            name: `sessions-${kind}-why`,
          })}
          summary={EXPLANATIONS.sessionHistory}
          explanation
          className="px-6 pb-2 max-[620px]:px-4"
        >
          {caveat.map((sentence) => (
            <p key={sentence} className="next-why-body">
              {sentence}
            </p>
          ))}
        </Disclosure>
      ) : null}
      {/* A sibling after the header, never inside it, so a filtered header reads exactly as an unfiltered one. */}
      {filter?.filtered.active && !noMatches && rows.length ? (
        <p
          className="m-0 flex flex-wrap items-center gap-x-2 px-6 pb-2 text-body text-muted-foreground max-[620px]:px-4"
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
      <TooltipProvider>
        <div className="next-operation-rows">
          {kept.length ? (
            buckets.map((bucket) => (
              <Fragment key={bucket.group}>
                {byGroup ? (
                  <h3
                    className="m-0 border-0 border-t border-solid border-[var(--sunk)] px-6 pt-4 pb-2 text-label font-semibold [overflow-wrap:anywhere] max-[620px]:px-4"
                    data-authored={Boolean(bucket.group) || undefined}
                  >
                    {groupName(bucket.group)}
                  </h3>
                ) : null}
                {nestRows(bucket.rows).map(({ row, depth }) => (
                  <RowView
                    key={row.key}
                    row={row}
                    depth={depth}
                    hints={filter?.filtered.hints.get(row.key) ?? NO_HINTS}
                  />
                ))}
              </Fragment>
            ))
          ) : !countsAvailable || noMatches ? null : rows.length ? (
            <p data-next-sessions-filtered-empty className={EMPTY_LINE}>
              {groupEmptyLine(rows.length, title)}
            </p>
          ) : (
            <p className={`next-sessions-empty ${EMPTY_LINE}`} data-next-sessions-empty={kind}>
              {empty}
            </p>
          )}
        </div>
      </TooltipProvider>
    </section>
  );
});

const RECENT_CAVEATS = [
  [RECENT_WHY, BOARD_WHY, GOAL_SOURCES_OFF],
  [RECENT_WHY, BOARD_WHY, GOAL_SOURCES_ON],
] as const;

function historyHeading({ hours, showAll }: FilterBoard) {
  if (showAll) return SESSION_LIST_WORDS.earlierSessions;
  if (hours === null || hours <= 0) return 'Recently active';
  return `Earlier in the last ${String(hours)} ${hours === 1 ? 'hour' : 'hours'}`;
}

const SESSIONS_LIST_ID = 'sessions-list';

/* The harnesses whose store could not be read, named, because "no sessions" under one of them would be
   a claim about a store nobody could open. */
function SourceGaps({
  failed,
}: {
  readonly failed: ReturnType<typeof selectHarnessSources>['rows'];
}) {
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
  progressAvailable: boolean,
  countsAvailable: boolean,
): FilterActions {
  const shell = useShell();
  const latest = useRef({ indexed, generated, annotated, progressAvailable, countsAvailable });
  const timer = useRef<TimerHandle | null>(null);
  useEffect(() => {
    latest.current = { indexed, generated, annotated, progressAvailable, countsAvailable };
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
      const result = applyFilters(
        now.indexed,
        prepare(next, now.generated, now.annotated, now.progressAvailable),
        () => null,
      );
      // Forgotten first, so the same sentence after a second press is spoken again.
      shell.announcer.forget(ANNOUNCE_KEY);
      shell.announcer.announce(
        ANNOUNCE_KEY,
        announcement(result, next, before, now.countsAvailable),
      );
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
  const list = useRef<HTMLElement>(null);
  const data = useDisplayed((snapshot) => snapshot.data);
  const model = useDisplayed(selectObserved);
  const attention = useDisplayed(selectAttentionSelection);
  const harnesses = useDisplayed(selectHarnessSources);
  const failedSources = harnesses.rows.filter((row) => row.error !== null);
  const screen = useMemo(
    () => (data ? buildSessionsScreen(data as unknown as Row, model, chosenFor, attention) : null),
    [data, model, chosenFor, attention],
  );
  const [filters, store] = useFilterState(shell.controls);
  /* The rows follow the choices a frame behind under load. The keystroke's own render keeps the deferred
     result, and `Group` and `RowView` are memoized on it, so that render redraws the toolbar and no row. */
  const deferred = useDeferredValue(filters);
  const indexed = useMemo(() => (screen ? indexScreen(screen) : []), [screen]);
  const generated = screen ? screen.context.generated : null;
  const annotated = screen ? screen.context.annotate && !screen.context.unreadable : false;
  const progressAvailable = useMemo(
    () =>
      indexed.some(({ progress, progressLevel }) => progress !== null || progressLevel !== null),
    [indexed],
  );
  const prepared = useMemo(
    () => prepare(deferred, generated, annotated, progressAvailable),
    [deferred, generated, annotated, progressAvailable],
  );
  const filtered = useMemo(
    () =>
      applyFilters(indexed, prepared, (at) =>
        formatTimestamp(at, generated, { style: 'same-day-relative' }),
      ),
    [indexed, prepared, generated],
  );
  const countsAvailable = Boolean(attention?.counts);
  const actions = useFilterActions(
    store,
    indexed,
    generated,
    annotated,
    progressAvailable,
    countsAvailable,
  );
  const board = useMemo((): FilterBoard | null => {
    if (!data || !screen) return null;
    const payload = data as unknown as Row;
    return {
      generated,
      hours: windowHours(data),
      showAll: shell.runtime.bootstrap.showAll || payload['show_all'] === true,
      harnesses: harnessMeta(payload),
      annotate: screen.context.annotate,
      unreadable: screen.context.unreadable,
      countsAvailable,
    };
  }, [data, screen, generated, shell, countsAvailable]);
  const groupFilter = useMemo(() => ({ filtered, onClear: actions.clearAll }), [filtered, actions]);
  if (!screen || !board) return null;
  return (
    <section className="next-operations" data-next-view-body="sessions">
      {/* The allowance leads the page, under the example invite and above the greeting (owner, 2026-11-24): a
          reader deciding what to start next reads how much AI use is left before the sessions. */}
      <CapacityStrip />
      {attention ? (
        <SessionsGlance
          selection={attention}
          hour={new Date(shell.clock.now()).getHours()}
          incompleteSources={failedSources.length > 0}
          listId={SESSIONS_LIST_ID}
          working={filters.segment === 'working'}
          showWorking={() => {
            if (filters.segment === 'working') {
              actions.change({ ...filters, segment: 'all' }, 'press');
              return;
            }
            actions.change({ ...filters, state: [], segment: 'working' }, 'press');
            list.current?.focus({ preventScroll: true });
            list.current?.scrollIntoView?.({ block: 'start' });
          }}
        />
      ) : null}
      <SourceGaps failed={failedSources} />
      <SessionsFilters
        indexed={indexed}
        filters={filters}
        prepared={prepared}
        filtered={filtered}
        board={board}
        actions={actions}
      />
      <section
        ref={list}
        id={SESSIONS_LIST_ID}
        aria-label={SESSION_LIST_WORDS.all}
        tabIndex={-1}
        /* The whole list, both groups, sits in one white card, as the redesign canvas draws it. */
        className="mt-4 scroll-mt-2 overflow-hidden rounded-standard-card border border-solid border-[var(--rule)] bg-card focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
        data-sessions-list-card
      >
        <Group
          kind="active"
          title={SESSION_LIST_WORDS.rightNow}
          rows={screen.active}
          countsAvailable={countsAvailable}
          empty="No exact session has active evidence right now."
          filter={groupFilter}
          byGroup={filters.byGroup}
        />
        <Group
          kind="history"
          title={historyHeading(board)}
          rows={screen.history}
          countsAvailable={countsAvailable}
          empty="No recent-history rows in this payload."
          caveat={RECENT_CAVEATS[screen.context.annotate ? 1 : 0]}
          filter={groupFilter}
          byGroup={filters.byGroup}
        />
      </section>
      <SessionsWindowLink board={board} />
      <StatusLegend />
    </section>
  );
}

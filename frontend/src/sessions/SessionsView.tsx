import { Card } from '../ui/card';
import { Button } from '../ui/button';
import { useDeferredValue, useEffect, useMemo, useRef, useSyncExternalStore } from 'react';
import { IntentHowTo } from '../intent/HowTo';
import { CapacityStrip } from '../capacity';
import { Disclosure, disclosureKey } from '../controls';
import { gapNames, isRecord, isScanOnly, type Row } from '../observed';
import { nextNumber } from '../api/bootstrap';
import { contextKey } from '../api/identity';
import { headerAnalysis } from '../drift/model';
import { overlaid } from '../drift/overlay';
import { driftCtxFor } from '../drift/state';
import { PillMeter } from '../drift/DriftLevelView';
import { identityOf } from '../intent/context';
import { useHeldVersion } from '../intent/useIntent';
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
import { sessionInstruction, type PromptCandidate } from './intent';
import { goalFocusFor } from './heldState';
import { worktreeLabel } from './worktree';
import {
  BOARD_WHY,
  DUPLICATE_LABEL_LIMIT,
  GOAL_SOURCES_OFF,
  GOAL_SOURCES_ON,
  RECENT_WHY,
  SCAN_ONLY_LINE,
  SCAN_ONLY_NOTE,
  UNREAD_SOURCE_NOTE,
} from './notes';
import './sessions.css';

/* The Sessions screen: one row per exact session, the blocked and moving ones first, each with the goal
   it was given and whether it has drifted. A pure render of one payload: every figure comes from the
   model read from the rows being drawn, so the fleet facts, the groups and the header cannot disagree.
   Nothing here fetches, polls or acts; a row's controls act only when pressed. */

export function StatusDot({
  label,
  className,
  filled = true,
}: {
  readonly label: string;
  readonly className?: string;
  readonly filled?: boolean;
}) {
  return (
    <span
      className={className ? `next-status-dot ${className}` : 'next-status-dot'}
      aria-label={label}
    >
      {filled ? '●' : '○'}
    </span>
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
      {detail ? <em>{detail}</em> : null}
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

function assignmentOf(source: Row | undefined): string {
  const assignment = sessionInstruction(source, 'asked');
  const text = assignment ? String(assignment['text'] || '').trim() : '';
  const title = String(source?.['title'] || source?.['last_prompt'] || '').trim();
  return text && text !== title ? text : '';
}

function Identity({ row, hints }: { readonly row: SessionRow; readonly hints: readonly string[] }) {
  const { session, source, history } = row;
  const assignment = history ? '' : assignmentOf(source);
  const names = source ? gapNames(source) : [];
  const state = rowState(session);
  return (
    <span className="next-operation-identity">
      <span
        className={`m-0 block text-label font-semibold uppercase tracking-[.07em] [font-family:var(--mono)] ${state === 'Waiting on you' ? 'text-[var(--amber)]' : state === 'Working' ? 'text-foreground' : 'text-[var(--ink-label)]'}`}
        data-next-row-state={state}
      >
        {state}
      </span>
      <span className="next-operation-harness">{row.harnessLabel}</span>
      <RouteAnchor
        route={row.route}
        className="next-operation-route"
        label={`Open session ${session.titleText}`}
        focusKey={`sessions-row:${row.key}`}
        fallback={SEARCH_KEY}
      >
        <strong
          {...(session.titleKnown
            ? {}
            : { className: 'next-operation-title--unknown next-absence' })}
        >
          {session.isLive ? (
            <StatusDot label="working" className="next-operation-live-glyph" />
          ) : null}
          {session.titleText}
        </strong>
      </RouteAnchor>
      {!session.titleKnown && session.promptKnown ? (
        <span className="next-operation-assignment">{`LAST PROMPT · ${session.promptText}`}</span>
      ) : null}
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
        <span className="next-operation-assignment">{`Current task · ${assignment}`}</span>
      ) : null}
      {session.sharedLabelKnown ? (
        <span className="next-operation-collision" title={DUPLICATE_LABEL_LIMIT}>
          {session.sharedLabelText}
        </span>
      ) : null}
      {source && isScanOnly(source) ? (
        <span className="next-operation-scan-only" title={SCAN_ONLY_NOTE}>
          {SCAN_ONLY_LINE}
        </span>
      ) : null}
      {names.length ? (
        <span className="next-operation-unread" title={UNREAD_SOURCE_NOTE}>
          {`Source not fully read: ${names.join(', ')}`}
        </span>
      ) : null}
    </span>
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

/* The level the chip names for this row. Only a stored reading that itself departs names one: a row whose
   drift is a raise alone names no level, and a raise beside a consistent reading would otherwise borrow that
   reading's "None or low". Where this tab holds the analysis row, the level is the one the session page's
   header pill shows, from the same derivation (`headerAnalysis`), so the two cannot differ. Without it, a
   departing reading is at least Medium (`levels.analysis_level`: a departure reads Medium, and only a fresh
   failed check reads higher), so the chip says that much and draws no meter, which would show Medium for
   what may be High. */
function rowLevel(
  input: Parameters<typeof headerAnalysis>[0] | null,
): { readonly level: string | null; readonly label: string } | null {
  if (!input || !readingDeparts(input.session)) return null;
  const shown = headerAnalysis(input);
  if (shown) return { level: shown.level, label: shown.label };
  const { session } = input;
  if (session['annotation_not_accurate'] === true) return null;
  /* A reading over words the reader has since replaced is the stale line's to describe, not a level's. */
  const raw = session['annotation_assessment'];
  const read = isRecord(raw) ? nextNumber(raw['revision_read']) : null;
  const current = nextNumber(session['annotation_revision']);
  if (read === null || (current !== null && current !== read)) return null;
  return { level: null, label: 'Medium or higher' };
}

function DriftMarkView({ row }: { readonly row: SessionRow }) {
  const shell = useShell();
  const ctx = driftCtxFor(shell);
  // Redraws when the reader's held words change, so a drafted intent hides the level as the header does.
  useHeldVersion(ctx.intent.held);
  const overlay = useSyncExternalStore(ctx.drift.subscribe, ctx.drift.getOverlay);
  const contexts = useDisplayed((snapshot) => snapshot.contexts);
  const data = useDisplayed((snapshot) => snapshot.data) as Row | null;
  const records = useDisplayed((snapshot) => snapshot.records);
  const count = useDisplayed((snapshot) => snapshot.acceptedCount);
  const mark = row.drift;
  const { source, projectKey } = row;
  if (!mark || !source || !data) return mark ? <DriftMark mark={mark} level={null} /> : null;
  const record = records.get(contextKey(projectKey, identityOf(source)));
  const level = rowLevel({
    session: source,
    payload: overlaid(data, overlay, count),
    projectKey,
    contexts,
    held: ctx.intent.held,
    ...(record ? { record } : {}),
  });
  return <DriftMark mark={mark} level={level} />;
}

function DriftMark({
  mark,
  level,
}: {
  readonly mark: NonNullable<SessionRow['drift']>;
  readonly level: ReturnType<typeof rowLevel>;
}) {
  return (
    <span className="next-operation-drift" data-next-session-drift-mark>
      {level ? (
        <span
          className="inline-flex items-baseline gap-1.5"
          data-next-row-drift-level={level.level ?? 'medium_or_higher'}
        >
          {level.level ? <PillMeter level={level.level} /> : null}
          <span>
            Drift: <strong className="font-semibold text-foreground">{level.label}</strong>
          </span>
        </span>
      ) : (
        <strong>Drift</strong>
      )}
      {` · ${mark.age}`}
      {mark.someUnknown ? <small>Some recorded departure ages are unknown</small> : null}
      {mark.stale.map((line) => (
        <small key={line}>{line}</small>
      ))}
    </span>
  );
}

const NO_HINTS: readonly string[] = [];

function RowView({
  row,
  hints = NO_HINTS,
}: {
  readonly row: SessionRow;
  readonly hints?: readonly string[];
}) {
  const { session, history } = row;
  const nowKind = 'NOW';
  const outcome = session.outcomeKnown ? (
    <span className={`next-operation-outcome next-operation-outcome--${session.tone}`}>
      {`${session.outcomeGlyph} ${session.outcomeText}`}
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
      className={`next-operation-row next-operation-row--${session.tone}`}
      data-next-harness={session.harness}
      data-next-session={session.sid}
      {...(history ? { 'data-next-operation-history': 'true' } : {})}
    >
      <Identity row={row} hints={hints} />
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
          {/* The state cell's place in the history grid; the state itself leads the row. */}
          <span className="next-operation-state" aria-hidden="true" />
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
      <DriftMarkView row={row} />
    </Card>
  );
}

function Group({
  kind,
  title,
  label,
  rows,
  empty,
  caveat,
  filter,
}: {
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
  return (
    <section
      className={`next-operation-group next-operation-group--${kind}`}
      data-next-operation-group={kind}
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
          <Button
            type="button"
            variant="native"
            className="cursor-pointer border-0 bg-transparent p-0 font-[family-name:var(--sans)] text-body text-foreground underline"
            onClick={filter.onClear}
          >
            Clear filters
          </Button>
        </p>
      ) : null}
      <div className="next-operations-columns" aria-hidden="true">
        <span>SESSION</span>
        <span>PROJECT</span>
        <span>GOAL</span>
        <span>NOW</span>
        {kind === 'history' ? (
          <span />
        ) : (
          <>
            <span>NEXT</span>
            <span>BLOCKED</span>
          </>
        )}
      </div>
      <div className="next-operation-rows">
        {kept.length ? (
          kept.map((row) => (
            <RowView
              key={row.key}
              row={row}
              hints={filter?.filtered.hints.get(row.key) ?? NO_HINTS}
            />
          ))
        ) : rows.length ? (
          <p data-next-sessions-filtered-empty className="next-absence">
            {groupEmptyLine(rows.length, title)}
          </p>
        ) : (
          <p className="next-sessions-empty next-absence">{empty}</p>
        )}
      </div>
    </section>
  );
}

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
  return useMemo(() => {
    const speak = (next: FilterState) => {
      const now = latest.current;
      const result = applyFilters(now.indexed, prepare(next, now.generated, now.annotated), (at) =>
        datedClock(at, now.generated ?? at),
      );
      // Forgotten first, so the same sentence after a second press is spoken again.
      shell.announcer.forget(ANNOUNCE_KEY);
      shell.announcer.announce(ANNOUNCE_KEY, announcement(result));
    };
    const cancel = () => {
      if (timer.current === null) return;
      shell.clock.clearTimeout(timer.current);
      timer.current = null;
    };
    return {
      change(next, how) {
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
  /* The rows follow the choices a frame behind under load, so a keystroke never waits on hundreds of rows. */
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
  if (!screen || !board) return null;
  const groupFilter = { filtered, onClear: actions.clearAll };
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
      />
      <Group
        kind="history"
        title="Recent history"
        label=""
        rows={screen.history}
        empty="No recent-history rows in this payload."
        caveat={{ summary: 'What recent means', body: RECENT_WHY }}
        filter={groupFilter}
      />
      <CapacityStrip />
    </section>
  );
}

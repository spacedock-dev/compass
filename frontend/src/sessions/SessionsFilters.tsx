import {
  useEffect,
  useId,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type ComponentProps,
  type KeyboardEvent as ReactKeyboardEvent,
  type ReactNode,
} from 'react';
import { Disclosure, disclosureKey, useControls, useFocusKey } from '../controls';
import { DraftInput } from '../controls/DraftField';
import { EXPLANATIONS, SESSION_LIST_WORDS, SHOWN } from '../language/glossary';
import { useControlledDisclosureState } from '../controls/useDisclosureState';
import { datedClock } from '../observed/values';
import { useNavigate } from '../shell/context';
import { keyIsTaken, SKIP_ROLE_SELECTOR } from '../shell/keyboard';
import { Alert } from '../ui/alert';
import { Button, buttonVariants } from '../ui/button';
import { Checkbox } from '../ui/checkbox';
import { Icon } from '../ui/icons';
import { Label } from '../ui/label';
import { RadioGroup, RadioGroupItem } from '../ui/radio-group';
import { Separator } from '../ui/separator';
import {
  applyFilters,
  chipText,
  dateChip,
  dateCounts,
  dateFieldLabel,
  fixedOptions,
  harnessOptions,
  hiddenWaiting,
  isDated,
  joinNames,
  narrowOptions,
  optionLabel,
  prepare,
  projectOptions,
  groupOptions,
  QUERY_LIMIT,
  PROGRESS_OPTIONS,
  segmentCounts,
  SESSION_SEGMENTS,
  resultLine,
  SEGMENT_LABELS,
  toggled,
  unstampedHidden,
  unstampedLine,
  waitCoverage,
  waitingLine,
  whenLabel,
  WHENS,
  whenStart,
  type DateField,
  type Facet,
  type FilterState,
  type Filtered,
  type HarnessMeta,
  type IndexedRow,
  type Option,
  type Prepared,
  type When,
} from './filters';
import { RouteAnchor } from './RouteAnchor';

// Search and filter choices live for the life of the shell. See docs/design-sessions-search.md#the-toolbar.
export const SEARCH_KEY = 'sessions-search';

const FILTERS_KEY = 'sessions-filters';
const FILTERS_PANEL = disclosureKey({ project: null, scope: null, name: FILTERS_KEY });
const MORE_FILTERS = disclosureKey({ project: null, scope: null, name: 'sessions-more-filters' });

function useOptionKey<T extends HTMLElement>(key: string) {
  const controls = useControls();
  return useFocusKey<T>(controls.focusLane, key, { fallback: FILTERS_KEY });
}

function KeyedCheckbox({
  name,
  ...props
}: ComponentProps<typeof Checkbox> & { readonly name: string }) {
  const ref = useOptionKey<HTMLElement>(name);
  return <Checkbox ref={ref} {...props} />;
}

function KeyedRadio({
  name,
  ...props
}: ComponentProps<typeof RadioGroupItem> & { readonly name: string }) {
  const ref = useOptionKey<HTMLElement>(name);
  return <RadioGroupItem ref={ref} {...props} />;
}

export interface FilterBoard {
  readonly generated: number | null;
  readonly hours: number | null;
  readonly showAll: boolean;
  readonly harnesses: readonly HarnessMeta[];
  readonly annotate: boolean;
  readonly unreadable: string;
  readonly countsAvailable: boolean;
}

export interface FilterActions {
  /** A press speaks at once; typing speaks once the reader pauses. */
  change(next: FilterState, how: 'press' | 'typing'): void;
  /** Empties the words and every facet, then puts the reader back in the search field. */
  clearAll(): void;
}

const ROW = 'flex min-h-11 w-full items-center gap-2.5 cursor-pointer';
const NOTE = 'm-0 text-label text-muted-foreground leading-[1.5]';
const SENTENCE = 'm-0 text-body text-muted-foreground leading-[1.55]';
const PROGRESS_LEVEL_NOTE = 'Filtering by progress level is unavailable.';
const NO_PUBLISHED_GOALS = 'The board did not publish saved goals for these sessions.';
const PARTIAL_GOALS = 'Goal filters skip sessions whose saved goal status was not published.';
const NO_CLOCK = 'The board published no clock time, so dates cannot be filtered.';
const HOURS_WORD = (hours: number) => `${String(hours)} ${hours === 1 ? 'hour' : 'hours'}`;

function showAllHref(all: boolean): string {
  return `${globalThis.location?.pathname ?? '/'}${all ? '?all=1' : ''}#n=sessions`;
}

function ShowAllLink() {
  return (
    <span className="flex flex-col gap-0.5">
      <a
        data-slot="button-link"
        className={`${buttonVariants({ variant: 'native' })} inline-flex items-center text-primary underline`}
        href={showAllHref(true)}
      >
        {SESSION_LIST_WORDS.showOlder}
      </a>
      <span className={NOTE}>
        The page reloads and reads every stored session. Your filters are not kept.
      </span>
    </span>
  );
}

export function SessionsWindowLink({ board }: { readonly board: FilterBoard }) {
  if (!board.showAll) return <ShowAllLink />;
  return (
    <div className="flex flex-col items-start gap-1" data-sessions-all-note>
      <a
        data-slot="button-link"
        className={`${buttonVariants({ variant: 'native' })} inline-flex items-center text-primary underline`}
        href={showAllHref(false)}
      >
        {board.hours
          ? `Show only the last ${HOURS_WORD(board.hours)}`
          : 'Show only recently active sessions'}
      </a>
      <p className={NOTE}>
        {`Showing all stored sessions. ${board.hours ? `Sessions not active in the last ${HOURS_WORD(board.hours)}` : 'Sessions that were not recently active'} were not fully read, so their start time, title or model may not be published.`}
      </p>
    </div>
  );
}

/* Where a dated choice reaches past what the board loaded. Started mode cannot be rescued by loading more,
   because start times are read only for sessions active in the window; Last active can. The note is drawn
   below the search result, and its button goes as it is pressed. */
export function WindowNote({
  filters,
  prepared,
  board,
  onSwitch,
}: {
  readonly filters: FilterState;
  readonly prepared: Prepared;
  readonly board: FilterBoard;
  readonly onSwitch: () => void;
}) {
  const { edges } = prepared;
  if (board.showAll || edges === null || !isDated(filters.when)) return null;
  if (board.hours === null || board.hours <= 0)
    return (
      <p className={SENTENCE} data-sessions-window-note>
        The board holds only recently active sessions.
      </p>
    );
  const windowStart = edges.generated - board.hours * 3600;
  const start = whenStart(filters.when, edges);
  if (start === null || start >= windowStart) return null;
  const since = `The board holds sessions active since ${datedClock(windowStart, edges.generated)} (the last ${HOURS_WORD(board.hours)}).`;
  return filters.dateField === 'started' ? (
    <div className="flex flex-col items-start gap-1" data-sessions-window-note="started">
      <p className={SENTENCE}>
        {`${since} A session that started in this range and went quiet before then is not on the board. Start times are read only for sessions active in that window, even under Show older sessions.`}
      </p>
      <Button type="button" onClick={onSwitch}>
        Filter by last active instead
      </Button>
    </div>
  ) : (
    <div className="flex flex-col items-start gap-1" data-sessions-window-note="active">
      <p className={SENTENCE}>{`${since} Older sessions are not loaded.`}</p>
    </div>
  );
}

function OptionRow({
  option,
  checked,
  onToggle,
  facet,
}: {
  readonly option: Option;
  readonly checked: boolean;
  readonly onToggle: () => void;
  readonly facet: Facet;
}) {
  const name = `${facet}:${option.value}`;
  return (
    <Label
      className={option.disabled ? `${ROW} cursor-not-allowed` : ROW}
      data-filter-option={name}
    >
      <KeyedCheckbox
        name={name}
        checked={checked}
        disabled={option.disabled}
        onCheckedChange={onToggle}
      />
      <span className="flex min-w-0 flex-1 flex-col">
        <span data-filter-label>{option.label}</span>
        {option.note ? (
          <span className={NOTE} data-filter-note>
            {option.note}
          </span>
        ) : null}
      </span>
      {option.count === null ? null : (
        <span
          className="text-label text-muted-foreground [font-family:var(--mono)]"
          data-filter-count
        >
          {option.count}
        </span>
      )}
    </Label>
  );
}

function OptionList({
  facet,
  name,
  options,
  chosen,
  onToggle,
}: {
  readonly facet: Facet;
  readonly name: string;
  readonly options: readonly Option[];
  readonly chosen: readonly string[];
  readonly onToggle: (value: string) => void;
}) {
  return (
    <div role="group" aria-label={name} className="grid">
      {options.map((option) => (
        <OptionRow
          key={option.value}
          facet={facet}
          option={option}
          checked={chosen.includes(option.value)}
          onToggle={() => onToggle(option.value)}
        />
      ))}
    </div>
  );
}

function FilterFacet({
  facet,
  name,
  children,
}: {
  readonly facet: string;
  readonly name: string;
  readonly children: ReactNode;
}) {
  return (
    <div data-filter-facet={facet} className="min-w-0">
      <h3 className={`${NOTE} font-semibold`}>{name}</h3>
      {children}
    </div>
  );
}

function ChipGroup({
  name,
  children,
  note,
}: {
  readonly name: string;
  readonly children: ReactNode;
  readonly note?: ReactNode;
}) {
  const noteId = useId();
  return (
    <div
      role="group"
      aria-label={name}
      aria-describedby={note ? noteId : undefined}
      className="flex min-w-0 flex-col items-start gap-2"
    >
      <span className={`${NOTE} font-semibold`}>{name}</span>
      <div className="flex flex-wrap gap-2">{children}</div>
      {note ? (
        <p id={noteId} className={NOTE}>
          {note}
        </p>
      ) : null}
    </div>
  );
}

function FilterChip({
  label,
  count,
  note,
  selected,
  disabled,
  onClick,
}: {
  readonly label: string;
  readonly count?: number | null;
  readonly note?: string;
  readonly selected: boolean;
  readonly disabled?: boolean;
  readonly onClick: () => void;
}) {
  const noteId = useId();
  const chip = (
    <Button
      type="button"
      variant="filter-option"
      aria-describedby={note ? noteId : undefined}
      aria-pressed={selected}
      disabled={disabled}
      onClick={onClick}
    >
      {label}
      {count == null ? null : (
        <>
          {' '}
          <span className="tabular-nums" data-filter-count>
            {count}
          </span>
        </>
      )}
    </Button>
  );
  return note ? (
    <div className="flex min-w-0 flex-col items-start gap-1">
      {chip}
      <p id={noteId} className={NOTE}>
        {note}
      </p>
    </div>
  ) : (
    chip
  );
}

export const PROJECT_FIND_KEY = 'sessions-filter-project-find';

/* The narrowing is the field's words. The words last while the panel is mounted; when the list falls to eight projects or fewer the field leaves the page and its words with it, so
   a field that comes back reports what it holds, empty included, and no narrowing outlives what it shows.
   Field memory restores only the caret, scroll and size. */
function ProjectFind({
  id,
  onNarrow,
}: {
  readonly id: string;
  readonly onNarrow: (text: string) => void;
}) {
  const box = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    onNarrow(box.current?.querySelector('input')?.value ?? '');
  }, [onNarrow]);
  return (
    <div ref={box}>
      <DraftInput
        id={id}
        memoryKey={PROJECT_FIND_KEY}
        focusKey={PROJECT_FIND_KEY}
        autoComplete="off"
        spellCheck={false}
        onInput={(event) => onNarrow(event.currentTarget.value)}
      />
    </div>
  );
}

function ProjectList({
  options,
  chosen,
  onToggle,
}: {
  readonly options: readonly Option[];
  readonly chosen: readonly string[];
  readonly onToggle: (value: string) => void;
}) {
  const [narrow, setNarrow] = useState('');
  const id = useId();
  const many = options.length > 8;
  const listed = many ? narrowOptions(options, narrow) : [...options];
  return (
    <>
      {many ? (
        <>
          <Label htmlFor={id} className="text-label text-muted-foreground">
            Find a project
          </Label>
          <ProjectFind id={id} onNarrow={setNarrow} />
          {listed.length < options.length ? (
            <p className={NOTE}>
              {`Showing ${String(listed.length)} of ${String(options.length)} projects. Keep typing to narrow.`}
            </p>
          ) : null}
        </>
      ) : null}
      <div className="max-h-[50vh] overflow-y-auto">
        <OptionList
          facet="project"
          name="Project"
          options={listed}
          chosen={chosen}
          onToggle={onToggle}
        />
      </div>
    </>
  );
}

function annotationSentence(board: FilterBoard, what: 'drift' | 'goal' | 'progress'): string {
  if (!board.annotate)
    return what === 'goal'
      ? 'Goals are not published because annotations are off.'
      : 'Progress records are not published because annotations are off.';
  if (board.unreadable)
    return 'The annotation store could not be read, so progress and goals cannot be filtered.';
  return '';
}

export function SessionsFilters({
  indexed,
  filters,
  prepared,
  filtered,
  board,
  actions,
}: {
  readonly indexed: readonly IndexedRow[];
  /** The live choices, so a control reads what the reader just pressed. */
  readonly filters: FilterState;
  /** The choices the rows below were drawn from. */
  readonly prepared: Prepared;
  readonly filtered: Filtered;
  readonly board: FilterBoard;
  readonly actions: FilterActions;
}) {
  const navigate = useNavigate();
  const controls = useControls();
  const searchId = useId();
  const panelId = useId();
  const panelOpen = useControlledDisclosureState(controls.disclosures, FILTERS_PANEL);
  const triggerRef = useFocusKey<HTMLButtonElement>(controls.focusLane, FILTERS_KEY);
  const quickId = useId();
  const fieldBox = useRef<HTMLDivElement>(null);
  const chipBox = useRef<HTMLDivElement>(null);
  const refocus = useRef<number | null>(null);
  const field = () => fieldBox.current?.querySelector('input') ?? null;
  const set = (change: Partial<FilterState>) => actions.change({ ...filters, ...change }, 'press');
  const setWhen = (when: When, dateField = filters.dateField) =>
    set(when === 'any' ? { dateField, when, includeUnstamped: false } : { dateField, when });
  const toggle = (facet: Facet, value: string) =>
    set({ [facet]: toggled(filters[facet], value) } as Partial<FilterState>);

  /* The node is uncontrolled, so a reset made elsewhere (Clear all, a group's Clear filters) reaches it here. */
  useLayoutEffect(() => {
    const node = field();
    if (node && node.value !== filters.query) node.value = filters.query;
  });

  /* Use the shell's shortcut rules so typing and open overlays retain their keys. */
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== '/') return;
      const target = event.target instanceof Element ? event.target : null;
      if (
        keyIsTaken({
          tagName: target?.tagName ?? 'BODY',
          isContentEditable: target instanceof HTMLElement && target.isContentEditable,
          role: target?.closest(SKIP_ROLE_SELECTOR)?.getAttribute('role') ?? null,
          metaKey: event.metaKey,
          ctrlKey: event.ctrlKey,
          altKey: event.altKey,
          defaultPrevented: event.defaultPrevented,
        })
      )
        return;
      if (
        document.querySelector(
          '[data-slot=popover-trigger][aria-expanded=true], [data-slot=select-trigger][aria-expanded=true], [data-hold-paint][aria-expanded=true]',
        )
      )
        return;
      const node = fieldBox.current?.querySelector('input');
      if (!node) return;
      // Firefox opens Quick Find on "/" unless the key is taken.
      event.preventDefault();
      node.focus();
      node.select();
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, []);

  /* A removed chip hands focus to the chip that took its place, then Clear all, then the field. */
  useLayoutEffect(() => {
    const index = refocus.current;
    if (index === null) return;
    refocus.current = null;
    const chips = [
      ...(chipBox.current?.querySelectorAll<HTMLElement>('[data-sessions-chip]') ?? []),
    ];
    const next =
      chips[index] ??
      chipBox.current?.querySelector<HTMLElement>('[data-sessions-clear-all]') ??
      field();
    next?.focus();
  });

  const readable = board.annotate && !board.unreadable;
  const progressExplanation = !readable
    ? annotationSentence(board, 'progress')
    : prepared.progressAvailable
      ? ''
      : NO_PUBLISHED_GOALS;
  const incompleteGoals = useMemo(
    () => indexed.some(({ progress }) => progress === null),
    [indexed],
  );
  const goalCoverage = progressExplanation || (incompleteGoals ? PARTIAL_GOALS : '');
  const noMatches = board.countsAvailable && filtered.active && filtered.shown === 0;
  const emptySearch = noMatches && prepared.terms.length > 0;
  /* The rows lag the field while the deferred render catches up, so the one match is offered only once
     they agree, and Enter reads the live words rather than the rows still drawn. */
  const caughtUp = prepared.filters === filters;
  const onlyIn = (result: Filtered) =>
    result.active && result.shown === 1
      ? indexed.find((one) => result.keys.has(one.row.key))
      : undefined;
  const only = caughtUp ? onlyIn(filtered) : undefined;
  const onFieldKey = (event: ReactKeyboardEvent<HTMLInputElement>) => {
    const node = event.currentTarget;
    if (event.key === 'Escape') {
      if (event.nativeEvent.defaultPrevented) return;
      if (panelOpen) {
        dismissPanel(event);
        return;
      }
      if (!node.value) return;
      node.value = '';
      event.preventDefault();
      actions.change({ ...filters, query: '' }, 'press');
      return;
    }
    if (event.key !== 'Enter' || event.nativeEvent.isComposing) return;
    const live = caughtUp
      ? only
      : onlyIn(
          applyFilters(
            indexed,
            prepare(filters, board.generated, readable, prepared.progressAvailable),
            () => '',
          ),
        );
    if (!live) return;
    event.preventDefault();
    navigate(live.row.route);
  };

  /* Everything below reads the deferred choices, so a keystroke, which changes only the live ones, reuses it
     and walks no row. */
  const derived = useMemo(
    () => ({
      dates: dateCounts(indexed, prepared),
      waiting: hiddenWaiting(indexed, filtered),
      coverage: waitCoverage(indexed, board.harnesses),
      projects: projectOptions(indexed, prepared),
      group: groupOptions(indexed, prepared),
      harnesses: harnessOptions(indexed, prepared, board.harnesses),
      state: fixedOptions(indexed, prepared, 'state', board.countsAvailable),
      drift: fixedOptions(indexed, prepared, 'drift', board.countsAvailable),
      goal: fixedOptions(indexed, prepared, 'goal', board.countsAvailable),
      headless: fixedOptions(indexed, prepared, 'headless', board.countsAvailable),
    }),
    [indexed, prepared, filtered, board.harnesses, board.countsAvailable],
  );
  const { dates, waiting, coverage, projects, harnesses } = derived;
  const counts = useMemo(() => segmentCounts(indexed), [indexed]);
  const togglePanel = () => controls.disclosures.set(FILTERS_PANEL, !panelOpen);
  const dismissPanel = (event: ReactKeyboardEvent) => {
    if (event.key !== 'Escape' || event.defaultPrevented || !panelOpen) return;
    event.preventDefault();
    togglePanel();
    controls.focusLane.focus(FILTERS_KEY);
  };
  const missing = unstampedHidden(dates, prepared);
  const noClock = board.generated === null;
  const datesUnavailable = noClock || !board.countsAvailable;
  const stamped = filters.dateField === 'started' ? 'start time' : 'activity time';

  /* Keep an inactive choice visible and clearable when the board loses the data it needs. */
  const chips: {
    readonly key: string;
    readonly full: string;
    readonly short: string;
    readonly inert: string;
    readonly clear: () => void;
  }[] = [];
  if (filters.segment !== 'all') {
    const segment = SEGMENT_LABELS[filters.segment];
    chips.push({
      key: 'segment',
      full: segment,
      short: segment,
      inert: '',
      clear: () => set({ segment: 'all' }),
    });
  }
  const date = dateChip(filters, dates.unstamped);
  if (date)
    chips.push({
      key: 'date',
      full: date,
      short: date,
      inert: noClock ? NO_CLOCK : '',
      clear: () => set({ when: 'any', includeUnstamped: false }),
    });
  const facetNames: Readonly<Record<Facet, string>> = {
    project: 'Project',
    group: 'Group',
    harness: 'Agent',
    headless: 'Headless',
    state: 'State',
    drift: SESSION_LIST_WORDS.progressRecords,
    goal: 'Goal source',
    progress: SESSION_LIST_WORDS.progressCheck,
  };
  const ordered = (facet: Facet): string[] => {
    const order =
      facet === 'project'
        ? projects.map((one) => one.value)
        : facet === 'harness'
          ? harnesses.map((one) => one.value)
          : facet === 'progress'
            ? PROGRESS_OPTIONS.map((one) => one.value)
            : derived[facet].map((one) => one.value);
    return [...filters[facet]].sort(
      (a, b) =>
        (order.indexOf(a) === -1 ? order.length : order.indexOf(a)) -
        (order.indexOf(b) === -1 ? order.length : order.indexOf(b)),
    );
  };
  for (const facet of [
    'project',
    'group',
    'harness',
    'headless',
    'state',
    'drift',
    'goal',
    'progress',
  ] as const) {
    if (!filters[facet].length) continue;
    const text = chipText(
      facetNames[facet],
      ordered(facet).map((value) => optionLabel(facet, value, board.harnesses)),
    );
    chips.push({
      key: facet,
      ...text,
      inert:
        facet === 'progress' || facet === 'goal'
          ? progressExplanation
          : facet === 'drift' && !readable
            ? annotationSentence(board, facet)
            : '',
      clear: () => set({ [facet]: [] } as Partial<FilterState>),
    });
  }
  const inertNotes = [...new Set(chips.map((chip) => chip.inert).filter(Boolean))].map(
    (sentence) => {
      const names = chips
        .filter((chip) => chip.inert === sentence)
        .map((chip) => (chip.key === 'date' ? 'Date' : facetNames[chip.key as Facet]));
      return {
        sentence,
        text: `${sentence} The ${joinNames(names)} ${names.length === 1 ? 'chip filters' : 'chips filter'} nothing.`,
      };
    },
  );
  const noteId = (sentence: string) =>
    `${quickId}-inert-${String(inertNotes.findIndex((note) => note.sentence === sentence))}`;

  /* Three buttons go as they are pressed, so each hands focus on before it goes: a focused node that leaves
     the page drops focus to the body. */
  const pressAndFocus = (change: Partial<FilterState>, key: string) => {
    set(change);
    controls.focusLane.focus(key);
  };
  const windowNote = (
    <WindowNote
      filters={prepared.filters}
      prepared={prepared}
      board={board}
      onSwitch={() => pressAndFocus({ dateField: 'active' }, FILTERS_KEY)}
    />
  );

  return (
    /* The role is stated as well: testing-library's role table predates the element, and older assistive
       software reads only the attribute. */
    <search
      role="search"
      aria-label="Find sessions"
      className="mt-6 flex flex-col gap-3"
      data-next-sessions-search
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="m-0 text-value font-semibold">{SESSION_LIST_WORDS.all}</h2>
        <div
          role="group"
          aria-label={SESSION_LIST_WORDS.status}
          className="flex flex-wrap gap-1 rounded-card bg-muted p-1"
        >
          {SESSION_SEGMENTS.map((segment) => (
            <Button
              key={segment}
              type="button"
              variant="segment"
              aria-pressed={filters.segment === segment}
              disabled={
                segment !== 'all' &&
                filters.segment !== segment &&
                (!board.countsAvailable || indexed.length === 0)
              }
              onClick={() => set({ segment })}
            >
              {SEGMENT_LABELS[segment]}{' '}
              {board.countsAvailable ? (
                <span className="ml-1 tabular-nums">{counts[segment]}</span>
              ) : (
                <span className="sr-only">unavailable</span>
              )}
            </Button>
          ))}
        </div>
      </div>
      <div className="flex flex-wrap items-start gap-2">
        <div ref={fieldBox} className="relative min-w-0 flex-[1_1_22rem]">
          <Label htmlFor={searchId} className="sr-only">
            Search sessions
          </Label>
          <Icon
            name="search"
            className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground"
          />
          <DraftInput
            id={searchId}
            type="search"
            memoryKey={SEARCH_KEY}
            focusKey={SEARCH_KEY}
            defaultValue={filters.query}
            maxLength={QUERY_LIMIT}
            placeholder="Search titles, goals or projects"
            aria-keyshortcuts="/"
            autoComplete="off"
            spellCheck={false}
            className="bg-card pl-9 pr-24 [&::-webkit-search-cancel-button]:appearance-none"
            onInput={(event) =>
              actions.change({ ...filters, query: event.currentTarget.value }, 'typing')
            }
            onKeyDown={onFieldKey}
          />
          <span className="absolute right-1 top-1/2 flex -translate-y-1/2 items-center gap-1">
            {filters.query ? null : (
              <kbd aria-hidden="true" className="mr-2 [@media(max-width:620px)]:hidden">
                /
              </kbd>
            )}
            {filters.query ? (
              <Button
                type="button"
                variant="native"
                aria-label="Clear search"
                className="inline-flex cursor-pointer items-center justify-center border-0 bg-transparent p-0 text-muted-foreground hover:text-foreground"
                onClick={() => {
                  const node = field();
                  if (node) node.value = '';
                  actions.change({ ...filters, query: '' }, 'press');
                  node?.focus();
                }}
              >
                <Icon name="remove" />
              </Button>
            ) : null}
          </span>
        </div>
        <Button
          ref={triggerRef}
          type="button"
          emphasis="secondary"
          aria-expanded={panelOpen}
          aria-controls={panelId}
          data-hold-paint
          className="gap-2"
          onClick={togglePanel}
          onKeyDown={dismissPanel}
        >
          <Icon name="filters" />
          {SESSION_LIST_WORDS.filters}
        </Button>
      </div>
      <section
        id={panelId}
        aria-label={SESSION_LIST_WORDS.filters}
        hidden={!panelOpen}
        className="rounded-card border border-border bg-card p-4"
        onKeyDown={dismissPanel}
      >
        <div className="flex flex-col gap-4">
          <div className="flex flex-wrap items-start gap-x-6 gap-y-4">
            <ChipGroup name="Project">
              {projects.slice(0, 3).map(({ value, label, count, note, disabled }) => (
                <FilterChip
                  key={value}
                  label={label}
                  count={count}
                  note={note}
                  disabled={disabled}
                  selected={filters.project.includes(value)}
                  onClick={() => toggle('project', value)}
                />
              ))}
              {projects.length > 3 ? (
                <Button
                  type="button"
                  variant="filter-option"
                  onClick={() => {
                    controls.disclosures.set(MORE_FILTERS, true);
                    controls.focusLane.focus('sessions-more-filters');
                  }}
                >
                  {`+${String(projects.length - 3)} more`}
                </Button>
              ) : null}
            </ChipGroup>
            <ChipGroup name="Agent">
              {harnesses.map(({ value, label, count, note, disabled }) => (
                <FilterChip
                  key={value}
                  label={label}
                  count={count}
                  note={note}
                  disabled={disabled}
                  selected={filters.harness.includes(value)}
                  onClick={() => toggle('harness', value)}
                />
              ))}
            </ChipGroup>
            <ChipGroup name="Started">
              {(['today', 'week'] as const).map((when) => {
                const selected = filters.dateField === 'started' && filters.when === when;
                return (
                  <FilterChip
                    key={when}
                    label={whenLabel(when, 'started')}
                    disabled={datesUnavailable}
                    selected={selected}
                    onClick={() => setWhen(selected ? 'any' : when, 'started')}
                  />
                );
              })}
            </ChipGroup>
          </div>
          <ChipGroup
            name={SESSION_LIST_WORDS.progressCheck}
            note={
              <>
                {PROGRESS_LEVEL_NOTE}
                {goalCoverage ? ` ${goalCoverage}` : ''}
              </>
            }
          >
            {PROGRESS_OPTIONS.map(({ value, label }) => (
              <FilterChip
                key={value}
                label={label}
                selected={value === 'no-goal' && filters.progress.includes(value)}
                disabled={value !== 'no-goal' || !prepared.progressAvailable}
                onClick={() => toggle('progress', value)}
              />
            ))}
          </ChipGroup>
          {noClock ? <p className={NOTE}>{NO_CLOCK}</p> : null}
          <Disclosure
            disclosureKey={MORE_FILTERS}
            summary={SESSION_LIST_WORDS.moreFilters}
            focusKey="sessions-more-filters"
            explanation
            searchable={false}
          >
            <div className="grid gap-4 pt-2 sm:grid-cols-2">
              <FilterFacet facet="date" name="Date">
                <p id={`${searchId}-by`} className={NOTE}>
                  Filter by
                </p>
                <RadioGroup
                  aria-labelledby={`${searchId}-by`}
                  value={filters.dateField}
                  disabled={datesUnavailable}
                  onValueChange={(value) => set({ dateField: value as DateField })}
                >
                  {(['started', 'active'] as const).map((value) => (
                    <Label key={value} className={ROW} data-filter-option={`date-field:${value}`}>
                      <KeyedRadio name={`date-field:${value}`} value={value} />
                      <span>{dateFieldLabel(value)}</span>
                    </Label>
                  ))}
                </RadioGroup>
                <p className={NOTE}>
                  {filters.dateField === 'started'
                    ? 'Started is when the session was created.'
                    : 'Last active is the last time the session was observed doing anything.'}
                </p>
                <p id={`${searchId}-when`} className={NOTE}>
                  When
                </p>
                <RadioGroup
                  aria-labelledby={`${searchId}-when`}
                  value={filters.when}
                  disabled={datesUnavailable}
                  onValueChange={(value) => setWhen(value as When)}
                >
                  {WHENS.map((when) => (
                    <Label key={when} className={ROW} data-filter-option={`when:${when}`}>
                      <KeyedRadio name={`when:${when}`} value={when} />
                      <span className="min-w-0 flex-1" data-filter-label>
                        {whenLabel(when, filters.dateField)}
                      </span>
                      {datesUnavailable ? null : (
                        <span
                          className="text-label text-muted-foreground [font-family:var(--mono)]"
                          data-filter-count
                        >
                          {dates.byWhen.get(when) ?? 0}
                        </span>
                      )}
                    </Label>
                  ))}
                </RadioGroup>
                <Label className={ROW} data-filter-option="include-unstamped">
                  <KeyedCheckbox
                    name="include-unstamped"
                    checked={filters.includeUnstamped}
                    disabled={datesUnavailable}
                    onCheckedChange={(checked) => set({ includeUnstamped: checked })}
                  />
                  <span className="min-w-0 flex-1">
                    {`Also show sessions with no ${stamped}`}
                    {board.countsAvailable ? ` (${String(dates.unstamped)})` : ''}
                  </span>
                </Label>
                <Separator />
                {dates.unstampedHarnesses.length ? (
                  <p className={NOTE} data-sessions-unstamped-harnesses>
                    {`No ${stamped} is published for: ${dates.unstampedHarnesses.join(', ')}.`}
                  </p>
                ) : null}
                {filters.dateField === 'started' ? (
                  <p className={NOTE}>
                    Where no start time is published, Claude Code and Codex sessions use the time of
                    their first message, as the session page does.
                  </p>
                ) : null}
                <p className={NOTE}>Days follow this computer&apos;s clock and time zone.</p>
              </FilterFacet>
              <FilterFacet facet="project" name="Project">
                <ProjectList
                  options={projects}
                  chosen={filters.project}
                  onToggle={(value) => toggle('project', value)}
                />
                {filters.project.length ? (
                  <Button
                    type="button"
                    onClick={() =>
                      pressAndFocus(
                        { project: [] },
                        projects.length > 8
                          ? PROJECT_FIND_KEY
                          : `project:${projects[0]?.value ?? ''}`,
                      )
                    }
                  >
                    Clear project filter
                  </Button>
                ) : null}
              </FilterFacet>
              <FilterFacet facet="group" name="Group">
                <OptionList
                  facet="group"
                  name="Group"
                  options={derived.group}
                  chosen={filters.group}
                  onToggle={(value) => toggle('group', value)}
                />
              </FilterFacet>
              <div>
                <Button
                  type="button"
                  aria-pressed={filters.byGroup}
                  className="text-muted-foreground aria-pressed:border-[var(--accent)] aria-pressed:bg-accent aria-pressed:text-foreground"
                  onClick={() => set({ byGroup: !filters.byGroup })}
                >
                  Group by group
                </Button>
              </div>
              <FilterFacet facet="headless" name="Headless">
                <OptionList
                  facet="headless"
                  name="Headless"
                  options={derived.headless}
                  chosen={filters.headless}
                  onToggle={(value) => toggle('headless', value)}
                />
                <Separator />
                <p className={NOTE}>
                  Read from Claude Code transcripts and Codex rollout metadata. Interactive or
                  unknown includes unknown entrypoints and other harnesses.
                </p>
              </FilterFacet>
              <FilterFacet facet="state" name="State">
                <OptionList
                  facet="state"
                  name="State"
                  options={derived.state}
                  chosen={filters.state}
                  onToggle={(value) => toggle('state', value)}
                />
                {coverage.length ? (
                  <>
                    <Separator />
                    {coverage.map((line) => (
                      <p key={line} className={NOTE} data-sessions-wait-coverage>
                        {line}
                      </p>
                    ))}
                  </>
                ) : null}
              </FilterFacet>
              <FilterFacet facet="drift" name={facetNames.drift}>
                {readable ? (
                  <>
                    <OptionList
                      facet="drift"
                      name={facetNames.drift}
                      options={derived.drift}
                      chosen={filters.drift}
                      onToggle={(value) => toggle('drift', value)}
                    />
                    <Separator />
                    <p className={NOTE}>
                      Progress records include saved checks against your current words.
                    </p>
                  </>
                ) : (
                  <p className={SENTENCE} data-sessions-annotations-off>
                    {annotationSentence(board, 'drift')}
                  </p>
                )}
              </FilterFacet>
              <FilterFacet facet="goal" name="Goal source">
                {readable ? (
                  <>
                    <OptionList
                      facet="goal"
                      name="Goal source"
                      options={derived.goal}
                      chosen={filters.goal}
                      onToggle={(value) => toggle('goal', value)}
                    />
                    {goalCoverage ? <p className={NOTE}>{goalCoverage}</p> : null}
                  </>
                ) : (
                  <p className={SENTENCE} data-sessions-annotations-off>
                    {annotationSentence(board, 'goal')}
                  </p>
                )}
              </FilterFacet>
            </div>
            <Disclosure
              explanation
              disclosureKey={disclosureKey({
                project: null,
                scope: null,
                name: 'sessions-filter-counts',
              })}
              summary={EXPLANATIONS.filterCounts}
              searchable={false}
            >
              <p className="next-why-body">
                Each number beside an option is how many sessions with that value your other filters
                keep. Choices inside one filter widen the list; separate filters and the search
                narrow it.
              </p>
              <p className="next-why-body">
                An unpublished value has its own option where the board can identify it. Tab and{' '}
                {SESSION_LIST_WORDS.atAGlance} counts cover the whole board.
              </p>
            </Disclosure>
          </Disclosure>
        </div>
      </section>
      {chips.length ? (
        <div ref={chipBox} className="flex flex-wrap items-center gap-2" data-sessions-chips>
          {chips.map((chip, index) => {
            /* The name holds the words on the chip, so a reader who says what they see reaches it; a
               shortened chip's whole list is its description. */
            const fullId = chip.short === chip.full ? '' : `${quickId}-full-${chip.key}`;
            const described = [fullId, chip.inert ? noteId(chip.inert) : ''].filter(Boolean);
            return (
              <Button
                key={chip.key}
                type="button"
                variant="filter-chip"
                aria-label={`Remove ${chip.short}`}
                aria-describedby={described.length ? described.join(' ') : undefined}
                data-sessions-chip={chip.key}
                data-sessions-chip-inert={chip.inert ? '' : undefined}
                onClick={() => {
                  refocus.current = index;
                  chip.clear();
                }}
              >
                <span>{chip.short}</span>
                {fullId ? (
                  <span id={fullId} className="sr-only">
                    {chip.full}
                  </span>
                ) : null}
                <Icon name="remove" />
              </Button>
            );
          })}
          <Button type="button" data-sessions-clear-all onClick={actions.clearAll}>
            Clear all
          </Button>
          {inertNotes.map((note) => (
            <p
              key={note.sentence}
              id={noteId(note.sentence)}
              className={`${NOTE} basis-full`}
              data-sessions-chip-note
            >
              {note.text}
            </p>
          ))}
        </div>
      ) : (
        <div ref={chipBox} hidden />
      )}
      {filtered.active && !noMatches ? (
        <p className={SENTENCE} data-sessions-result>
          {resultLine(filtered, board)}
          {only ? ' Press Enter to open it.' : ''}
        </p>
      ) : null}
      {emptySearch || !board.countsAvailable ? null : windowNote}
      {!emptySearch && waiting.length ? (
        <Alert
          variant="session-health"
          announce={false}
          className="flex flex-wrap items-center gap-x-3 gap-y-1 text-foreground"
          data-sessions-hidden-waiting
        >
          <span className="flex items-center gap-1.5">
            <Icon name="earlier-failed" className="shrink-0 text-[var(--amber)]" />
            {waitingLine(waiting.length)}
          </span>
          {waiting.length === 1 && waiting[0] ? (
            <RouteAnchor
              route={waiting[0].row.route}
              label={`Open it: ${waiting[0].row.session.titleText}`}
              className="inline-flex items-center text-foreground underline"
            >
              Open it
            </RouteAnchor>
          ) : null}
          <Button type="button" onClick={actions.clearAll}>
            Clear filters
          </Button>
          {waiting.length > 1 ? (
            <RouteAnchor
              route={{ view: 'attention', project: null, session: null }}
              className="inline-flex items-center text-foreground underline"
            >
              See them on {SHOWN.attention}
            </RouteAnchor>
          ) : null}
        </Alert>
      ) : null}
      {!emptySearch && missing ? (
        <div className="flex flex-wrap items-center gap-x-3" data-sessions-unstamped>
          <p className={SENTENCE}>{unstampedLine(missing, prepared.filters.dateField)}</p>
          <Button
            type="button"
            onClick={() => pressAndFocus({ includeUnstamped: true }, FILTERS_KEY)}
          >
            Include them
          </Button>
        </div>
      ) : null}
    </search>
  );
}

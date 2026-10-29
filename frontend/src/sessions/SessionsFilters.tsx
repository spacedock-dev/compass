import {
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type ComponentProps,
  type KeyboardEvent as ReactKeyboardEvent,
  type ReactNode,
} from 'react';
import { Disclosure, disclosureKey, useControls, useFocusKey } from '../controls';
import { DraftInput } from '../controls/DraftField';
import { datedClock } from '../observed/values';
import { useNavigate } from '../shell/context';
import { keyIsTaken, SKIP_ROLE_SELECTOR } from '../shell/keyboard';
import { Alert } from '../ui/alert';
import { Badge } from '../ui/badge';
import { Button, buttonVariants } from '../ui/button';
import { Checkbox } from '../ui/checkbox';
import { Icon } from '../ui/icons';
import { Label } from '../ui/label';
import { RadioGroup, RadioGroupItem } from '../ui/radio-group';
import { Separator } from '../ui/separator';
import {
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
  projectOptions,
  QUERY_LIMIT,
  queryTerms,
  resultLine,
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

/* The Find sessions toolbar: one search field, six filter popovers, three presets, the chips that say what is
   on, and the lines that say what the filters hide. It owns no state of its own beyond the "Find a project"
   narrowing: every choice is in the filter store, so a poll, a view change and a round trip through a session
   leave it as the reader left it. docs/plans/2026-10-29-sessions-search.md owns the copy and the rules. */

export const SEARCH_KEY = 'sessions-search';

/** The focus key of a filter popover's trigger. */
const filterKey = (popover: string): string => `sessions-filter-${popover}`;

/* An option keeps its place by `<facet>:<value>`, the name its row carries, and an option that goes while
   focused hands focus to its popover's trigger rather than to the document body. */
function useOptionKey<T extends HTMLElement>(key: string, popover: string) {
  const controls = useControls();
  return useFocusKey<T>(controls.focusLane, key, { fallback: filterKey(popover) });
}

function KeyedCheckbox({
  name,
  inPopover,
  ...props
}: ComponentProps<typeof Checkbox> & { readonly name: string; readonly inPopover: string }) {
  const ref = useOptionKey<HTMLElement>(name, inPopover);
  return <Checkbox ref={ref} {...props} />;
}

function KeyedRadio({
  name,
  ...props
}: ComponentProps<typeof RadioGroupItem> & { readonly name: string }) {
  const ref = useOptionKey<HTMLElement>(name, 'date');
  return <RadioGroupItem ref={ref} {...props} />;
}

export interface FilterBoard {
  readonly generated: number | null;
  readonly hours: number | null;
  readonly showAll: boolean;
  readonly cleared: number;
  readonly harnesses: readonly HarnessMeta[];
  readonly annotate: boolean;
  readonly unreadable: string;
}

export interface FilterActions {
  /** A press speaks at once; typing speaks once the reader pauses. */
  change(next: FilterState, how: 'press' | 'typing'): void;
  /** Empties the words and every facet, then puts the reader back in the search field. */
  clearAll(): void;
}

const TRIGGER =
  'gap-1.5 border border-solid border-[var(--line)] rounded-control px-3 text-foreground hover:border-[var(--line-hi)]';
const ROW = 'flex min-h-11 w-full items-center gap-2.5 cursor-pointer';
const NOTE = 'm-0 text-label text-muted-foreground leading-[1.5]';
const SENTENCE = 'm-0 text-body text-muted-foreground leading-[1.55]';
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
        className={`${buttonVariants({ variant: 'native' })} inline-flex items-center text-foreground underline`}
        href={showAllHref(true)}
      >
        Show all stored sessions
      </a>
      <span className={NOTE}>
        The page reloads and reads every stored session. Your filters are not kept.
      </span>
    </span>
  );
}

/* Where a dated choice reaches past what the board loaded. Started mode cannot be rescued by loading more,
   because start times are read only for sessions active in the window; Last active can. */
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
        {`${since} A session that started in this range and went quiet before then is not on the board. Showing all stored sessions will not help, because start times are read only for sessions active in that window.`}
      </p>
      <Button type="button" onClick={onSwitch}>
        Filter by last active instead
      </Button>
    </div>
  ) : (
    <div className="flex flex-col items-start gap-1" data-sessions-window-note="active">
      <p className={SENTENCE}>{`${since} Older sessions are not loaded.`}</p>
      <ShowAllLink />
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
        inPopover={facet}
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

function FilterButton({
  facet,
  name,
  selected,
  children,
}: {
  readonly facet: string;
  readonly name: string;
  readonly selected: number;
  readonly children: ReactNode;
}) {
  return (
    <Disclosure
      variant="popover"
      disclosureKey={disclosureKey({
        project: null,
        scope: null,
        name: `sessions-filter-${facet}`,
      })}
      focusKey={filterKey(facet)}
      summaryLabel={selected ? `${name}, ${String(selected)} selected` : name}
      triggerClassName={TRIGGER}
      /* A short window flipped the tall Date list beside its button, over the search field; a filter list
         belongs under its button and scrolls there instead. */
      vertical
      holdPaint
      summary={
        <>
          <span>{name}</span>
          {selected ? (
            <Badge className="px-1.5 py-0" data-filter-badge>
              {selected}
            </Badge>
          ) : null}
        </>
      }
    >
      <div className="flex flex-col gap-2" data-filter-popover={facet}>
        {children}
      </div>
    </Disclosure>
  );
}

export const PROJECT_FIND_KEY = 'sessions-filter-project-find';

/* Field memory puts the words back into a remounted field without an input event, so the narrowing is read
   back from the node once it is restored; a child's layout effect runs after the restore inside it. */
function ProjectFind({
  id,
  onNarrow,
}: {
  readonly id: string;
  readonly onNarrow: (text: string) => void;
}) {
  const box = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const restored = box.current?.querySelector('input')?.value ?? '';
    if (restored) onNarrow(restored);
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

function annotationSentence(board: FilterBoard, what: 'drift' | 'goal'): string {
  if (!board.annotate)
    return what === 'drift'
      ? 'Drift is not published because annotations are off.'
      : 'Goals are not published because annotations are off.';
  if (board.unreadable)
    return 'The annotation store could not be read, so drift and goals cannot be filtered.';
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
  const searchId = useId();
  const quickId = useId();
  const fieldBox = useRef<HTMLDivElement>(null);
  const chipBox = useRef<HTMLDivElement>(null);
  const refocus = useRef<number | null>(null);
  const field = () => fieldBox.current?.querySelector('input') ?? null;
  const set = (change: Partial<FilterState>) => actions.change({ ...filters, ...change }, 'press');
  const toggle = (facet: Facet, value: string) =>
    set({ [facet]: toggled(filters[facet], value) } as Partial<FilterState>);

  /* The node is uncontrolled, so a reset made elsewhere (Clear all, a group's Clear filters) reaches it here. */
  useLayoutEffect(() => {
    const node = field();
    if (node && node.value !== filters.query) node.value = filters.query;
  });

  /* "/" finds the field from anywhere on Sessions, by the same rule the route keys use, and never from
     inside an open popup, where the reader is choosing. */
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
          '[data-slot=popover-trigger][aria-expanded=true], [data-slot=select-trigger][aria-expanded=true]',
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

  const terms = queryTerms(prepared.filters.query);
  const only =
    filtered.active && filtered.shown === 1
      ? indexed.find((one) => filtered.keys.has(one.row.key))
      : undefined;
  const onFieldKey = (event: ReactKeyboardEvent<HTMLInputElement>) => {
    const node = event.currentTarget;
    if (event.key === 'Escape') {
      // The capture-phase popover handler has already closed a popup and placed focus.
      if (event.nativeEvent.defaultPrevented) return;
      if (!node.value) return;
      node.value = '';
      event.preventDefault();
      actions.change({ ...filters, query: '' }, 'press');
      return;
    }
    if (event.key === 'Enter' && !event.nativeEvent.isComposing && only) {
      event.preventDefault();
      navigate(only.row.route);
    }
  };

  const dates = dateCounts(indexed, prepared);
  const missing = unstampedHidden(dates, prepared);
  const waiting = hiddenWaiting(indexed, filtered);
  const coverage = waitCoverage(indexed, board.harnesses);
  const projects = projectOptions(indexed, prepared);
  const harnesses = harnessOptions(indexed, prepared, board.harnesses);
  const readable = board.annotate && !board.unreadable;
  const noClock = board.generated === null;
  const stamped = filters.dateField === 'started' ? 'start time' : 'activity time';

  /* A chip the board cannot apply stays, so the reader still sees and can clear what they chose, and it is
     described by the sentence its popover says (`filtersActive` counts it as nothing). */
  const chips: {
    readonly key: string;
    readonly full: string;
    readonly short: string;
    readonly inert: string;
    readonly clear: () => void;
  }[] = [];
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
    harness: 'Harness',
    state: 'State',
    drift: 'Drift',
    goal: 'Goal',
  };
  const ordered = (facet: Facet): string[] => {
    const order =
      facet === 'project'
        ? projects.map((one) => one.value)
        : facet === 'harness'
          ? harnesses.map((one) => one.value)
          : fixedOptions(indexed, prepared, facet).map((one) => one.value);
    return [...filters[facet]].sort(
      (a, b) =>
        (order.indexOf(a) === -1 ? order.length : order.indexOf(a)) -
        (order.indexOf(b) === -1 ? order.length : order.indexOf(b)),
    );
  };
  for (const facet of ['project', 'harness', 'state', 'drift', 'goal'] as const) {
    if (!filters[facet].length) continue;
    const text = chipText(
      facetNames[facet],
      ordered(facet).map((value) => optionLabel(facet, value, board.harnesses)),
    );
    chips.push({
      key: facet,
      ...text,
      inert:
        (facet === 'drift' || facet === 'goal') && !readable
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

  const presets = [
    {
      key: 'waiting',
      label: 'Waiting on you',
      pressed: filters.state.includes('Waiting on you'),
      disabled: false,
      press: () => toggle('state', 'Waiting on you'),
    },
    {
      key: 'today',
      label: 'Started today',
      pressed: filters.dateField === 'started' && filters.when === 'today',
      disabled: noClock,
      press: () =>
        filters.dateField === 'started' && filters.when === 'today'
          ? set({ when: 'any' })
          : set({ dateField: 'started', when: 'today' }),
    },
    ...(board.annotate
      ? [
          {
            key: 'drift',
            label: 'Drift recorded',
            pressed: filters.drift.includes('recorded'),
            disabled: false,
            press: () => toggle('drift', 'recorded'),
          },
        ]
      : []),
  ];

  const windowNote = (
    <WindowNote
      filters={prepared.filters}
      prepared={prepared}
      board={board}
      onSwitch={() => set({ dateField: 'active' })}
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
            placeholder="Search titles, goals and prompts"
            aria-keyshortcuts="/"
            autoComplete="off"
            spellCheck={false}
            className="pl-9 pr-24 [&::-webkit-search-cancel-button]:appearance-none"
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
        <div role="group" aria-label="Filters" className="flex flex-wrap gap-2">
          <FilterButton facet="date" name="Date" selected={filters.when === 'any' ? 0 : 1}>
            {noClock ? <p className={SENTENCE}>{NO_CLOCK}</p> : null}
            <p id={`${searchId}-by`} className={NOTE}>
              Filter by
            </p>
            <RadioGroup
              aria-labelledby={`${searchId}-by`}
              value={filters.dateField}
              disabled={noClock}
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
              disabled={noClock}
              onValueChange={(value) => set({ when: value as When })}
            >
              {WHENS.map((when) => (
                <Label key={when} className={ROW} data-filter-option={`when:${when}`}>
                  <KeyedRadio name={`when:${when}`} value={when} />
                  <span className="min-w-0 flex-1" data-filter-label>
                    {whenLabel(when, filters.dateField)}
                  </span>
                  {noClock ? null : (
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
                inPopover="date"
                checked={filters.includeUnstamped}
                disabled={noClock}
                onCheckedChange={(checked) => set({ includeUnstamped: checked })}
              />
              <span className="min-w-0 flex-1">{`Also show sessions with no ${stamped} (${String(dates.unstamped)})`}</span>
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
            {windowNote}
            {board.showAll ? (
              <div className="flex flex-col items-start gap-1" data-sessions-all-note>
                <p className={NOTE}>
                  {`Showing all stored sessions. ${board.hours ? `Sessions not active in the last ${HOURS_WORD(board.hours)}` : 'Sessions that were not recently active'} were not fully read, so their start time, title or model may not be published.`}
                </p>
                <a
                  data-slot="button-link"
                  className={`${buttonVariants({ variant: 'native' })} inline-flex items-center text-foreground underline`}
                  href={showAllHref(false)}
                >
                  {board.hours
                    ? `Show only the last ${HOURS_WORD(board.hours)}`
                    : 'Show only recently active sessions'}
                </a>
              </div>
            ) : null}
          </FilterButton>
          <FilterButton facet="project" name="Project" selected={filters.project.length}>
            <ProjectList
              options={projects}
              chosen={filters.project}
              onToggle={(value) => toggle('project', value)}
            />
            {filters.project.length ? (
              <Button type="button" onClick={() => set({ project: [] })}>
                Clear project filter
              </Button>
            ) : null}
          </FilterButton>
          <FilterButton facet="harness" name="Harness" selected={filters.harness.length}>
            <OptionList
              facet="harness"
              name="Harness"
              options={harnesses}
              chosen={filters.harness}
              onToggle={(value) => toggle('harness', value)}
            />
          </FilterButton>
          <FilterButton facet="state" name="State" selected={filters.state.length}>
            <OptionList
              facet="state"
              name="State"
              options={fixedOptions(indexed, prepared, 'state')}
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
          </FilterButton>
          <FilterButton facet="drift" name="Drift" selected={filters.drift.length}>
            {readable ? (
              <>
                <OptionList
                  facet="drift"
                  name="Drift"
                  options={fixedOptions(indexed, prepared, 'drift')}
                  chosen={filters.drift}
                  onToggle={(value) => toggle('drift', value)}
                />
                <Separator />
                <p className={NOTE}>
                  Drift recorded means a check or a stored reading found the session moving away
                  from the words you gave it.
                </p>
                <p className={NOTE}>
                  A session nobody checked looks the same as one that was checked and found nothing,
                  so Compass offers no &quot;No drift&quot; filter.
                </p>
              </>
            ) : (
              <p className={SENTENCE} data-sessions-annotations-off>
                {annotationSentence(board, 'drift')}
              </p>
            )}
          </FilterButton>
          <FilterButton facet="goal" name="Goal" selected={filters.goal.length}>
            {readable ? (
              <OptionList
                facet="goal"
                name="Goal"
                options={fixedOptions(indexed, prepared, 'goal')}
                chosen={filters.goal}
                onToggle={(value) => toggle('goal', value)}
              />
            ) : (
              <p className={SENTENCE} data-sessions-annotations-off>
                {annotationSentence(board, 'goal')}
              </p>
            )}
          </FilterButton>
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <span id={quickId} className="text-label text-muted-foreground">
          Quick filters
        </span>
        <div role="group" aria-labelledby={quickId} className="flex flex-wrap gap-2">
          {presets.map((preset) => (
            <Button
              key={preset.key}
              type="button"
              variant="native"
              aria-pressed={preset.pressed}
              disabled={preset.disabled}
              data-sessions-preset={preset.key}
              className="inline-flex cursor-pointer items-center rounded-control border border-solid border-[var(--line)] bg-transparent px-3 font-[family-name:var(--sans)] text-body text-muted-foreground hover:border-[var(--line-hi)] aria-pressed:border-[var(--accent)] aria-pressed:bg-[var(--raise)] aria-pressed:text-foreground disabled:border-dashed disabled:text-[color:var(--ink3)] disabled:cursor-not-allowed"
              onClick={preset.press}
            >
              {preset.label}
            </Button>
          ))}
        </div>
        <div className="ml-auto">
          <Disclosure
            variant="popover"
            disclosureKey={disclosureKey({
              project: null,
              scope: null,
              name: 'sessions-filter-counts',
            })}
            summary="How these counts work"
          >
            <p className="next-why-body">
              Each number beside an option is how many sessions on this board would show if you
              chose it, with your other filters kept. Choices inside one filter widen the list;
              separate filters and the search narrow it.
            </p>
            <p className="next-why-body">
              A session that does not publish a value is counted under its own option, never as zero
              and never as older. ACTIVE NOW and WORKING above always count the whole board.
            </p>
          </Disclosure>
        </div>
      </div>
      {chips.length ? (
        <div ref={chipBox} className="flex flex-wrap items-center gap-2" data-sessions-chips>
          {chips.map((chip, index) => (
            <Button
              key={chip.key}
              type="button"
              variant="filter-chip"
              aria-label={`Remove ${chip.full}`}
              aria-describedby={chip.inert ? noteId(chip.inert) : undefined}
              data-sessions-chip={chip.key}
              data-sessions-chip-inert={chip.inert ? '' : undefined}
              onClick={() => {
                refocus.current = index;
                chip.clear();
              }}
            >
              <span>{chip.short}</span>
              <Icon name="remove" />
            </Button>
          ))}
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
      <p className={SENTENCE} data-sessions-result>
        {resultLine(filtered, board)}
        {only ? ' Press Enter to open it.' : ''}
      </p>
      {windowNote}
      {filtered.active && filtered.shown === 0 ? (
        <div className="flex flex-col items-start gap-1.5" data-sessions-nothing>
          <p className={`${SENTENCE} text-foreground`}>No session matches these filters.</p>
          <Button type="button" onClick={actions.clearAll}>
            Clear filters
          </Button>
          {terms.length ? (
            <p className={SENTENCE}>
              Search reads titles, goals and prompts, not the conversation itself.
            </p>
          ) : null}
          {board.showAll ? null : (
            <>
              <p className={SENTENCE}>
                {board.hours
                  ? `Sessions not active in the last ${HOURS_WORD(board.hours)} are not loaded.`
                  : 'Sessions not recently active are not loaded.'}
              </p>
              <ShowAllLink />
            </>
          )}
          {board.cleared > 0 ? (
            <p className={SENTENCE}>
              {board.cleared === 1
                ? '1 session you marked handled is not on this board.'
                : `${String(board.cleared)} sessions you marked handled are not on this board.`}
            </p>
          ) : null}
          {prepared.filters.state.includes('Waiting on you')
            ? coverage.map((line) => (
                <p key={line} className={SENTENCE} data-sessions-wait-coverage>
                  {line}
                </p>
              ))
            : null}
        </div>
      ) : null}
      {waiting.length ? (
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
              label={`Open session ${waiting[0].row.session.titleText}`}
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
              See them on Attention
            </RouteAnchor>
          ) : null}
        </Alert>
      ) : null}
      {missing ? (
        <div className="flex flex-wrap items-center gap-x-3" data-sessions-unstamped>
          <p className={SENTENCE}>{unstampedLine(missing, prepared.filters.dateField)}</p>
          <Button type="button" onClick={() => set({ includeUnstamped: true })}>
            Include them
          </Button>
        </div>
      ) : null}
    </search>
  );
}

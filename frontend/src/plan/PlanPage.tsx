import { type ReactNode, useId } from 'react';
import { PLAN_WORDS, SESSION_ROW_WORDS, SHOWN } from '../language/glossary';
import { cn } from '../lib/utils';
import { fragmentForRoute, type SessionRoute } from '../router/grammar';
import { RouteAnchor } from '../sessions/RouteAnchor';
import { Badge } from '../ui/badge';
import { Card } from '../ui/card';
import { Icon, SESSION_TILE_ICONS } from '../ui/icons';
import { titleLink } from '../ui/link';
import type {
  PlanGoal,
  PlanLaneState,
  PlanModel,
  PlanNote,
  PlanRepoDate,
  PlanSessionReference,
  PlanTrackerStatus,
} from './model';
import { SOURCE_REFUSALS } from './model';

/* Group order on a goal card. The counted groups come first; the count is done lanes over the
   lanes rendered in them. Dropped lanes, then lanes whose status is unknown, sit apart below. */
const countedLaneLabels = {
  blocked: PLAN_WORDS.blocked,
  waiting: PLAN_WORDS.waiting,
  running: PLAN_WORDS.inProgress,
  not_started: PLAN_WORDS.planned,
  done: PLAN_WORDS.done,
} as const;
const trackerLabels = {
  ...countedLaneLabels,
  dropped: PLAN_WORDS.dropped,
} as const satisfies Record<Exclude<PlanTrackerStatus, 'Status not recognised'>, string>;
const laneGroups: readonly { readonly state: PlanLaneState; readonly label: string }[] = [
  ...(Object.keys(trackerLabels) as (keyof typeof trackerLabels)[]).map((state) => ({
    state,
    label: trackerLabels[state],
  })),
  { state: 'Status not recognised', label: PLAN_WORDS.statusNotRecognised },
  { state: null, label: PLAN_WORDS.notMeasured },
];

const sessionStates = {
  working: { word: SESSION_ROW_WORDS.working, ink: 'text-[var(--status-working-ink)]' },
  waiting: { word: SESSION_ROW_WORDS.waitingOnYou, ink: 'text-[var(--status-waiting-ink)]' },
  quiet: { word: SESSION_ROW_WORDS.quiet, ink: 'text-[var(--status-quiet-ink)]' },
  ended: { word: SESSION_ROW_WORDS.ended, ink: 'text-[var(--status-ended-ink)]' },
  unknown: { word: SESSION_ROW_WORDS.stateNotKnown, ink: 'text-[var(--ink2)]' },
} as const;

const rowLayout = 'flex min-w-0 flex-col items-start gap-x-6 gap-y-1 leading-6 sm:flex-row';

function PlanSection({
  title,
  sourceLabels = [],
  children,
}: {
  readonly title: string;
  readonly sourceLabels?: readonly string[];
  readonly children: ReactNode;
}) {
  const headingId = useId();
  return (
    <section aria-labelledby={headingId} className="grid min-w-0 gap-3">
      <div>
        <h2 id={headingId} className="m-0 text-head font-bold">
          {title}
        </h2>
        {sourceLabels.length > 0 && (
          <p className="m-0 text-label text-muted-foreground">
            From <span data-authored>{[...new Set(sourceLabels)].join(', ')}</span>
          </p>
        )}
      </div>
      {children}
    </section>
  );
}

const datePrefixes = {
  changed: 'Changed ',
  proposed: '',
  due: 'Due ',
  target: `${PLAN_WORDS.target} `,
  updated: `${PLAN_WORDS.updated} `,
  completed: `${PLAN_WORDS.completed} `,
} satisfies Record<PlanRepoDate['kind'], string>;

function RepoDate({ date }: { readonly date: PlanRepoDate }) {
  const parsed = date.at ? new Date(date.at) : null;
  const hasDate = parsed !== null && !Number.isNaN(parsed.getTime());
  if (date.kind !== 'proposed' && !hasDate) return null;

  return (
    <p className="m-0 flex flex-wrap gap-x-2 text-label text-muted-foreground">
      {date.kind === 'proposed' && <span>Proposed, not merged</span>}
      {hasDate && (
        <time dateTime={date.at ?? undefined}>
          {datePrefixes[date.kind]}
          {parsed.toLocaleDateString(undefined, {
            dateStyle: 'medium',
            ...(/^\d{4}-\d{2}-\d{2}$/.test(date.at ?? '') ? { timeZone: 'UTC' } : {}),
          })}
        </time>
      )}
    </p>
  );
}

function PlanSessionRef({
  route,
  name,
  state,
}: Pick<PlanSessionReference, 'name' | 'state'> & { readonly route: SessionRoute }) {
  const { word, ink } = sessionStates[state];
  return (
    <RouteAnchor
      route={route}
      label={`Open session ${name}, ${word}`}
      className={cn(
        titleLink,
        'inline-flex items-center justify-start gap-1.5 rounded-control text-label text-muted-foreground sm:justify-end',
      )}
    >
      <span role="img" aria-label={word} className={cn('grid shrink-0 place-items-center', ink)}>
        <Icon name={SESSION_TILE_ICONS[word]} size={16} />
      </span>
      <span className="max-w-[28ch] truncate" data-authored>
        {name}
      </span>
    </RouteAnchor>
  );
}

/* A session opened from Plan names Plan as its origin, so its crumb and Escape come back here. */
function fromPlan(key: SessionRoute): SessionRoute {
  return { ...key, from: 'plan' };
}

function SessionReferences({
  sessions,
}: {
  readonly sessions: readonly PlanSessionReference[] | null;
}) {
  if (!sessions?.length) return null;
  const shown = sessions.slice(0, 3);
  const remaining = sessions.length - shown.length;
  return (
    <div className="flex max-w-full flex-none flex-col items-start sm:items-end">
      {shown.map(({ key, name, state }) => (
        <PlanSessionRef
          key={fragmentForRoute(key)}
          route={fromPlan(key)}
          name={name}
          state={state}
        />
      ))}
      {remaining > 0 && (
        <p className="m-0 text-label text-muted-foreground">and {remaining} more</p>
      )}
    </div>
  );
}

function WaitingOnYou({
  asks,
  waitingSessions,
  trackerAsks,
}: Pick<PlanModel, 'asks' | 'waitingSessions' | 'trackerAsks'>) {
  const waitingId = useId();
  const hasRows = asks.length > 0 || !!trackerAsks?.length || waitingSessions.length > 0;
  return (
    <PlanSection title={SESSION_ROW_WORDS.waitingOnYou}>
      {trackerAsks === null && (
        <p className="m-0 text-muted-foreground">{PLAN_WORDS.trackerAsksNotMeasured}</p>
      )}
      {trackerAsks?.length === 0 && (
        <p className="m-0 text-muted-foreground">{PLAN_WORDS.noTrackerAsks}</p>
      )}
      {!hasRows ? (
        trackerAsks === undefined && (
          <p className="m-0 text-muted-foreground">
            No open asks or sessions waiting for a reply are listed.
          </p>
        )
      ) : (
        <Card className="grid gap-5 border-l-2 border-l-[var(--amber)] max-sm:p-4">
          {asks.length > 0 && (
            <div className="grid gap-2">
              <h3 className="m-0 flex items-center gap-2 text-value font-bold">
                <Icon name="help" className="shrink-0 text-[var(--amber)]" />
                Open asks
              </h3>
              <ul role="list" aria-label="Open asks" className="m-0 grid list-none gap-3 p-0">
                {asks.map(({ id, text, at, timeLabel, source, lane, sessions }) => {
                  const date = at && timeLabel ? new Date(at) : null;
                  const hasDate = date !== null && !Number.isNaN(date.getTime());
                  return (
                    <li key={id} className={rowLayout}>
                      <div
                        className={cn(
                          'grid min-w-0 flex-1 gap-1',
                          !!sessions?.length && 'sm:mt-2.5',
                        )}
                      >
                        {text === null ? (
                          <p className="m-0 max-w-[var(--measure)] font-semibold">
                            {PLAN_WORDS.askWithoutText}
                          </p>
                        ) : (
                          <p className="m-0 max-w-[var(--measure)] font-semibold" data-authored>
                            {text}
                          </p>
                        )}
                        <p className="m-0 text-label leading-relaxed text-muted-foreground">
                          {hasDate ? (
                            <>
                              Asked{' '}
                              <time dateTime={at ?? undefined}>
                                {date.toLocaleString(undefined, {
                                  dateStyle: 'medium',
                                  timeStyle: 'short',
                                })}
                              </time>
                              {` · ${timeLabel} · `}
                            </>
                          ) : (
                            ''
                          )}
                          <span data-authored>{source}</span>
                        </p>
                        {lane && (
                          <p className="m-0 text-label leading-relaxed text-muted-foreground">
                            {PLAN_WORDS.lane}: <span data-authored>{lane.title}</span>
                          </p>
                        )}
                      </div>
                      <SessionReferences sessions={sessions} />
                    </li>
                  );
                })}
              </ul>
            </div>
          )}
          {!!trackerAsks?.length && (
            <div className="grid gap-2">
              <h3 className="m-0 flex items-center gap-2 text-value font-bold">
                <Icon name="help" className="shrink-0 text-[var(--amber)]" />
                {PLAN_WORDS.trackerAsks}
              </h3>
              <ul
                role="list"
                aria-label={PLAN_WORDS.trackerAsks}
                className="m-0 grid list-none gap-3 p-0"
              >
                {trackerAsks.map(({ lane, title, source, linkHost }) => (
                  <li key={lane} className="grid min-w-0 gap-1">
                    <a
                      href={`https://${linkHost}`}
                      target="_blank"
                      rel="noreferrer"
                      className={cn(titleLink, 'w-fit max-w-[var(--measure)] font-semibold')}
                      data-authored
                    >
                      {title}
                    </a>
                    <p className="m-0 text-label leading-relaxed text-muted-foreground">
                      {source} · {linkHost}
                    </p>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {waitingSessions.length > 0 && (
            <div className="grid gap-2">
              <h3 className="m-0 flex items-center gap-2 text-value font-bold">
                <Icon name="waiting" className="shrink-0 text-[var(--amber)]" />
                Sessions waiting for a reply
              </h3>
              <ul
                role="list"
                aria-label="Sessions waiting for a reply"
                className="m-0 grid list-none gap-3 p-0"
              >
                {waitingSessions.map(
                  ({ key, title, harnessLabel, request, requestAuthored }, index) => {
                    const descriptorId = `${waitingId}-${index}-descriptor`;
                    const requestId = `${waitingId}-${index}-request`;
                    return (
                      <li key={fragmentForRoute(key)}>
                        <RouteAnchor
                          route={fromPlan(key)}
                          label={title}
                          extra={{ 'aria-describedby': `${descriptorId} ${requestId}` }}
                          className="group grid gap-1 rounded-control text-foreground no-underline"
                        >
                          <span
                            className="max-w-[var(--measure)] font-semibold underline-offset-[3px] group-hover:underline group-focus-visible:underline"
                            data-authored
                          >
                            {title}
                          </span>
                          <span id={descriptorId} className="text-label text-muted-foreground">
                            {harnessLabel}
                            {key.project.trim() && (
                              <>
                                {' · '}
                                <span data-authored>{key.project}</span>
                              </>
                            )}
                          </span>
                          <span
                            id={requestId}
                            className="max-w-[var(--measure)] text-muted-foreground"
                            data-authored={requestAuthored || undefined}
                          >
                            {request}
                          </span>
                        </RouteAnchor>
                      </li>
                    );
                  },
                )}
              </ul>
            </div>
          )}
        </Card>
      )}
    </PlanSection>
  );
}

function notCountedNote(dropped: boolean, unknown: boolean) {
  if (dropped && unknown) return 'Dropped lanes and lanes without a known status are not counted.';
  return dropped
    ? 'Dropped lanes are not counted.'
    : 'Lanes without a known status are not counted.';
}

function GoalCard({ goal }: { readonly goal: PlanGoal }) {
  const headingId = useId();
  const groups = laneGroups
    .map(({ state, label }) => ({
      state,
      label,
      lanes: goal.lanes.filter((lane) => lane.state === state),
    }))
    .filter(({ lanes }) => lanes.length > 0);
  const counted = groups.filter(
    ({ state }) => state !== null && Object.hasOwn(countedLaneLabels, state),
  );
  const total = counted.reduce((count, { lanes }) => count + lanes.length, 0);
  const done = counted.find(({ state }) => state === 'done')?.lanes.length ?? 0;
  const apart = groups.filter((group) => !counted.includes(group));
  const dropped = apart.some(({ state }) => state === 'dropped');
  const unknown = apart.some(({ state }) => state !== 'dropped');

  return (
    <Card as="article" aria-labelledby={headingId} className="grid gap-4 max-sm:p-4">
      <h3 id={headingId} className="m-0 text-value font-bold" data-authored>
        {goal.title}
      </h3>
      {goal.date && <RepoDate date={goal.date} />}
      {goal.additionalDates?.map((date) => (
        <RepoDate key={date.kind} date={date} />
      ))}
      {goal.proposal && <p className="m-0 text-label text-muted-foreground">{goal.proposal}</p>}
      <dl className="m-0 grid gap-1">
        <dt className="text-label font-semibold text-muted-foreground">Done when</dt>
        <dd
          className="m-0 max-w-[var(--measure)]"
          data-authored={goal.doneWhen !== null || undefined}
        >
          {goal.doneWhen ?? 'No completion condition is listed.'}
        </dd>
      </dl>
      {groups.length === 0 ? (
        <p className="m-0 text-muted-foreground">No lanes serve this goal yet</p>
      ) : (
        <>
          {total === 0 ? (
            <p className="m-0 text-muted-foreground">
              {unknown ? 'Lane progress is not measured.' : notCountedNote(dropped, false)}
            </p>
          ) : (
            <div className="grid gap-1">
              <p className="m-0 font-semibold">
                {done} of {total} {total === 1 ? 'lane is' : 'lanes are'} done
              </p>
              {apart.length > 0 && (
                <p className="m-0 text-label text-muted-foreground">
                  {notCountedNote(dropped, unknown)}
                </p>
              )}
            </div>
          )}
          <div className="grid gap-3">
            {groups.map(({ label, lanes }) => (
              <div
                key={label}
                className="grid min-w-0 gap-1 border-0 border-solid border-[var(--rule)] not-first:border-t not-first:pt-3"
              >
                <h4 className="m-0 text-label font-semibold text-muted-foreground">{label}</h4>
                <ul role="list" aria-label={label} className="m-0 list-none p-0">
                  {lanes.map(({ id, title, sessions, additionalDates }) => (
                    <li
                      key={id}
                      className={cn(
                        rowLayout,
                        'border-0 border-solid border-[var(--rule)] py-3 first:pt-0 last:pb-0 not-first:border-t',
                      )}
                    >
                      <div
                        className={cn(
                          'min-w-0 flex-1 text-body',
                          !!sessions?.length && 'sm:mt-2.5',
                        )}
                      >
                        <span data-authored>{title}</span>
                        {additionalDates?.map((date) => (
                          <RepoDate key={date.kind} date={date} />
                        ))}
                      </div>
                      <SessionReferences sessions={sessions} />
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </>
      )}
    </Card>
  );
}

function NotesList({
  notes,
  label,
}: {
  readonly notes: readonly PlanNote[];
  readonly label?: string;
}) {
  return (
    <ul role="list" aria-label={label} className="m-0 grid list-none gap-4 p-0">
      {notes.map(({ id, title, summary, date, linkHosts }) => (
        <li key={id} className="grid gap-1">
          <p className="m-0 max-w-[var(--measure)] font-semibold" data-authored>
            {title}
          </p>
          {summary && (
            <p className="m-0 max-w-[var(--measure)] text-muted-foreground" data-authored>
              {summary}
            </p>
          )}
          {date && <RepoDate date={date} />}
          {linkHosts && linkHosts.length > 0 && (
            <p className="m-0 text-label text-muted-foreground" data-authored>
              {linkHosts.join(', ')}
            </p>
          )}
        </li>
      ))}
    </ul>
  );
}

function Tracker({ items }: { readonly items: PlanModel['tracker'] }) {
  return (
    <PlanSection title="Tracker" sourceLabels={items.map((item) => item.source)}>
      {items.length === 0 ? (
        <p className="m-0 text-muted-foreground">No tracker items are listed.</p>
      ) : (
        <Card className="max-sm:p-4">
          <ul role="list" className="m-0 grid list-none gap-4 p-0">
            {items.map(({ id, title, status, date }) => (
              <li key={id} className="flex flex-wrap items-start justify-between gap-x-4 gap-y-1.5">
                <div className="grid min-w-0 gap-1">
                  <p className="m-0 max-w-[var(--measure)] font-semibold" data-authored>
                    {title}
                  </p>
                  {date && <RepoDate date={date} />}
                </div>
                {status === 'Status not recognised' ? (
                  <span className="text-label text-muted-foreground">
                    {PLAN_WORDS.statusNotRecognised}
                  </span>
                ) : (
                  <Badge>{trackerLabels[status]}</Badge>
                )}
              </li>
            ))}
          </ul>
        </Card>
      )}
    </PlanSection>
  );
}

function PlanSources({ sources, limits }: Pick<PlanModel, 'sources' | 'limits'>) {
  return (
    <footer className="mt-8 grid gap-6 border-0 border-t border-solid border-[var(--rule)] pt-6">
      <PlanSection title="Sources">
        {sources.length === 0 ? (
          <p className="m-0 text-muted-foreground">No sources are listed.</p>
        ) : (
          <ul role="list" className="m-0 grid list-none gap-2 p-0">
            {sources.map((source) => (
              <li key={source.id} className="flex flex-wrap items-baseline gap-x-3">
                <span className="font-semibold" data-authored>
                  {source.name}
                </span>
                {source.status === 'tracker' ? (
                  <span className="min-w-0 text-label text-muted-foreground">
                    {source.state === 'ok' ? (
                      'Read'
                    ) : source.state === 'empty' ? (
                      PLAN_WORDS.noLanesFound
                    ) : (
                      <>
                        {PLAN_WORDS.notMeasured}. <span>{source.detail}</span>
                      </>
                    )}
                  </span>
                ) : source.status === 'ok' ? (
                  <span className="text-label text-muted-foreground">
                    {source.read === undefined ? 'Read' : `${source.read} read`}
                  </span>
                ) : (
                  <>
                    <span className="text-label font-semibold text-muted-foreground">Refused</span>
                    <span className="text-label text-muted-foreground">
                      {SOURCE_REFUSALS[source.reason]}
                    </span>
                  </>
                )}
              </li>
            ))}
          </ul>
        )}
      </PlanSection>
      <PlanSection title="What Compass can't see">
        <p className="m-0 max-w-[var(--measure)] text-muted-foreground">{limits}</p>
      </PlanSection>
    </footer>
  );
}

const pageLayout =
  'mx-auto max-w-5xl px-4 py-6 leading-relaxed [overflow-wrap:anywhere] sm:px-8 sm:py-8';

export function RefusedPlanPage({ reason }: { readonly reason: string }) {
  const detail: Readonly<Record<string, string>> = {
    'malformed settings': 'The Plan settings did not have the expected format.',
    'could not identify a private root':
      'Compass could not identify a private root in the Plan settings.',
    'settings are inside a repository': 'Keep the Plan settings outside a Git repository.',
    'symbolic link': 'The Plan settings file is a symbolic link.',
    'hard link': 'The Plan settings file has another name.',
    private: 'The Plan settings file is marked private.',
    'not an owned regular file': 'Use a regular Plan settings file you own.',
    'over the byte cap': 'The Plan settings file exceeds the size limit.',
    'file changed before it could be read': 'The Plan settings file changed during the read.',
    'guarded plan reads are unavailable on this platform':
      'Compass cannot read Plan settings on this platform.',
  };
  return (
    <PlanNotice>
      {Object.hasOwn(detail, reason) ? detail[reason] : 'The Plan settings could not be read.'}
    </PlanNotice>
  );
}

/* A Plan page that has no plan to draw: the heading and one sentence, as a region named Plan. */
function PlanNotice({ children }: { readonly children: ReactNode }) {
  const headingId = useId();
  return (
    <section
      aria-labelledby={headingId}
      data-next-view-body="plan"
      className={cn(pageLayout, 'grid gap-3')}
    >
      <h1 id={headingId} className="m-0 text-hero leading-tight font-extrabold">
        {SHOWN.plan}
      </h1>
      <p className="m-0 text-muted-foreground">{children}</p>
    </section>
  );
}

export function PlanReadFailed() {
  return (
    <PlanNotice>Compass could not read the plan. It tries again on the next refresh.</PlanNotice>
  );
}

export function PlanPage({ model }: { readonly model: PlanModel }) {
  const headingId = useId();
  // A note the decision log has not marked decided never sits under Product decisions.
  const decided = model.design.filter((note) => note.decided !== false);
  const undecided = model.design.filter((note) => note.decided === false);
  const goalOccurrences = new Map<string, number>();
  return (
    <div className={pageLayout} data-next-view-body="plan">
      <section aria-labelledby={headingId} className="grid gap-8">
        <h1 id={headingId} className="m-0 text-hero leading-tight font-extrabold">
          {SHOWN.plan}
        </h1>
        <WaitingOnYou
          asks={model.asks}
          waitingSessions={model.waitingSessions}
          trackerAsks={model.trackerAsks}
        />
        <PlanSection title="Goals">
          {model.goals.length === 0 ? (
            <p className="m-0 text-muted-foreground">
              {model.trackerIncomplete ? 'Lane progress is not measured.' : 'No goals are listed.'}
            </p>
          ) : (
            model.goals.map((goal) => {
              // File goals can share an ID. Removing another source must keep this card mounted.
              const occurrence = goalOccurrences.get(goal.id) ?? 0;
              goalOccurrences.set(goal.id, occurrence + 1);
              return <GoalCard key={`${goal.id}:${occurrence}`} goal={goal} />;
            })
          )}
        </PlanSection>
        {model.fileSections.design && (
          <PlanSection title="Design" sourceLabels={model.design.map((note) => note.source)}>
            {model.design.length === 0 ? (
              <p className="m-0 text-muted-foreground">No product decisions are listed.</p>
            ) : (
              <Card className="grid gap-4 max-sm:p-4">
                {[
                  { label: PLAN_WORDS.productDecisions, notes: decided },
                  { label: PLAN_WORDS.notDecidedYet, notes: undecided },
                ]
                  .filter(({ notes }) => notes.length > 0)
                  .map(({ label, notes }) => (
                    <div
                      key={label}
                      className="grid gap-3 border-0 border-solid border-[var(--rule)] not-first:border-t not-first:pt-4"
                    >
                      <h3 className="m-0 text-value font-bold">{label}</h3>
                      <NotesList notes={notes} label={label} />
                    </div>
                  ))}
              </Card>
            )}
          </PlanSection>
        )}
        {model.fileSections.tracker && <Tracker items={model.tracker} />}
        {model.fileSections.diagrams && (
          <PlanSection title="Diagrams" sourceLabels={model.diagrams.map((note) => note.source)}>
            {model.diagrams.length === 0 ? (
              <p className="m-0 text-muted-foreground">No diagrams are listed.</p>
            ) : (
              <Card className="max-sm:p-4">
                <NotesList notes={model.diagrams} />
              </Card>
            )}
          </PlanSection>
        )}
      </section>
      <PlanSources sources={model.sources} limits={model.limits} />
    </div>
  );
}

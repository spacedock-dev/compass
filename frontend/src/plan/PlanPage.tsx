import { type ReactNode, useId } from 'react';
import { PLAN_WORDS, SESSION_ROW_WORDS, SHOWN } from '../language/glossary';
import { cn } from '../lib/utils';
import { fragmentForRoute } from '../router/grammar';
import { Badge } from '../ui/badge';
import { buttonVariants } from '../ui/button';
import { Card } from '../ui/card';
import { Icon, SESSION_TILE_ICONS } from '../ui/icons';
import { titleLink } from '../ui/link';
import type {
  PlanGoal,
  PlanLaneState,
  PlanModel,
  PlanNote,
  PlanRefusalReason,
  PlanRepoDate,
  PlanSessionReference,
} from './model';

const stateLabels = {
  blocked: PLAN_WORDS.blocked,
  'in-progress': PLAN_WORDS.inProgress,
  planned: 'Planned',
  done: 'Done',
  unpublished: 'Status not published',
} satisfies Record<PlanLaneState, string>;

const sessionStates = {
  working: { word: SESSION_ROW_WORDS.working, ink: 'text-[var(--status-working-ink)]' },
  waiting: { word: SESSION_ROW_WORDS.waitingOnYou, ink: 'text-[var(--status-waiting-ink)]' },
  quiet: { word: SESSION_ROW_WORDS.quiet, ink: 'text-[var(--status-quiet-ink)]' },
  ended: { word: SESSION_ROW_WORDS.ended, ink: 'text-[var(--status-ended-ink)]' },
  unknown: { word: SESSION_ROW_WORDS.stateNotKnown, ink: 'text-[var(--ink2)]' },
} as const;

const rowLayout = 'flex min-w-0 flex-col items-start gap-x-6 gap-y-1 leading-6 sm:flex-row';

const refusalReasons = {
  unknown: 'The source could not be read.',
  'git reads are off': 'Git reads are off.',
  unreadable: 'The source could not be read.',
  malformed: 'The source did not have the expected format.',
  symlink: 'The file is a symbolic link.',
  'hard-link': 'The same file has another name.',
  private: 'Marked private.',
  'unknown-structural-status': 'Compass did not recognise a required status.',
} satisfies Record<PlanRefusalReason, string>;

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
            From {[...new Set(sourceLabels)].join(', ')}
          </p>
        )}
      </div>
      {children}
    </section>
  );
}

function RepoDate({ date }: { readonly date: PlanRepoDate }) {
  const parsed = date.at ? new Date(date.at) : null;
  const hasDate = parsed !== null && !Number.isNaN(parsed.getTime());
  if (date.kind === 'changed' && !hasDate) return null;

  return (
    <p className="m-0 flex flex-wrap gap-x-2 text-label text-muted-foreground">
      {date.kind === 'proposed' && <span>Proposed, not merged</span>}
      {hasDate && (
        <time dateTime={date.at ?? undefined}>
          {date.kind === 'changed' && 'Changed '}
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
  href,
  name,
  state,
}: Pick<PlanSessionReference, 'name' | 'state'> & { readonly href: string }) {
  const { word, ink } = sessionStates[state];
  return (
    <a
      href={href}
      aria-label={`Open session ${name}, ${word}`}
      className={cn(
        buttonVariants({ variant: 'native' }),
        titleLink,
        'inline-flex items-center justify-start gap-1.5 rounded-control text-label text-muted-foreground sm:justify-end',
      )}
    >
      <span role="img" aria-label={word} className={cn('grid shrink-0 place-items-center', ink)}>
        <Icon name={SESSION_TILE_ICONS[word]} size={16} />
      </span>
      <span className="max-w-[28ch] truncate">{name}</span>
    </a>
  );
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
      {shown.map(({ key, ...session }) => {
        const href = fragmentForRoute(key);
        return <PlanSessionRef key={href} href={href} {...session} />;
      })}
      {remaining > 0 && (
        <p className="m-0 text-label text-muted-foreground">and {remaining} more</p>
      )}
    </div>
  );
}

function WaitingOnYou({ asks, waitingSessions }: Pick<PlanModel, 'asks' | 'waitingSessions'>) {
  const waitingId = useId();
  return (
    <PlanSection title={SESSION_ROW_WORDS.waitingOnYou}>
      {asks.length === 0 && waitingSessions.length === 0 ? (
        <p className="m-0 text-muted-foreground">
          No open asks or sessions waiting for a reply are listed.
        </p>
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
                        <p className="m-0 max-w-[var(--measure)] font-semibold">{text}</p>
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
                          {source}
                        </p>
                        {lane && (
                          <p className="m-0 text-label leading-relaxed text-muted-foreground">
                            {PLAN_WORDS.lane}: {lane.title}
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
                {waitingSessions.map(({ key, title, harnessLabel, request }, index) => {
                  const href = fragmentForRoute(key);
                  const descriptorId = `${waitingId}-${index}-descriptor`;
                  const requestId = `${waitingId}-${index}-request`;
                  return (
                    <li key={href}>
                      <a
                        href={href}
                        aria-label={title}
                        aria-describedby={`${descriptorId} ${requestId}`}
                        className={cn(
                          buttonVariants({ variant: 'native' }),
                          'group grid gap-1 rounded-control text-foreground no-underline',
                        )}
                      >
                        <span className="max-w-[var(--measure)] font-semibold underline-offset-[3px] group-hover:underline group-focus-visible:underline">
                          {title}
                        </span>
                        <span id={descriptorId} className="text-label text-muted-foreground">
                          {harnessLabel}
                          {key.project.trim() && ` · ${key.project}`}
                        </span>
                        <span
                          id={requestId}
                          className="max-w-[var(--measure)] text-muted-foreground"
                        >
                          {request}
                        </span>
                      </a>
                    </li>
                  );
                })}
              </ul>
            </div>
          )}
        </Card>
      )}
    </PlanSection>
  );
}

function GoalCard({ goal }: { readonly goal: PlanGoal }) {
  const headingId = useId();
  const groups = Object.entries(stateLabels)
    .map(([state, label]) => ({
      state,
      label,
      lanes: goal.lanes.filter((lane) => lane.state === state),
    }))
    .filter(({ lanes }) => lanes.length > 0);
  const total = groups.reduce((count, { lanes }) => count + lanes.length, 0);
  const done = groups.find(({ state }) => state === 'done')?.lanes.length ?? 0;

  return (
    <Card as="article" aria-labelledby={headingId} className="grid gap-4 max-sm:p-4">
      <h3 id={headingId} className="m-0 text-value font-bold">
        {goal.title}
      </h3>
      {goal.proposal && <p className="m-0 text-label text-muted-foreground">{goal.proposal}</p>}
      <dl className="m-0 grid gap-1">
        <dt className="text-label font-semibold text-muted-foreground">Done when</dt>
        <dd className="m-0 max-w-[var(--measure)]">
          {goal.doneWhen ?? 'No completion condition is listed.'}
        </dd>
      </dl>
      {total === 0 ? (
        <p className="m-0 text-muted-foreground">No lanes serve this goal yet</p>
      ) : (
        <>
          {groups.some(({ state }) => state === 'unpublished') ? (
            <p className="m-0 text-muted-foreground">Lane progress is not published.</p>
          ) : (
            <p className="m-0 font-semibold">
              {done} of {total} {total === 1 ? 'lane is' : 'lanes are'} done
            </p>
          )}
          <div className="grid gap-3">
            {groups.map(({ state, label, lanes }) => (
              <div
                key={state}
                className="grid min-w-0 gap-1 border-0 border-solid border-[var(--rule)] not-first:border-t not-first:pt-3"
              >
                <h4 className="m-0 text-label font-semibold text-muted-foreground">{label}</h4>
                <ul role="list" aria-label={label} className="m-0 list-none p-0">
                  {lanes.map(({ id, title, sessions }) => (
                    <li
                      key={id}
                      className={cn(
                        rowLayout,
                        'border-0 border-solid border-[var(--rule)] py-3 first:pt-0 last:pb-0 not-first:border-t',
                      )}
                    >
                      <span
                        className={cn(
                          'min-w-0 flex-1 text-body',
                          !!sessions?.length && 'sm:mt-2.5',
                        )}
                      >
                        {title}
                      </span>
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

function NotesList({ notes }: { readonly notes: readonly PlanNote[] }) {
  return (
    <ul role="list" className="m-0 grid list-none gap-4 p-0">
      {notes.map(({ id, title, summary, date, linkHosts }) => (
        <li key={id} className="grid gap-1">
          <p className="m-0 max-w-[var(--measure)] font-semibold">{title}</p>
          {summary && <p className="m-0 max-w-[var(--measure)] text-muted-foreground">{summary}</p>}
          {date && <RepoDate date={date} />}
          {linkHosts && linkHosts.length > 0 && (
            <p className="m-0 text-label text-muted-foreground">{linkHosts.join(', ')}</p>
          )}
        </li>
      ))}
    </ul>
  );
}

const trackerLabels = { ...stateLabels, waiting: 'Waiting', dropped: 'Dropped' };

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
                  <p className="m-0 max-w-[var(--measure)] font-semibold">{title}</p>
                  {date && <RepoDate date={date} />}
                </div>
                {status === 'unrecognised' ? (
                  <span className="text-label text-muted-foreground">Status not recognised</span>
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
                <span className="font-semibold">{source.name}</span>
                {source.status === 'ok' ? (
                  <span className="text-label text-muted-foreground">Read</span>
                ) : (
                  <>
                    <span className="text-label font-semibold text-muted-foreground">Refused</span>
                    <span className="text-label text-muted-foreground">
                      {refusalReasons[source.reason]}
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
    <section className={cn(pageLayout, 'grid gap-3')}>
      <h1 className="m-0 text-hero leading-tight font-extrabold">{SHOWN.plan}</h1>
      <p className="m-0 text-muted-foreground">
        {Object.hasOwn(detail, reason) ? detail[reason] : 'The Plan settings could not be read.'}
      </p>
    </section>
  );
}

export function PlanPage({ model }: { readonly model: PlanModel }) {
  const headingId = useId();
  return (
    <div className={pageLayout}>
      <section aria-labelledby={headingId} className="grid gap-8">
        <h1 id={headingId} className="m-0 text-hero leading-tight font-extrabold">
          {SHOWN.plan}
        </h1>
        <WaitingOnYou asks={model.asks} waitingSessions={model.waitingSessions} />
        <PlanSection title="Goals">
          {model.goals.length === 0 ? (
            <p className="m-0 text-muted-foreground">No goals are listed.</p>
          ) : (
            model.goals.map((goal) => <GoalCard key={goal.id} goal={goal} />)
          )}
        </PlanSection>
        <PlanSection title="Design" sourceLabels={model.design.map((note) => note.source)}>
          {model.design.length === 0 ? (
            <p className="m-0 text-muted-foreground">No product decisions are listed.</p>
          ) : (
            <Card className="grid gap-3 max-sm:p-4">
              <h3 className="m-0 text-value font-bold">{PLAN_WORDS.productDecisions}</h3>
              <NotesList notes={model.design} />
            </Card>
          )}
        </PlanSection>
        <Tracker items={model.tracker} />
        <PlanSection title="Diagrams" sourceLabels={model.diagrams.map((note) => note.source)}>
          {model.diagrams.length === 0 ? (
            <p className="m-0 text-muted-foreground">No diagrams are listed.</p>
          ) : (
            <Card className="max-sm:p-4">
              <NotesList notes={model.diagrams} />
            </Card>
          )}
        </PlanSection>
      </section>
      <PlanSources sources={model.sources} limits={model.limits} />
    </div>
  );
}

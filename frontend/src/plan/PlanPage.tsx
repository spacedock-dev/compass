import { type ReactNode, useId } from 'react';
import { PLAN_WORDS, SESSION_ROW_WORDS } from '../language/glossary';
import { Badge } from '../ui/badge';
import { Card } from '../ui/card';
import { Icon } from '../ui/icons';
import type {
  PlanGoal,
  PlanLaneState,
  PlanModel,
  PlanNote,
  PlanRefusalReason,
  PlanRepoDate,
} from './model';

const stateLabels = {
  done: 'Done',
  'in-progress': 'In progress',
  blocked: PLAN_WORDS.blocked,
  planned: 'Planned',
} satisfies Record<PlanLaneState, string>;

const refusalReasons = {
  unreadable: 'The source could not be read.',
  malformed: 'The source did not have the expected format.',
  symlink: 'The file is a symbolic link.',
  'hard-link': 'The same file has another name.',
  private: 'Marked private.',
  'unknown-structural-status': 'Compass did not recognise a required status.',
} satisfies Record<PlanRefusalReason, string>;

const limitLabels = {
  'health-information': 'health information',
  'confidential-text': 'confidential text',
} as const;

function PlanSection({
  title,
  children,
}: {
  readonly title: string;
  readonly children: ReactNode;
}) {
  const headingId = useId();
  return (
    <section aria-labelledby={headingId} className="grid min-w-0 gap-3">
      <h2 id={headingId} className="m-0 text-head font-bold">
        {title}
      </h2>
      {children}
    </section>
  );
}

function RepoDate({ date }: { readonly date: PlanRepoDate }) {
  const label = new Date(date.at).toLocaleDateString(undefined, { dateStyle: 'medium' });
  return (
    <p className="m-0 flex flex-wrap gap-x-2 text-label text-muted-foreground">
      {date.kind === 'proposed' && <span>Proposed, not merged</span>}
      <time dateTime={date.at}>{date.kind === 'changed' ? `Changed ${label}` : label}</time>
    </p>
  );
}

function WaitingOnYou({ asks, waitingSessions }: Pick<PlanModel, 'asks' | 'waitingSessions'>) {
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
                {asks.map(({ id, text, at }) => (
                  <li key={id} className="grid gap-1">
                    <p className="m-0 max-w-[var(--measure)] font-semibold">{text}</p>
                    <p className="m-0 flex flex-wrap gap-x-2 text-label text-muted-foreground">
                      <time dateTime={at}>
                        {new Date(at).toLocaleString(undefined, {
                          dateStyle: 'medium',
                          timeStyle: 'short',
                        })}
                      </time>
                      <span>from the log</span>
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
                {waitingSessions.map(({ id, title, request }) => (
                  <li key={id} className="grid gap-1">
                    <p className="m-0 max-w-[var(--measure)] font-semibold">{title}</p>
                    <p className="m-0 max-w-[var(--measure)] text-muted-foreground">{request}</p>
                  </li>
                ))}
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
      <dl className="m-0 grid gap-1">
        <dt className="text-label font-semibold text-muted-foreground">Done when</dt>
        <dd className="m-0 max-w-[var(--measure)]">{goal.doneWhen}</dd>
      </dl>
      {total === 0 ? (
        <p className="m-0 text-muted-foreground">No lanes serve this goal yet</p>
      ) : (
        <>
          <p className="m-0 font-semibold">
            {done} of {total} {total === 1 ? 'lane is' : 'lanes are'} done
          </p>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {groups.map(({ state, label, lanes }) => (
              <div key={state} className="min-w-0 rounded-control bg-muted px-3 py-2">
                <h4 className="m-0 text-label font-semibold">{label}</h4>
                <ul role="list" aria-label={label} className="m-0 mt-1 grid list-none gap-1 p-0">
                  {lanes.map(({ id, title }) => (
                    <li key={id}>{title}</li>
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
      {notes.map(({ id, title, summary, date, linkHost }) => (
        <li key={id} className="grid gap-1">
          <p className="m-0 max-w-[var(--measure)] font-semibold">{title}</p>
          <p className="m-0 max-w-[var(--measure)] text-muted-foreground">{summary}</p>
          {date && <RepoDate date={date} />}
          {linkHost && <p className="m-0 text-label text-muted-foreground">{linkHost}</p>}
        </li>
      ))}
    </ul>
  );
}

function Tracker({ items }: { readonly items: PlanModel['tracker'] }) {
  return (
    <PlanSection title="Tracker">
      {items.length === 0 ? (
        <p className="m-0 text-muted-foreground">No tracker items are listed.</p>
      ) : (
        <Card className="max-sm:p-4">
          <ul role="list" className="m-0 grid list-none gap-4 p-0">
            {items.map(({ id, title, status, date, linkHost }) => (
              <li key={id} className="flex flex-wrap items-start justify-between gap-x-4 gap-y-1.5">
                <div className="grid min-w-0 gap-1">
                  <p className="m-0 max-w-[var(--measure)] font-semibold">{title}</p>
                  {date && <RepoDate date={date} />}
                  {linkHost && <p className="m-0 text-label text-muted-foreground">{linkHost}</p>}
                </div>
                {status === 'unrecognised' ? (
                  <span className="text-label text-muted-foreground">Status not recognised</span>
                ) : (
                  <Badge>{stateLabels[status]}</Badge>
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
        <p className="m-0 max-w-[var(--measure)] text-muted-foreground">
          Compass cannot detect {limits.map((limit) => limitLabels[limit]).join(' or ')} typed into
          these sources.
        </p>
      </PlanSection>
    </footer>
  );
}

export function PlanPage({ model }: { readonly model: PlanModel }) {
  const headingId = useId();
  return (
    <div className="mx-auto max-w-5xl px-4 py-6 leading-relaxed [overflow-wrap:anywhere] sm:px-8 sm:py-8">
      <main aria-labelledby={headingId} className="grid gap-8">
        <h1 id={headingId} className="m-0 text-hero leading-tight font-extrabold">
          Plan
        </h1>
        <WaitingOnYou asks={model.asks} waitingSessions={model.waitingSessions} />
        <PlanSection title="Goals">
          {model.goals.length === 0 ? (
            <p className="m-0 text-muted-foreground">No goals are listed.</p>
          ) : (
            model.goals.map((goal) => <GoalCard key={goal.id} goal={goal} />)
          )}
        </PlanSection>
        <PlanSection title="Design">
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
        <PlanSection title="Diagrams">
          {model.diagrams.length === 0 ? (
            <p className="m-0 text-muted-foreground">No diagrams are listed.</p>
          ) : (
            <Card className="max-sm:p-4">
              <NotesList notes={model.diagrams} />
            </Card>
          )}
        </PlanSection>
      </main>
      <PlanSources sources={model.sources} limits={model.limits} />
    </div>
  );
}

import { useId, useState, type ReactNode } from 'react';
import { dirtyEndReason } from '../attention/select';
import { delegationFigure, metricOf, useProjectWindow } from '../delegation';
import { GLOSSARY, SESSION_ROW_WORDS, SHOWN } from '../language/glossary';
import { endedAt, sessionState, sessionStateLimit, sessionTile } from '../observed';
import { RouteLink } from '../shell/RouteLink';
import { useShell } from '../shell/context';
import { formatDurationWords, formatTimestamp, observationAge } from '../shell/format';
import { MEMO_LIMIT } from '../storage';
import { Card } from '../ui/card';
import { Icon } from '../ui/icons';
import { StatusLegend } from '../ui/status-legend';
import { StatusTile } from '../ui/status-tile';
import { Textarea } from '../ui/textarea';
import { subagentIsLive } from './activity';
import { noteKey, type ProjectModel } from './model';
import { endedToday } from './projectList';
import { projectInstruction, type ProjectSession } from './projectActivity';

type Labels = ReturnType<typeof import('./projectActivity').projectSessionLabels>;

const words = SESSION_ROW_WORDS;

export function ProjectSummary({
  model,
  rows,
}: {
  readonly model: ProjectModel;
  readonly rows: readonly ProjectSession[];
}) {
  const working = rows.filter(({ state }) => state === 'Working');
  const waiting = rows.filter(({ state }) => state === 'Waiting on you');
  const flagged = rows.filter(({ reason }) => reason);
  const helpers = working.reduce(
    (total, { session }) => total + session.subagents.filter(subagentIsLive).length,
    0,
  );
  const goal = projectInstruction(rows);
  const source = goal?.current
    ? goal.dated
      ? 'the latest instruction'
      : 'a published instruction'
    : 'an earlier instruction';
  const age = formatTimestamp(goal?.at, model.generated, { style: 'same-day-relative' });
  const hasLimits = rows.some(({ session }) => sessionStateLimit(session));
  return (
    <section className="project-summary-cards" aria-label="Where this project stands">
      <ProjectCard title="Working on">
        <p className="project-answer" data-authored={Boolean(goal) || undefined}>
          {goal?.text ?? 'No instruction published'}
        </p>
        {goal ? <p>{`From ${source}${age ? `, ${age}` : ''}.`}</p> : null}
      </ProjectCard>
      <ProjectCard title="Running now">
        <p className="project-answer">
          {working.length
            ? `${String(working.length)} ${working.length === 1 ? 'session' : 'sessions'} working`
            : hasLimits
              ? 'Working state unavailable'
              : SHOWN.nothingWorking}
        </p>
        {helpers ? (
          <p>{`${String(helpers)} ${helpers === 1 ? 'helper' : GLOSSARY.helpers.plain.toLowerCase()} reported`}</p>
        ) : null}
        {hasLimits && working.length ? <p>Some session states are unavailable.</p> : null}
      </ProjectCard>
      <ProjectCard title={SHOWN.attention}>
        {waiting.length || flagged.length ? (
          <>
            <p className="project-answer project-attention-answer">
              {[
                waiting.length ? `${String(waiting.length)} waiting on you` : '',
                flagged.length ? `${String(flagged.length)} worth a look` : '',
              ]
                .filter(Boolean)
                .join(' · ')}
            </p>
            <RouteLink route={{ view: 'attention' }}>Open in Needs you</RouteLink>
          </>
        ) : (
          <p className="project-answer">
            {hasLimits
              ? 'Attention state incomplete'
              : 'Nothing reported waiting on you or worth a look'}
          </p>
        )}
      </ProjectCard>
    </section>
  );
}

function ProjectCard({
  title,
  children,
}: {
  readonly title: string;
  readonly children: ReactNode;
}) {
  const id = useId();
  return (
    <Card as="section" className="project-overview-card" aria-labelledby={id}>
      <h2 id={id}>{title}</h2>
      {children}
    </Card>
  );
}

function SessionDestination({
  project,
  row,
  className,
  children,
}: {
  readonly project: string;
  readonly row: ProjectSession;
  readonly className: string;
  readonly children: ReactNode;
}) {
  return row.identity ? (
    <RouteLink
      route={{
        view: 'session',
        project,
        session: row.identity.sid,
        harness: row.identity.harness,
        from: 'project',
      }}
      className={className}
    >
      {children}
    </RouteLink>
  ) : (
    <div className={className}>{children}</div>
  );
}

function SessionRow({
  model,
  row,
  label,
}: {
  readonly model: ProjectModel;
  readonly row: ProjectSession;
  readonly label: NonNullable<ReturnType<Labels['get']>>;
}) {
  const { session, source, reason } = row;
  const state = sessionState(session);
  const limit = sessionStateLimit(session, state);
  const time = formatTimestamp(endedAt(source) ?? source?.['started_at'], model.generated, {
    style: 'same-day-relative',
  });
  return (
    <li>
      <SessionDestination project={model.group.label} row={row} className="project-overview-row">
        {/* Every session row draws a tile, as on Sessions (owner, 2026-11-24). */}
        <StatusTile
          state={sessionTile(session, state)}
          rowState={state === 'State not published' || state === 'Waiting on child' ? null : state}
          focusable={false}
          live={session.isLive && sessionTile(session, state) === 'Working'}
        />
        <span className="project-overview-row-title">
          <strong data-authored={session.titleKnown || undefined}>{label.title}</strong>
          {limit ? (
            <span data-authored={state === 'Waiting on child' || undefined}>{limit}</span>
          ) : null}
          {state === 'Ended' && row.state === 'Waiting on you' ? <span>Waiting on you</span> : null}
          {reason ? (
            <span className="project-row-flag">
              <Icon name="worth-a-look" />
              {words.worthALook}: {reason}
            </span>
          ) : null}
          {row.identity ? null : <span>Session link unavailable</span>}
        </span>
        <span className="project-overview-row-time">
          <span>
            {label.harness}
            {label.detail ? ` · ${label.detail}` : ''}
          </span>
          {time ? <span>{`${session.isEnded ? 'Ended' : 'Started'} ${time}`}</span> : null}
        </span>
        {row.identity ? <Icon name="caret-right" className="project-overview-chevron" /> : null}
      </SessionDestination>
    </li>
  );
}

function EndResults({
  model,
  rows,
  labels,
}: {
  readonly model: ProjectModel;
  readonly rows: readonly ProjectSession[];
  readonly labels: Labels;
}) {
  const { generated, payload } = model;
  const hasClock = generated !== null && observationAge(generated, generated) !== null;
  const ends = rows.filter(({ source }) => {
    const at = endedAt(source);
    return at !== null && (!hasClock || endedToday(at, generated));
  });
  const groups = [
    {
      label: words.worthALook,
      rows: ends.filter(({ source }) => source?.['dirty'] === true),
      note: (source: ProjectSession['source']) => dirtyEndReason(source ?? {}),
    },
    {
      label: GLOSSARY.readyToWrapUp.plain,
      rows: ends.filter(({ source }) => source?.['dirty'] === false),
      note: () => 'Ended with a clean working tree',
    },
    {
      label: 'End outcome unavailable',
      rows: ends.filter(({ source }) => typeof source?.['dirty'] !== 'boolean'),
      note: () => 'No outcome was published',
    },
  ];
  const unavailable = payload['ends_observable'] === false;
  return (
    <ProjectCard title="How today’s sessions ended">
      {hasClock ? null : <p>The board has no timestamp to determine which sessions ended today.</p>}
      {unavailable ? <p>Session ends are unobservable on this board.</p> : null}
      {!ends.length && hasClock && !unavailable ? (
        <p>No session ends were reported today.</p>
      ) : null}
      {groups.map(({ label, rows, note }) =>
        rows.length ? (
          <div className="project-end-group" key={label}>
            <h3>{label}</h3>
            <ul>
              {rows.map((row) => {
                const name = labels.get(row.key);
                return (
                  <li key={row.key}>
                    <SessionDestination
                      project={model.group.label}
                      row={row}
                      className="project-end-link"
                    >
                      <strong data-authored={row.session.titleKnown || undefined}>
                        {name?.title}
                      </strong>
                      {name?.detail ? <span>{name.detail}</span> : null}
                      <span>{note(row.source)}</span>
                    </SessionDestination>
                  </li>
                );
              })}
            </ul>
          </div>
        ) : null,
      )}
    </ProjectCard>
  );
}

function TimeOnTheirOwn({ project }: { readonly project: string }) {
  const window = useProjectWindow(project);
  const figure = delegationFigure(window);
  const metric = metricOf(window);
  const span = formatDurationWords(metric.observedSec);
  return (
    <ProjectCard title="Time agents worked on their own">
      {figure.pct === null ? (
        <p>Waiting for enough recorded working time.</p>
      ) : (
        <>
          <p className="project-time-answer">{figure.pctText}</p>
          <meter
            min={0}
            max={100}
            value={figure.pct}
            aria-label="Share of working or waiting time spent working without an open request"
          />
          <p>Share of working or waiting time spent working without an open request.</p>
          <p>{`${String(metric.humanTurns)} ${metric.humanTurns === 1 ? 'intervention' : 'interventions'} inferred over ${span ?? 'the window'} of observation.`}</p>
        </>
      )}
    </ProjectCard>
  );
}

function Notes({ storageKey }: { readonly storageKey: string }) {
  const {
    controls: { memo },
  } = useShell();
  const id = useId();
  const [text, setText] = useState(() => memo.read(storageKey));
  const [feedback, setFeedback] = useState('');
  return (
    <Card as="section" className="project-overview-card">
      <h2>
        <label htmlFor={id}>Your notes</label>
      </h2>
      <p id={`${id}-privacy`}>
        Kept in this browser. Compass never sends these notes to a session.
      </p>
      <Textarea
        id={id}
        rows={3}
        value={text}
        data-authored
        aria-describedby={`${id}-privacy`}
        onChange={(event) => {
          const draft = event.target.value;
          setText(draft);
          setFeedback(
            [...draft].length > MEMO_LIMIT
              ? `Your note is over the ${String(MEMO_LIMIT)} character limit.`
              : memo.write(storageKey, draft) === 'error'
                ? 'Browser storage is unavailable. These notes are held in this tab.'
                : '',
          );
        }}
      />
      {feedback ? <p role="status">{feedback}</p> : null}
    </Card>
  );
}

export function ProjectOverview({
  model,
  rows,
  labels,
}: {
  readonly model: ProjectModel;
  readonly rows: readonly ProjectSession[];
  readonly labels: Labels;
}) {
  const storageKey = noteKey(model, 'outcome');
  return (
    <div className="project-overview-grid">
      <div>
        <ProjectCard title={SHOWN.sessions}>
          <StatusLegend />
          <ul className="project-overview-rows">
            {rows.map((row) => {
              const label = labels.get(row.key);
              return label ? (
                <SessionRow key={row.key} model={model} row={row} label={label} />
              ) : null;
            })}
          </ul>
        </ProjectCard>
        <EndResults model={model} rows={rows} labels={labels} />
      </div>
      <aside>
        <TimeOnTheirOwn project={model.group.label} />
        <Notes key={storageKey} storageKey={storageKey} />
      </aside>
    </div>
  );
}

import { useId, useState, type ReactNode } from 'react';
import { compatSessKey } from '../api/identity';
import { attentionSelectionFor } from '../attention/select';
import { delegationFigure, metricOf, useProjectWindow } from '../delegation';
import { GLOSSARY, SESSION_ROW_WORDS, SHOWN } from '../language/glossary';
import {
  endedAt,
  sessionState,
  sessionStateLimit,
  type ObservedSession,
  type Row,
} from '../observed';
import { RouteLink } from '../shell/RouteLink';
import { useShell } from '../shell/context';
import { formatDurationWords, formatTimestamp } from '../shell/format';
import { MEMO_LIMIT } from '../storage';
import { Card } from '../ui/card';
import { Icon } from '../ui/icons';
import { StatusTile } from '../ui/status-tile';
import { Textarea } from '../ui/textarea';
import { subagentIsLive } from './activity';
import { goalScope, instructionHeading } from './goal';
import { noteKey, type ProjectModel } from './model';
import { endedToday } from './projectList';

const words = SESSION_ROW_WORDS;

export function ProjectSummary({ model }: { readonly model: ProjectModel }) {
  const selection = attentionSelectionFor(model.payload);
  const project = model.group.label;
  const working = selection?.working.filter((row) => row.project === project) ?? [];
  const waiting = selection?.waitingOnYou.filter((row) => row.project === project) ?? [];
  const flagged = [...(selection?.worthALook ?? [])].filter(([row]) => row.project === project);
  const helpers = working.reduce(
    (total, row) => total + row.subagents.filter(subagentIsLive).length,
    0,
  );
  const goal = goalScope(model.group.observed, null);
  const source = instructionHeading(model.group.observed, null).toLowerCase();
  const age = formatTimestamp(goal.at, model.generated, { style: 'same-day-relative' });
  const hasLimits = model.group.observed.sessions.some((session) => sessionStateLimit(session));
  return (
    <section className="project-summary-cards" aria-label="Where this project stands">
      <ProjectCard title="Working on">
        <p className="project-answer" data-authored={goal.known || undefined}>
          {goal.known ? goal.text : 'No instruction published'}
        </p>
        {goal.known ? <p>{`From a ${source}${age ? `, ${age}` : ''}.`}</p> : null}
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

function exactSessionRoute(project: string, session: ObservedSession) {
  return {
    view: 'session',
    project,
    session: session.sid,
    harness: session.harness,
    from: 'project',
  } as const;
}

function SessionRow({
  model,
  session,
  source,
  reason,
}: {
  readonly model: ProjectModel;
  readonly session: ObservedSession;
  readonly source?: Row;
  readonly reason?: string;
}) {
  const state = sessionState(session);
  const limit = sessionStateLimit(session, state);
  const time = formatTimestamp(endedAt(source) ?? source?.['started_at'], model.generated, {
    style: 'same-day-relative',
  });
  const harness = model.harnesses.get(session.harness) ?? session.harness;
  const title = session.titleKnown ? session.titleText : SHOWN.titleNotPublished;
  return (
    <li>
      <RouteLink
        route={exactSessionRoute(model.group.label, session)}
        className="project-overview-row"
      >
        {state === 'State not published' || state === 'Waiting on child' ? (
          <span className="project-list-no-icon" />
        ) : (
          <StatusTile state={state} focusable={false} live={session.isLive} />
        )}
        <span className="project-overview-row-title">
          <strong data-authored={session.titleKnown || undefined}>{title}</strong>
          {limit ? (
            <span data-authored={state === 'Waiting on child' || undefined}>{limit}</span>
          ) : null}
          {reason ? (
            <span className="project-row-flag">
              <Icon name="worth-a-look" />
              {words.worthALook}: {reason}
            </span>
          ) : null}
        </span>
        <span className="project-overview-row-time">
          <span>{harness}</span>
          {time ? <span>{`${session.isEnded ? 'Ended' : 'Started'} ${time}`}</span> : null}
        </span>
        <Icon name="caret-right" className="project-overview-chevron" />
      </RouteLink>
    </li>
  );
}

function EndResults({
  model,
  rows,
  reasons,
  clean,
}: {
  readonly model: ProjectModel;
  readonly rows: readonly ObservedSession[];
  readonly reasons: ReadonlyMap<string, string>;
  readonly clean: ReadonlySet<string>;
}) {
  const groups = [
    {
      label: words.worthALook,
      keep: (key: string) => reasons.has(key),
      note: (key: string) => reasons.get(key),
    },
    {
      label: GLOSSARY.readyToWrapUp.plain,
      keep: (key: string) => clean.has(key),
      note: () => 'Ended with a clean working tree',
    },
    {
      label: 'End outcome unavailable',
      keep: (key: string) => !reasons.has(key) && !clean.has(key),
      note: () => 'No outcome was published',
    },
  ];
  return (
    <ProjectCard title="How today’s sessions ended">
      {rows.length ? (
        groups.map(({ label, keep, note }) => {
          const selected = rows.filter((row) => keep(compatSessKey(row)));
          return selected.length ? (
            <div className="project-end-group" key={label}>
              <h3>{label}</h3>
              <ul>
                {selected.map((row) => {
                  const key = compatSessKey(row);
                  return (
                    <li key={key}>
                      <RouteLink
                        route={exactSessionRoute(model.group.label, row)}
                        className="project-end-link"
                      >
                        <strong data-authored={row.titleKnown || undefined}>{row.titleText}</strong>
                        <span>{note(key)}</span>
                      </RouteLink>
                    </li>
                  );
                })}
              </ul>
            </div>
          ) : null;
        })
      ) : (
        <p>No session ends were reported today.</p>
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
            aria-label="Share of observed time worked independently"
          />
          <p>{`Over ${span ?? 'the observed window'}, you stepped in ${String(metric.humanTurns)} ${metric.humanTurns === 1 ? 'time' : 'times'}.`}</p>
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

export function ProjectOverview({ model }: { readonly model: ProjectModel }) {
  const { group, payload, generated } = model;
  const selection = attentionSelectionFor(payload);
  const sourceByKey = new Map(group.sessions.map((row) => [compatSessKey(row), row]));
  const rows = [
    ...new Map(
      group.observed.sessions.filter(({ sid }) => sid).map((row) => [compatSessKey(row), row]),
    ).values(),
  ];
  const reasons = new Map(
    [...(selection?.worthALook ?? [])]
      .filter(([row]) => row.project === group.label)
      .map(([row, reason]) => [compatSessKey(row), reason]),
  );
  const clean = new Set(
    (selection?.readyToWrapUp ?? [])
      .filter((row) => row.project === group.label)
      .map(compatSessKey),
  );
  const today = rows.filter((row) =>
    endedToday(endedAt(sourceByKey.get(compatSessKey(row))), generated),
  );
  const storageKey = noteKey(model, 'outcome');
  return (
    <div className="project-overview-grid">
      <div>
        <ProjectCard title={SHOWN.sessions}>
          <ul className="project-overview-rows">
            {rows.map((row) => {
              const key = compatSessKey(row);
              const source = sourceByKey.get(key);
              const reason = reasons.get(key);
              return (
                <SessionRow
                  key={key}
                  model={model}
                  session={row}
                  {...(source ? { source } : {})}
                  {...(reason ? { reason } : {})}
                />
              );
            })}
          </ul>
          {rows.length < group.observed.sessions.length && !rows.length ? (
            <p>Session links are unavailable for this project.</p>
          ) : null}
        </ProjectCard>
        <EndResults model={model} rows={today} reasons={reasons} clean={clean} />
      </div>
      <aside>
        <TimeOnTheirOwn project={group.label} />
        <Notes key={storageKey} storageKey={storageKey} />
      </aside>
    </div>
  );
}

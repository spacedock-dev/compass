import { Button } from '../ui/button';
import { Fragment } from 'react';
import { durationSince, isRecord, promptCopied, sessionKey, type Row } from '../observed/values';
import type { ObservedSession } from '../observed';
import {
  activitySubagents,
  completedTasks,
  instructionEchoes,
  progressValue,
  projectProgress,
} from './activity';
import type { ProjectModel } from './model';
import { Dot, Value } from './parts';
import { routeToken, useRouteTarget } from './routing';

/* What the project's sessions are doing now (GOING ON), how the ones that stopped ended, and the tasks
   that were done. Every figure and sentence is read off the rows drawn beside it, and an unmeasured one
   says why it is not a number. Ported from `next-activity.js`. */

const INSTRUCTION_LABELS = ['asked', 'agent', 'earlier'];

/* What the session is working on now, where the title cannot say, never without its label and the age of
   the record it came from. Nothing is drawn where it would only repeat the title. */
function Instruction({
  source,
  title,
  generated,
}: {
  readonly source: Row | undefined;
  readonly title: string;
  readonly generated: number | null;
}) {
  const instruction = source?.['instruction'];
  if (!isRecord(instruction) || promptCopied(source, 'instruction')) return null;
  const label = INSTRUCTION_LABELS.find((name) => name === String(instruction['label'] || ''));
  const text = String(instruction['text'] == null ? '' : instruction['text']).trim();
  if (!label || !text || instructionEchoes(text, title)) return null;
  const age = durationSince(generated, instruction['at']);
  return (
    <span
      className="next-activity-instruction"
      data-next-instruction={String(instruction['label'])}
    >
      <span className="next-instruction-label">{label}</span>
      {`${age === null ? ':' : `, ${age}:`} `}
      <span className="next-instruction-text">{text}</span>
    </span>
  );
}

function Subagents({
  session,
  generated,
}: {
  readonly session: ObservedSession;
  readonly generated: number | null;
}) {
  const found = activitySubagents(session, generated);
  if (!found) return null;
  return (
    <span className="next-activity-subagents" role="list" aria-label="Subagents">
      {found.pills.map((pill) => (
        <span
          key={pill.index}
          className={`next-activity-subagent${pill.live ? '' : ' next-activity-subagent--idle'}`}
          role="listitem"
          data-next-activity-subagent={String(pill.index)}
        >
          <span className="next-activity-subagent-name">{pill.name}</span>
          {pill.elapsed ? (
            <span className="next-activity-subagent-elapsed">{pill.elapsed}</span>
          ) : null}
        </span>
      ))}
      {found.remaining > 0 ? (
        <span
          className="next-activity-subagent-more"
          role="listitem"
        >{`+${String(found.remaining)} more`}</span>
      ) : null}
    </span>
  );
}

function ActivityCard({
  session,
  model,
}: {
  readonly session: ObservedSession;
  readonly model: ProjectModel;
}) {
  const route = {
    view: 'session',
    project: model.group.label,
    harness: session.harness,
    session: session.sid,
  } as const;
  const target = useRouteTarget(route);
  const key = sessionKey(session as unknown as Row);
  const source = model.group.sessions.find((candidate) => sessionKey(candidate) === key);
  return (
    <Button
      variant="native"
      type="button"
      className={`next-activity-card next-project-tone--${session.tone}`}
      data-next-going-on={session.sid}
      data-next-route={routeToken(route)}
      data-next-focus={routeToken(route)}
      onClick={target.onClick}
    >
      <span className="next-activity-title">
        <Dot session={session} />
        <Value text={session.titleText} known={session.titleKnown} />
      </span>
      <Instruction source={source} title={session.titleText} generated={model.generated} />
      <span className="next-activity-now">
        <span className="next-activity-harness">{`${session.harness} · `}</span>
        <Value text={session.nowText} known={session.nowKnown} />
      </span>
      <span>
        {'next · '}
        <Value text={session.nextText} known={session.nextKnown} />
      </span>
      <span>
        {'turn · '}
        <Value text={session.turnText} known={session.turnKnown} />
      </span>
      {session.stuckKnown ? (
        <span className="next-activity-stuck">{`stuck · ${session.stuckText}`}</span>
      ) : null}
      {session.askKnown ? (
        <span className="next-activity-question line-clamp-3">{session.askText}</span>
      ) : null}
      {session.isNeeds ? (
        <span className="next-activity-metric">{session.waitedText}</span>
      ) : (
        <Value text={session.rateText} known={session.rateKnown} className="next-activity-metric" />
      )}
      <Subagents session={session} generated={model.generated} />
    </Button>
  );
}

export function GoingOn({ model }: { readonly model: ProjectModel }) {
  const sessions = model.group.observed.sessions.filter(
    (session) => session.isLive || session.isNeeds || session.askKnown,
  );
  const empty = model.attention.length
    ? 'No session currently running. Command attention remains above.'
    : 'Nothing observed running.';
  return (
    <section className="next-project-activity" data-next-project-activity="going-on">
      <h2>GOING ON</h2>
      <div className="next-activity-cards">
        {sessions.length ? (
          sessions.map((session, index) => (
            <ActivityCard
              key={`${sessionKey(session as unknown as Row)}#${String(index)}`}
              session={session}
              model={model}
            />
          ))
        ) : (
          <p className="next-activity-empty">{empty}</p>
        )}
      </div>
    </section>
  );
}

function Ending({
  session,
  model,
}: {
  readonly session: ObservedSession;
  readonly model: ProjectModel;
}) {
  const route = {
    view: 'session',
    project: model.group.label,
    harness: session.harness,
    session: session.sid,
  } as const;
  const target = useRouteTarget(route);
  return (
    <Button
      variant="native"
      type="button"
      className={`next-project-ending next-project-tone--${session.tone}`}
      data-next-outcome={session.sid}
      data-next-route={routeToken(route)}
      data-next-focus={routeToken(route)}
      onClick={target.onClick}
    >
      <span className="next-project-ending-title">
        <span className="next-project-ending-glyph" aria-hidden="true">
          {session.outcomeGlyph}
        </span>
        <Value text={session.titleText} known={session.titleKnown} />
      </span>
      <Value
        text={session.outcomeText}
        known={session.outcomeKnown}
        className="next-project-ending-outcome"
      />
      <span>
        {`${session.harness} · git: `}
        <Value text={session.gitText} known={session.gitKnown} />
      </span>
    </Button>
  );
}

export function HowEnded({ model }: { readonly model: ProjectModel }) {
  const ended = model.group.observed.ended;
  return (
    <section className="next-project-activity" data-next-project-activity="ended">
      <h2>HOW THINGS ENDED</h2>
      <div className="next-activity-cards">
        {ended.length ? (
          ended.map((session, index) => (
            <Fragment key={`${sessionKey(session as unknown as Row)}#${String(index)}`}>
              <Ending session={session} model={model} />
            </Fragment>
          ))
        ) : (
          <p className="next-activity-empty">
            No session in this project has been observed ending.
          </p>
        )}
      </div>
    </section>
  );
}

/* The tasks sessions published as completed, and the progress across the project. A completed task is one
   a source said completed: a review that changed the course, or an agent saying it is done, is not one. */
export function CompletedWork({ model }: { readonly model: ProjectModel }) {
  const completed = completedTasks(model.group.observed.sessions);
  const progress = projectProgress(model.group.sessions);
  // Whether the section is offered is read off the raw rows and what it lists off the observed ones, as the
  // legacy page does; they are the same arrays unless a board repeats a session.
  if (!completedTasks(model.group.sessions).length && !progress) return null;
  return (
    <section className="next-project-activity" data-next-project-activity="done">
      <h2>{`COMPLETED TASKS · ${String(completed.length)}`}</h2>
      {progress ? (
        <>
          <progress
            className="next-project-progress-bar"
            value={progressValue(progress)}
            max={progress.total}
            aria-label={`${String(progress.done)} of ${String(progress.total)} tasks done`}
          />
          <span>{`${String(progress.done)} of ${String(progress.total)} done`}</span>
        </>
      ) : null}
      {completed.length ? (
        <ul className="next-activity-done">
          {completed.map((task, index) => (
            <li key={index}>
              <span className="next-activity-done-glyph" aria-label="completed">
                ✓
              </span>
              <span>{String(task['subject'] || '')}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="next-activity-empty">No completed tracked tasks in this payload.</p>
      )}
    </section>
  );
}

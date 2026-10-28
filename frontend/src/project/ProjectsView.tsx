import { Card } from '../ui/card';
import { Button } from '../ui/button';
import type { ReactNode } from 'react';
import { useMemo } from 'react';
import type { ObservedProject } from '../observed';
import { goalFocusFor } from '../sessions/heldState';
import { useShell } from '../shell/context';
import { selectObserved } from '../observed/select';
import { useDisplayed } from '../shell/context';
import { projectMembers } from './activity';
import { Dot, Value } from './parts';
import { routeToken, useRouteTarget } from './routing';
import type { ObservedSession } from '../observed';
import './project.css';

/* The Projects list: every project the board publishes a label for, split into the ones with something
   going on (a session working, or waiting on the reader) and the rest, which stay reachable by identity
   while their operational claims lapse. A project is the sessions that publish one label, exactly as
   published: two spellings of one directory are two rows and each says so. Ported from `next-projects.js`.
   Every count in a sentence is derived from the rows the row draws. */

/* A member line's key is its harness and sid, so the button keeps its node, and with it keyboard focus, when a
   refresh re-ranks the members. A board can publish one pair twice (the generated boards do), and only the
   repeats take an occurrence number: an index on every key remounted each line below a newcomer. */
function memberKeys(sessions: readonly ObservedSession[]): (readonly [string, ObservedSession])[] {
  const seen = new Map<string, number>();
  return sessions.map((session) => {
    const identity = `${session.harness}\u0000${session.sid}`;
    const repeat = seen.get(identity) ?? 0;
    seen.set(identity, repeat + 1);
    return [repeat ? `${identity}\u0000${String(repeat)}` : identity, session] as const;
  });
}

function MemberLine({
  session,
  project,
}: {
  readonly session: ObservedSession;
  readonly project: string;
}) {
  const route = {
    view: 'session',
    project,
    harness: session.harness,
    session: session.sid,
  } as const;
  const target = useRouteTarget(route);
  const { controls } = useShell();
  return (
    <Button
      variant="native"
      type="button"
      className="next-project-session"
      data-next-project-session=""
      data-next-harness={session.harness}
      data-next-session={session.sid}
      data-next-route={routeToken(route)}
      data-next-focus={routeToken(route)}
      onClick={(event) => {
        goalFocusFor(controls).request({ harness: session.harness, sid: session.sid });
        target.onClick(event);
      }}
    >
      <Dot session={session} />
      <span className="next-project-session-harness">{session.harness}</span>
      <Value
        text={session.titleText}
        known={session.titleKnown}
        className="next-project-session-title"
      />
      <Value text={session.nowText} known={session.nowKnown} className="next-project-session-now" />
      <Value
        text={session.nextText}
        known={session.nextKnown}
        className="next-project-session-next"
      />
    </Button>
  );
}

function ProjectRow({
  project,
  history,
}: {
  readonly project: ObservedProject;
  readonly history: boolean;
}) {
  const route = { view: 'project', project: project.key, session: null } as const;
  const target = useRouteTarget(route);
  const members = history ? null : projectMembers(project.sessions, project.risky);
  const identity = <strong className="next-project-name">{project.key}</strong>;
  const count = <div className="next-project-summary">{project.countLine}</div>;
  return (
    <Card
      as="article"
      variant="project-row"
      className={`next-project-row next-project-tone--${project.tone}${history ? ' next-project-row--history' : ''}`}
      data-next-project-row=""
      data-next-project={project.key}
      data-next-route={routeToken(route)}
      data-next-focus={routeToken(route)}
      role="link"
      tabIndex={0}
      {...(history ? { 'data-next-project-history': 'true' } : {})}
      onClick={target.onClick}
      onKeyDown={target.onKeyDown}
    >
      {members ? (
        <>
          <div className="next-project-project">
            {identity}
            <Value
              text={project.scopeText}
              known={project.scopeKnown}
              className="next-project-scope"
            />
            {count}
            {project.sharedLabelKnown ? (
              <div className="next-project-collision">{project.sharedLabelText}</div>
            ) : null}
          </div>
          <div className="next-project-sessions" aria-label="Observed sessions">
            {memberKeys(members.shown).map(([key, session]) => (
              <MemberLine key={key} session={session} project={project.key} />
            ))}
            {members.hidden ? (
              <Button
                variant="native"
                type="button"
                className="next-project-more"
                data-next-project-more=""
                data-next-route={routeToken(route)}
                data-next-focus={routeToken(route)}
                onClick={target.onClick}
              >
                {`${String(members.hidden)} other ${members.hidden === 1 ? 'session' : 'sessions'}`}
              </Button>
            ) : null}
          </div>
        </>
      ) : (
        <>
          {identity}
          {count}
        </>
      )}
      <span className="next-project-chevron" aria-hidden="true">
        ›
      </span>
    </Card>
  );
}

function Group({
  kind,
  title,
  description,
  projects,
  empty,
}: {
  readonly kind: 'active' | 'history';
  readonly title: string;
  readonly description: string;
  readonly projects: readonly ObservedProject[];
  readonly empty: string;
}) {
  return (
    <section
      className={`next-project-group next-project-group--${kind}`}
      data-next-project-group={kind}
    >
      <header>
        <h2>{title}</h2>
        <p>{description}</p>
      </header>
      <div className="next-projects-brief">
        {projects.length ? (
          projects.map((project, index) => (
            // Two projects cannot share a label, but a malformed board could repeat one, and React needs two keys.
            <ProjectRow
              key={`${project.key}#${String(index)}`}
              project={project}
              history={kind === 'history'}
            />
          ))
        ) : (
          <p className="next-projects-empty">{empty}</p>
        )}
      </div>
    </section>
  );
}

/** What the steering step draws above the list: the stage conditions waiting on the reader. */
export interface ProjectsViewProps {
  readonly conditions?: ReactNode;
}

export function ProjectsView({ conditions = null }: ProjectsViewProps) {
  const model = useDisplayed(selectObserved);
  const { active, rest } = useMemo(
    () => ({ active: model.activeProjects, rest: model.restProjects }),
    [model],
  );
  return (
    <section className="next-projects" data-next-view-body="projects">
      <h1>Projects</h1>
      {conditions}
      <p className="next-projects-note">sessions grouped by the label their harness publishes</p>
      <Group
        kind="active"
        title="Active"
        description="blocked on you ranks first · only source-backed sessions contribute claims"
        projects={active}
        empty="No project has active session evidence right now."
      />
      <Group
        kind="history"
        title="Recently observed"
        description="identity stays reachable; operational claims lapse"
        projects={rest}
        empty="No recently observed project history in this payload."
      />
    </section>
  );
}

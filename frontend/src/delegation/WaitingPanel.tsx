import { Card } from '../ui/card';
import { CopyControl, RaiseControl, resumeCommand } from '../controls';
import type { ObservedProject, ObservedSession } from '../observed';
import { RouteLink } from '../shell/RouteLink';
import { RailHeader } from '../steering/RailHeader';
import './delegation.css';

function Waiting({
  project,
  session,
}: {
  readonly project: string;
  readonly session: ObservedSession;
}) {
  const sid = String(session.sid);
  const harness = String(session.harness);
  const command = resumeCommand(harness, String(session.resume_id || ''));
  const copyId = sid.trim();
  return (
    <Card as="article" variant="rail-wait" className="next-rail-wait" data-next-wait-session={sid}>
      <div className="next-rail-wait-heading">
        <RouteLink
          route={{ view: 'session', project, harness, session: sid }}
          className={session.titleKnown ? '' : 'next-rail-reason'}
        >
          {session.titleText}
        </RouteLink>
        <span className={session.waitedKnown ? 'next-rail-wait-duration' : 'next-rail-reason'}>
          {session.waitedText}
        </span>
      </div>
      {/* Clamped as the Sessions row is: the question can run to 2,000 characters, and the session page has it whole. */}
      {session.askKnown ? (
        <p className="next-rail-question line-clamp-3">{session.askText}</p>
      ) : null}
      <div className="next-rail-wait-controls">
        {/* The raise names the exact pair this card was drawn for. A card whose row published a display id
            only has nothing to raise, and the control draws nothing for it. */}
        <RaiseControl
          harness={harness.trim()}
          sid={copyId}
          focusable={session.focusable === true}
        />
        {command ? (
          <CopyControl kind="command" harness={harness} sid={sid} value={command} />
        ) : copyId ? (
          <CopyControl kind="id" harness={harness} sid={copyId} value={copyId} />
        ) : null}
      </div>
    </Card>
  );
}

/* The sessions in this project that have asked for the reader, each with the way back into it. Only an exact
   question or a native gate puts a session here, and a session that is not here is not thereby healthy: the
   empty sentence says only what the board holds. */
export function WaitingPanel({ project }: { readonly project: ObservedProject }) {
  const note = project.needs.length
    ? `${String(project.needs.length)} of ${String(project.sessions.length)}`
    : 'none';
  return (
    <Card
      as="section"
      variant="rail-panel"
      className="next-rail-panel"
      data-next-rail-panel="waiting"
    >
      <RailHeader label="WAITING ON YOU" note={note} />
      {project.needs.length ? (
        project.needs.map((session, index) => (
          <Waiting
            // A payload can publish one pair twice; the index keeps two cards from sharing a key.
            key={`${session.harness}\u0000${session.sid}\u0000${String(index)}`}
            project={project.key}
            session={session}
          />
        ))
      ) : (
        <p className="next-rail-reason">Nothing in this project has asked for you.</p>
      )}
    </Card>
  );
}

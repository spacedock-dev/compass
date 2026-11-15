import { Card } from '../ui/card';
import { CopyControl, RaiseControl, resumeCommand } from '../controls';
import type { BoardRisk, Row } from '../observed';
import { nextNumber } from '../api/bootstrap';
import { AttentionLink } from './AttentionLink';
import type { AttentionModel, Subject } from './model';
import { riskRow } from './subjects';
import {
  checkpointRows,
  subjectNow,
  subjectOutcome,
  subjectSource,
  subjectRoute,
  subjectTitle,
} from './text';

/* The way back into a waiting session, drawn on the gate queue's rows only. Every section here names a
   session, so the controls would render on all four, and a small affordance on every row is furniture
   rather than an affordance. This one answers "it is waiting on me, get me there", which is the question
   only NEEDS YOU NOW asks. The copy is reversible and always works; the raise is neither, and a reader who
   has only the raise has lost the affordance that cannot fail, so it comes after the copy and never in
   place of it. Both name the exact harness and sid this row drew. */
function GateControls({ session }: { readonly session: Row | null }) {
  if (!session) return null;
  const harness = String(session['harness'] || '');
  const sid = String(session['sid'] || '');
  const command = resumeCommand(harness, String(session['resume_id'] || ''));
  return (
    <span className="next-attention-controls">
      {command ? <CopyControl kind="command" harness={harness} sid={sid} value={command} /> : null}
      <RaiseControl
        harness={harness.trim()}
        sid={sid.trim()}
        focusable={session['focusable'] === true}
      />
    </span>
  );
}

function NowValues({
  rows,
  className,
}: {
  readonly rows: readonly { readonly text: string; readonly note: string }[];
  readonly className: string;
}) {
  // The rows of one subject are an ordered list of readings, and two can be the same sentence, so the
  // position is their identity.
  return rows.map((row, index) => (
    <span key={index} className={className}>
      {row.text}
      {row.note ? <small>{row.note}</small> : null}
    </span>
  ));
}

/* A subject of the queues below At risk: why it is here, what outcome it serves, what is observed now,
   what is next and where the claim came from. Hidden rows stay in the document, as they do on the legacy
   page, so a reader's find and a screen reader's list both count what the heading counts. */
export function SubjectItem({
  subject,
  model,
  hidden,
}: {
  readonly subject: Subject;
  readonly model: AttentionModel;
  readonly hidden: boolean;
}) {
  const { title, secondary } = subjectTitle(subject);
  const outcome = subjectOutcome(subject, model);
  const now = subjectNow(subject, model);
  const checkpoints = checkpointRows(subject, model);
  return (
    <li {...(hidden ? { hidden: true } : {})}>
      <Card
        as="article"
        variant="attention-item"
        className="next-attention-item next-attention-item--legacy"
        data-next-attention-subject={subject.key}
        data-next-subject-key={subject.key}
        data-next-attention-kind={subject.primaryKind}
      >
        <h3 className="next-attention-why" data-next-attention-part="why">
          <AttentionLink
            route={subjectRoute(subject)}
            focusKey={`attention:subject:${subject.key}`}
            fallback={`attention:section:${subject.section}`}
          >
            {`${title}${secondary}`}
          </AttentionLink>
        </h3>
        <p className="next-attention-part" data-next-attention-part="outcome">
          <span className="next-attention-label">{outcome.label}</span>
          <span>{outcome.text}</span>
        </p>
        <div className="next-attention-part" data-next-attention-part="now">
          <span className="next-attention-label">NOW</span>
          <span>
            <NowValues rows={now} className="next-attention-now-value" />
          </span>
        </div>
        {checkpoints.length ? (
          <p className="next-attention-part" data-next-attention-part="next">
            <span className="next-attention-label">NEXT</span>
            <span>
              <NowValues
                rows={checkpoints.map((text) => ({ text, note: '' }))}
                className="next-attention-now-value"
              />
            </span>
          </p>
        ) : null}
        <p className="next-attention-part" data-next-attention-part="source">
          <span className="next-attention-label">SOURCE</span>
          <span>
            {subjectSource(subject, model)}
            {subject.section === 'needs' ? <GateControls session={subject.session} /> : null}
          </span>
        </p>
      </Card>
    </li>
  );
}

/* One risk, numbered, with the source that published it. A session's risk, a board-level one (a quota
   window, an identity collision, a request no session owns) and a retained per-model quota all draw
   here; the board ones carry `board` so a reader and a test can tell them from the session count. */
export function RiskItem({
  risk,
  index,
  model,
  board = false,
  retained,
}: {
  readonly risk: BoardRisk;
  readonly index: number;
  readonly model: AttentionModel;
  readonly board?: boolean;
  readonly retained?: Subject;
}) {
  const row = riskRow(risk, model, board, retained);
  const outcome = row.subject ? subjectOutcome(row.subject, model) : null;
  return (
    <li>
      <Card
        as="article"
        variant="attention-item"
        className={`next-attention-item${board ? ' next-attention-item--board' : ''}`}
        {...(board ? { 'data-next-board-risk': risk.kind } : {})}
        tone={
          risk.tone === 'want' || risk.tone === 'bad' || risk.tone === 'ok' ? risk.tone : 'unknown'
        }
        data-tone={risk.tone}
        data-next-attention-subject={row.key}
        data-next-subject-key={row.key}
        data-next-attention-kind={risk.kind}
      >
        <span className="next-attention-index">{index + 1}</span>
        <div className="next-attention-risk-identity">
          <h3>
            <AttentionLink
              route={row.route}
              focusKey={`attention:subject:${row.key}`}
              fallback="attention:section:risk"
            >
              {risk.title}
            </AttentionLink>
          </h3>
          <span>{risk.identity}</span>
          {outcome?.label === 'OUTCOME' ? (
            <p className="next-attention-risk-assignment">{outcome.text}</p>
          ) : null}
        </div>
        <div className="next-attention-risk-observation">
          <p>{risk.nowText}</p>
          {row.subject?.kind === 'collision' ? (
            <ul>
              {row.subject.sessions.map((session) => {
                const harness = String(session['harness'] || '');
                const sid = String(session['sid'] || '');
                const started = nextNumber(session['started_at']);
                const date = new Date((started ?? Number.NaN) * 1000);
                const stamp =
                  started !== null && started > 0 && Number.isFinite(date.getTime())
                    ? date.toISOString()
                    : 'not published';
                return (
                  <li key={JSON.stringify([harness, sid])}>
                    <AttentionLink
                      route={{
                        view: 'session',
                        project: String(session['project'] || ''),
                        harness,
                        session: sid,
                      }}
                      focusKey={`attention:subject:${row.key}:member:${harness}:${sid}`}
                      fallback="attention:section:risk"
                    >
                      {`${String(session['title'] || '').trim() || 'Title not published'} · ${String(session['worktree'] || 'No worktree published')} · ${harness}:${sid} · Start time ${stamp}`}
                    </AttentionLink>
                  </li>
                );
              })}
            </ul>
          ) : null}
          <div className="next-attention-risk-detail">
            {row.signals.map((signal, position) => (
              <span key={position}>
                {signal.text}
                {signal.note ? <small>{signal.note}</small> : null}
              </span>
            ))}
          </div>
        </div>
        <div className="next-attention-risk-source">
          {risk.nextKnown ? (
            <span className="next-attention-risk-next">{risk.nextText}</span>
          ) : (
            row.checkpoints.map((text, position) => (
              <span key={position} className="next-attention-risk-next">
                {text}
              </span>
            ))
          )}
          <span>{`source · ${risk.src}`}</span>
          {row.subject?.section === 'needs' ? <GateControls session={row.subject.session} /> : null}
        </div>
      </Card>
    </li>
  );
}

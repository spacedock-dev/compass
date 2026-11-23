import { Card } from '../ui/card';
import { CopyControl, RaiseControl, resumeCommand, useControls } from '../controls';
import { TechnicalDetails } from '../controls/TechnicalDetails';
import { useFocusKey } from '../controls/useFocusKey';
import { Button } from '../ui/button';
import { Icon } from '../ui/icons';
import { StatusTile } from '../ui/status-tile';
import { endedAt, sessionKey, type BoardRisk, type ObservedSession } from '../observed';
import { expandDurationUnits, formatDurationWords, formatTimestamp } from '../shell/format';
import { AttentionLink } from './AttentionLink';
import { subjectAge, type AttentionModel, type Subject } from './model';
import { riskRow } from './subjects';
import {
  delegatedAttentionText,
  dirtyEndText,
  riskSourceText,
  inputNow,
  subjectOutcome,
  subjectNow,
  harnessLabel,
} from './text';
import { WorthALookFlag } from './WorthALookFlag';

function WaitingEvidence({
  row,
  subject,
  model,
}: {
  readonly row: ObservedSession;
  readonly subject: Subject;
  readonly model: AttentionModel;
}) {
  const { focus } = useControls();
  const command = resumeCommand(row.harness, String(row.resume_id ?? ''));
  const canRaise = Boolean(focus && row.focusable === true);
  const signals = subjectNow(
    {
      ...subject,
      signals: subject.signals.filter(
        ({ kind }) => kind !== 'ask' && kind !== 'input' && kind !== 'task',
      ),
    },
    model,
  );
  if (!command && !canRaise && !signals.length) return null;
  return (
    <TechnicalDetails disclosureKey={`attention-wait:${sessionKey(row)}`}>
      {signals.map((signal, index) => (
        <p key={index}>
          {signal.text}
          {signal.note ? ` · ${signal.note}` : ''}
        </p>
      ))}
      <div className="next-attention-actions">
        {command ? (
          <CopyControl kind="command" harness={row.harness} sid={row.sid} value={command} />
        ) : null}
        {canRaise ? <RaiseControl harness={row.harness} sid={row.sid} focusable /> : null}
      </div>
    </TechnicalDetails>
  );
}

export function SessionItem({
  row,
  section,
  model,
  hidden,
  subject,
  risk,
  reason,
  onMark,
  markPending,
  markFallback,
}: {
  readonly row: ObservedSession;
  readonly section: 'needs' | 'risk' | 'close';
  readonly model: AttentionModel;
  readonly hidden: boolean;
  readonly subject?: Subject | undefined;
  readonly risk?: BoardRisk;
  readonly reason?: string;
  readonly onMark?: (() => void) | undefined;
  readonly markPending?: boolean;
  readonly markFallback?: string;
}) {
  const key = sessionKey(row);
  const { focusLane } = useControls();
  const markRef = useFocusKey<HTMLButtonElement>(focusLane, `attention:mark:${key}`, {
    fallback: markFallback ?? 'attention:title',
  });
  const route = {
    view: 'session',
    project: row.project,
    harness: row.harness,
    session: row.sid,
  } as const;
  const member =
    risk?.kind === 'collision'
      ? subject?.sessions.find((source) => sessionKey(source) === key)
      : undefined;
  const time = formatTimestamp(
    row.isEnded ? endedAt(subject?.session ?? member) : row.lastActivityAt,
    model.generated,
    { style: 'same-day-relative' },
  );
  const wait = row.isNeeds && subject ? inputNow(subject.session) : null;
  const age = subject && formatDurationWords(subjectAge(subject, model.generated));
  const evidence = risk ? riskRow(risk, model, false, subject) : null;
  const shortRisk = risk?.nowText === reason;
  const started =
    member && formatTimestamp(member['started_at'], model.generated, { style: 'clock' });
  const outcome = subject && subjectOutcome(subject, model);
  const dirtyEnd = section === 'needs' && subject?.signals.find(({ kind }) => kind === 'end-dirty');
  return (
    <li hidden={hidden}>
      <article
        className="next-attention-session"
        data-next-attention-subject={key}
        data-next-subject-key={key}
        data-next-attention-kind={risk?.kind ?? subject?.primaryKind ?? section}
      >
        {section === 'risk' ? (
          <span
            role="img"
            aria-label="Worth a look"
            className="grid size-10 shrink-0 place-items-center rounded-status-tile bg-[var(--status-waiting-bg)] text-[var(--worth-a-look)]"
          >
            <Icon name="worth-a-look" size={20} />
          </span>
        ) : (
          <StatusTile state={section === 'needs' ? 'Waiting on you' : 'Ended'} focusable={false} />
        )}
        <div className="next-attention-session-body">
          <h3 data-authored>{row.titleText}</h3>
          <p className="next-attention-session-meta" data-next-attention-part="source">
            <span data-authored>
              {harnessLabel(model, row.harness)}
              {row.project ? ` · ${row.project}` : ''}
            </span>
            {section === 'needs' && age
              ? ` · waiting ${age}`
              : time
                ? ` · ${row.isEnded ? 'Ended' : 'Last active'} ${time}`
                : section === 'close'
                  ? ' · Ended'
                  : ''}
          </p>
          {section === 'needs' ? (
            <div className="next-attention-reason">
              {row.askKnown ? <p data-authored>{row.askText}</p> : null}
              {wait && wait.text !== row.askText ? (
                <p data-authored={wait.text !== 'Needs-input state reported' || undefined}>
                  {wait.text === 'Needs-input state reported'
                    ? 'The agent is waiting for your input.'
                    : wait.text}
                </p>
              ) : null}
              {wait?.note ? <p>{wait.note}</p> : null}
              {dirtyEnd ? <p>{dirtyEndText(dirtyEnd.detail)}</p> : null}
            </div>
          ) : null}
          {section === 'risk' && reason ? (
            <div className="next-attention-reason next-attention-risk-observation">
              <WorthALookFlag reason={reason} />
              {risk && !shortRisk ? (
                <p data-authored>
                  {risk.delegatedSession
                    ? delegatedAttentionText(risk.delegatedSession, model.generated)
                    : risk.kind === 'long-turn'
                      ? expandDurationUnits(risk.nowText)
                      : risk.nowText}
                </p>
              ) : null}
            </div>
          ) : null}
        </div>
        <div className="next-attention-actions">
          <AttentionLink
            route={route}
            focusKey={`attention:subject:${key}`}
            fallback={`attention:section:${section}`}
          >
            Open session
          </AttentionLink>
          {onMark ? (
            <Button
              ref={markRef}
              type="button"
              variant="quiet"
              aria-busy={markPending || undefined}
              onClick={onMark}
            >
              {section === 'close' ? 'Mark as read' : 'Dismiss'}
            </Button>
          ) : null}
        </div>
        {section === 'needs' && subject ? (
          <div className="next-attention-evidence">
            <WaitingEvidence row={row} subject={subject} model={model} />
          </div>
        ) : null}
        {evidence && risk ? (
          <div className="next-attention-evidence">
            <TechnicalDetails disclosureKey={`attention-risk:${key}`}>
              <p>{risk.identity}</p>
              {member ? (
                <p>{`${row.titleText} · ${String(member['worktree'] || 'No worktree published')} · ${row.harness}:${row.sid} · Start time ${started ?? 'not published'}`}</p>
              ) : null}
              {outcome?.label === 'OUTCOME' ? <p>{outcome.text}</p> : null}
              <p>{riskSourceText(risk)}</p>
              <p>{risk.nowText}</p>
              {evidence.signals.map((signal, index) => (
                <p key={index}>
                  {signal.text}
                  {signal.note ? ` · ${signal.note}` : ''}
                </p>
              ))}
              {(risk.nextKnown ? [risk.nextText] : evidence.checkpoints).map((text, index) => (
                <p key={index}>{text}</p>
              ))}
            </TechnicalDetails>
          </div>
        ) : null}
      </article>
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
  readonly retained?: Subject | undefined;
}) {
  const row = riskRow(risk, model, board, retained);
  const outcome = row.subject ? subjectOutcome(row.subject, model) : null;
  const members = row.subject?.kind === 'collision' ? row.subject.sessions : [];
  const identifiers =
    risk.kind === 'ask'
      ? [risk.identity].filter(Boolean)
      : members.map(
          (session) => `${String(session['harness'] || '')}:${String(session['sid'] || '')}`,
        );
  let observation = risk.nowText;
  if (risk.kind === 'long-turn') observation = expandDurationUnits(observation);
  if (risk.delegatedSession) {
    observation = delegatedAttentionText(risk.delegatedSession, model.generated);
  }
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
          <h3 data-authored>
            <AttentionLink
              route={row.route}
              focusKey={`attention:subject:${row.key}`}
              fallback="attention:title"
            >
              {risk.title}
            </AttentionLink>
          </h3>
          {risk.kind === 'ask' ? null : <span data-authored>{risk.identity}</span>}
          {outcome?.label === 'OUTCOME' ? (
            <p className="next-attention-risk-assignment">{outcome.text}</p>
          ) : null}
        </div>
        <div className="next-attention-risk-observation">
          <p data-authored>{observation}</p>
          {members.length ? (
            <ul>
              {members.map((session) => {
                const harness = String(session['harness'] || '');
                const sid = String(session['sid'] || '');
                const stamp =
                  formatTimestamp(session['started_at'], model.generated, { style: 'clock' }) ??
                  'not published';
                return (
                  <li key={JSON.stringify([harness, sid])} data-authored>
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
                      {`${String(session['title'] || '').trim() || 'Title not published'} · ${String(session['worktree'] || 'No worktree published')} · Start time ${stamp}`}
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
            <span className="next-attention-risk-next">
              {risk.kind === 'quota' ? expandDurationUnits(risk.nextText) : risk.nextText}
            </span>
          ) : (
            row.checkpoints.map((text, position) => (
              <span key={position} className="next-attention-risk-next">
                {text}
              </span>
            ))
          )}
          <span>{riskSourceText(risk)}</span>
        </div>
        {identifiers.length ? (
          <div className="col-span-full">
            <TechnicalDetails disclosureKey={`attention-other:${row.key}`}>
              {identifiers.map((identity, index) => (
                <p key={index}>{identity}</p>
              ))}
            </TechnicalDetails>
          </div>
        ) : null}
      </Card>
    </li>
  );
}

import { Alert } from '../ui/alert';
import { Card } from '../ui/card';
import { Separator } from '../ui/separator';
import { Disclosure } from '../controls';
import type { Landing } from '../observed';
import { RouteAnchor } from './RouteAnchor';
import { durationSince, isRecord, promptCopied, type Row } from '../observed';
import { StatusDot } from './SessionsView';
import type { CommandReports, Delivery, Facts, Health, Subagents, Tasks } from './detail';

/* The parts of the session page that are a sentence or a list and nothing more. Each takes what the pure
   half derived and draws it; none reads the payload itself, so a figure on screen is always the one the
   derivation printed. */

const INSTRUCTION_LABELS = ['asked', 'agent', 'earlier'] as const;

/* The line beneath a session's title: what it is working on now, never without its label and the age of
   the record it came from. "agent, 4m:" is an agent quoting itself and "earlier, 2h:" is not the newest
   thing asked, and a reader who cannot see which has been handed a claim the runtime cannot support. A
   copied correction is never shown as the reader's words. */
export function InstructionLine({
  session,
  generated,
  className,
}: {
  readonly session: Row;
  readonly generated: number | null;
  readonly className: string;
}) {
  const instruction = session['instruction'];
  if (!isRecord(instruction) || promptCopied(session, 'instruction')) return null;
  const label = INSTRUCTION_LABELS.find(
    (candidate) => candidate === String(instruction['label'] || ''),
  );
  const text = String(instruction['text'] == null ? '' : instruction['text']).trim();
  if (!label || !text) return null;
  const age = durationSince(generated, instruction['at']);
  // The age sits OUTSIDE the label span: the label is upper-cased by the sheet, and a duration whose unit is
  // a capital letter reads as an initialism.
  return (
    <p className={className} data-next-instruction={String(instruction['label'])}>
      <span className="next-instruction-label">{label}</span>
      {`${age === null ? ':' : `, ${age}:`} `}
      <span className="next-instruction-text">{text}</span>
    </p>
  );
}

export function FactsView({
  facts,
  disclosureKey,
}: {
  readonly facts: Facts;
  readonly disclosureKey: string;
}) {
  const row = (fact: Facts['shown'][number]) => {
    const value = (
      <span {...(fact.known ? {} : { className: 'next-session-absent' })}>{fact.text}</span>
    );
    return (
      <div key={fact.key} data-next-session-fact={fact.key}>
        <dt>{fact.label}</dt>
        <dd>
          {fact.commandFact ? (
            <section data-next-session-command-fact="next">{value}</section>
          ) : (
            value
          )}
          {fact.key === 'block' && fact.note ? (
            <span className="next-session-fact-note">{fact.note}</span>
          ) : null}
        </dd>
      </div>
    );
  };
  return (
    <>
      <dl className="next-session-facts">{facts.shown.map(row)}</dl>
      <Disclosure
        disclosureKey={disclosureKey}
        summary={facts.summary}
        className="next-session-facts-more"
      >
        <dl className="next-session-facts">{facts.behind.map(row)}</dl>
      </Disclosure>
    </>
  );
}

export function HealthView({ health }: { readonly health: Health }) {
  return (
    <Alert
      as="aside"
      variant="session-health"
      className="next-session-health"
      role="note"
      aria-label={health.label}
      data-next-session-health={health.kind}
    >
      <strong>{health.label}</strong>
      <span className="next-session-health-separator" aria-hidden="true">
        {' — '}
      </span>
      <span>{health.why}</span>
    </Alert>
  );
}

export function TasksView({ tasks }: { readonly tasks: Tasks }) {
  return (
    <section className="next-session-section" data-next-session-section="tasks">
      <h2>{tasks.heading}</h2>
      {tasks.rows.map((task, index) => (
        <div
          key={index}
          className={
            task.pending ? 'next-session-task next-session-task--pending' : 'next-session-task'
          }
          data-next-session-task={task.id}
        >
          {task.glyph === 'completed' ? (
            <span className="next-status-dot next-session-task-glyph" aria-label="completed">
              ✓
            </span>
          ) : (
            <StatusDot
              label={task.glyph}
              className="next-session-task-glyph"
              filled={task.glyph === 'in progress'}
            />
          )}
          <strong className="next-session-task-subject">{task.subject}</strong>
        </div>
      ))}
    </section>
  );
}

export function SubagentsView({ subagents }: { readonly subagents: Subagents }) {
  return (
    <div className="next-session-current-subagents" data-next-session-subagents>
      <span>{subagents.label}</span>
      {subagents.rows.map((row) => (
        <div
          key={row.index}
          className={row.live ? 'next-session-subagent next-live' : 'next-session-subagent'}
          data-next-session-subagent={row.index}
        >
          <StatusDot
            label={row.live ? 'running' : 'idle'}
            className="next-session-subagent-glyph"
            filled={row.live}
          />
          <strong className="next-session-subagent-name">
            {row.name}
            {row.parent ? (
              <span className="next-session-subagent-parent">{` · ${row.parent}`}</span>
            ) : null}
          </strong>
          {row.elapsed !== null ? (
            <span className="next-session-subagent-elapsed">{row.elapsed}</span>
          ) : null}
        </div>
      ))}
      {subagents.omitted > 0 ? (
        <div className="next-session-subagents-omitted">{`+${String(subagents.omitted)} older finished worker${subagents.omitted === 1 ? '' : 's'} omitted`}</div>
      ) : null}
    </div>
  );
}

const REPORT_CAVEATS = (
  <>
    <p>A shape match does not prove the action succeeded.</p>
    <p>
      Claude Code and Codex after-tool hooks only. Reports may repeat or arrive out of order. This
      run keeps up to 1,000 reports, 20 per session, for at most 24 hours; restarting clears them.
    </p>
  </>
);

/* Command-shape reports for this session. Off or unsupported it is one summary naming that state, with its
   sentence and the caveats behind it; on, the list or "No command-shape reports" stays in view and the
   caveats sit behind "About these reports". */
export function CommandReportsView({
  reports,
  disclosureKey,
}: {
  readonly reports: CommandReports;
  readonly disclosureKey: string;
}) {
  if (reports.state !== 'on') {
    return (
      <section className="next-attention-section" data-next-command-reports>
        <Disclosure
          disclosureKey={disclosureKey}
          summary={
            reports.state === 'off'
              ? 'Command-shape reports: off'
              : 'Command-shape reports: unsupported here'
          }
        >
          <p>{reports.absent}</p>
          {REPORT_CAVEATS}
        </Disclosure>
      </section>
    );
  }
  const count = reports.rows.length;
  return (
    <section className="next-attention-section" data-next-command-reports>
      <div className="next-attention-section-heading">
        <h2>Command-shape reports</h2>
        {count ? (
          <p>{`${String(count)} report${count === 1 ? '' : 's'} shown · newest first`}</p>
        ) : null}
      </div>
      {count ? (
        <ol>
          {reports.rows.map((report, index) => (
            <li key={index} className="next-attention-risk-identity">
              <h3>{report.text}</h3>
              <p className="next-attention-risk-source">{report.source}</p>
            </li>
          ))}
        </ol>
      ) : (
        <p>No command-shape reports.</p>
      )}
      <Disclosure disclosureKey={`${disclosureKey}\nabout`} summary="About these reports">
        {count ? null : <p>{reports.absent}</p>}
        {REPORT_CAVEATS}
      </Disclosure>
    </section>
  );
}

/* What became of the notifications Compass raised about this session. Every sentence is composed by the
   server and printed verbatim: the wording is the product. */
export function DeliveryView({ delivery }: { readonly delivery: Delivery }) {
  return (
    <section
      className="next-session-delivery"
      data-next-delivery={delivery.outcome}
      {...(delivery.mixed ? { 'data-next-delivery-mixed': 'true' } : {})}
    >
      <Separator aria-hidden="true" className="mb-[10px]" />
      <h2>NOTIFICATIONS</h2>
      <p className="next-session-delivery-count">{delivery.count}</p>
      {delivery.why ? <p className="next-session-delivery-why">{delivery.why}</p> : null}
      {delivery.mixed && delivery.mixedWhy ? (
        <p className="next-session-delivery-note">{delivery.mixedWhy}</p>
      ) : null}
      {delivery.bindingWhy ? (
        <p className="next-session-delivery-note">{delivery.bindingWhy}</p>
      ) : null}
      {delivery.laneWhy ? <p className="next-session-delivery-lane">{delivery.laneWhy}</p> : null}
    </section>
  );
}

/* How it landed, as two cards that never merge: what ended (the evidence of an end) and who says it
   finished. Evidence of an end and a claim of completion are separate questions, and today the honest answer
   to the second is always the session itself, so the card says why nothing corroborates it rather than
   leaving a blank. A fact that was not measured wears the absence register. */
export function LandedView({
  landing,
  disclosureKey,
}: {
  readonly landing: Landing;
  readonly disclosureKey: string;
}) {
  const card = (title: string, text: string, known: boolean, note: string) => (
    <Card variant="session-landed" className="next-cockpit-landed-card">
      <span className="next-cockpit-landed-label">{title}</span>
      <span
        className={
          known
            ? 'next-cockpit-landed-value'
            : 'next-cockpit-landed-value next-cockpit-landed-value--absent'
        }
      >
        {text}
      </span>
      {note ? <span className="next-cockpit-landed-note">{note}</span> : null}
    </Card>
  );
  return (
    <section className="next-cockpit-landed">
      <header>
        <h2>HOW IT LANDED</h2>
      </header>
      <div className="next-cockpit-landed-cards">
        {card('END EVIDENCE', landing.endText, landing.endKnown, '')}
        {card(
          'WHO CLAIMS IT FINISHED',
          landing.claimText,
          landing.claimKnown,
          landing.independentText,
        )}
      </div>
      <p className="next-why-body">Neither card implies the other.</p>
      <Disclosure disclosureKey={disclosureKey} summary="Why two cards">
        <p className="next-why-body">
          Evidence of an end and a claim of completion are separate questions.
        </p>
      </Disclosure>
    </section>
  );
}

/* Where a raise is kept, in the page's last slot: a pointer off this page, like HOW IT LANDED is a block of
   it. The link in view and what it keeps one click away. */
export function DeparturesKept({ disclosureKey }: { readonly disclosureKey: string }) {
  return (
    <div className="next-cockpit-departures-kept">
      <RouteAnchor route={{ view: 'intent', project: null, session: null }}>Intent log</RouteAnchor>
      <Disclosure disclosureKey={disclosureKey} summary="What it keeps">
        <p className="next-why-body">
          The Intent log keeps what you saved and what was raised against it after the session
          leaves the board.
        </p>
      </Disclosure>
    </div>
  );
}

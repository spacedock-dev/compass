import { Alert } from '../ui/alert';
import { Card } from '../ui/card';
import { Separator } from '../ui/separator';
import { Disclosure } from '../controls';
import { GLOSSARY, SESSION_LIST_WORDS, SHOWN } from '../language/glossary';
import { SESSION_TEXT_ORIGIN, type Landing, type ObservedSession } from '../observed';
import { RouteAnchor } from './RouteAnchor';
import { durationSince, gapNames, isRecord, promptCopied, type Row } from '../observed';
import { Icon } from '../ui/icons';
import { StatusTile } from '../ui/status-tile';
import { companionsLine, type ProjectCompanions } from '../project/projectList';
import {
  helperTile,
  helperWords,
  sessionFigures,
  turnEndedSentence,
  type CommandReports,
  type Delivery,
  type Facts,
  type Health,
  type Subagents,
  type Tasks,
} from './detail';

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
      <span className="next-instruction-text" data-authored>
        {text}
      </span>
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
          <span role="img" aria-label={task.glyph} className="next-session-task-glyph">
            <Icon
              name={
                task.glyph === 'completed'
                  ? 'check'
                  : task.glyph === 'in progress'
                    ? 'working'
                    : 'unrecorded'
              }
            />
          </span>
          <strong className="next-session-task-subject">{task.subject}</strong>
        </div>
      ))}
    </section>
  );
}

export function SubagentsView({ subagents }: { readonly subagents: Subagents }) {
  const heading = `${GLOSSARY.helpers.plain} (${subagents.rows.length})`;
  return (
    <div className="grid gap-1.5" data-next-session-subagents>
      <h3 className="m-0 text-label font-semibold">{heading}</h3>
      <ul aria-label={heading} className="m-0 grid list-none gap-2.5 p-0">
        {subagents.rows.map((row) => {
          const words = helperWords(row);
          return (
            <li
              key={row.index}
              className="flex items-center gap-2.5"
              data-next-session-subagent={row.index}
            >
              <StatusTile
                state={helperTile(row.live)}
                size="small"
                focusable={false}
                rowState={null}
              />
              <span className="flex min-w-0 flex-1 flex-wrap justify-between gap-x-2 [overflow-wrap:anywhere]">
                {row.name ? (
                  <span data-authored>{row.parent ? `${row.name} · ${row.parent}` : row.name}</span>
                ) : (
                  <span>
                    Unnamed helper
                    {row.parent ? (
                      <>
                        {' '}
                        · <span data-authored>{row.parent}</span>
                      </>
                    ) : null}
                  </span>
                )}
                {words ? <span className="text-label text-muted-foreground">{words}</span> : null}
              </span>
            </li>
          );
        })}
      </ul>
      {subagents.omitted > 0 ? (
        <p className="m-0 text-label text-muted-foreground">
          {`${subagents.omitted} older ${subagents.omitted === 1 ? 'helper' : 'helpers'} omitted`}
        </p>
      ) : null}
    </div>
  );
}

export function RightNow({
  session,
  observed,
  generated,
  subagents,
}: {
  readonly session: Row;
  readonly observed: ObservedSession;
  readonly generated: number | null;
  readonly subagents: Subagents | null;
}) {
  const origin = observed[SESSION_TEXT_ORIGIN];
  const gaps = gapNames(session);
  const turnEnd = session['waiting_on_child']
    ? null
    : turnEndedSentence(session, generated, observed.askKnown);
  return (
    <Card
      as="section"
      variant="drift-panel"
      className="next-session-right-now grid gap-3 p-4"
      aria-labelledby="session-right-now"
    >
      <h2 id="session-right-now" className="m-0 text-value font-semibold">
        {SESSION_LIST_WORDS.rightNow}
      </h2>
      <p
        className="m-0 [overflow-wrap:anywhere]"
        data-authored={(!turnEnd && origin.now) || undefined}
      >
        {turnEnd ?? observed.nowWords}
      </p>
      {gaps.length ? (
        <p className="m-0 text-label text-muted-foreground">
          Some activity could not be read: {gaps.join(', ')}.
        </p>
      ) : null}
      {subagents ? <SubagentsView subagents={subagents} /> : null}
      {!observed.isEnded ? (
        <dl className="m-0 grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-2 text-body">
          <dt className="text-muted-foreground">Next step</dt>
          <dd
            className="m-0 [overflow-wrap:anywhere]"
            data-authored={observed.nextKnown || undefined}
          >
            {observed.nextText}
          </dd>
          <dt className="text-muted-foreground">Blocked?</dt>
          <dd className="m-0 [overflow-wrap:anywhere]">
            {observed.blockKnown || gaps.includes('block state')
              ? observed.blockText
              : 'This agent does not report blocks'}
            {observed.blockNote ? (
              <span className="block" data-authored={origin.blockNote || undefined}>
                {observed.blockNote}
              </span>
            ) : null}
          </dd>
        </dl>
      ) : null}
    </Card>
  );
}

export function AtAGlance({ figures }: { readonly figures: ReturnType<typeof sessionFigures> }) {
  return (
    <Card
      as="section"
      variant="drift-panel"
      className="next-session-at-a-glance grid gap-3 p-4"
      aria-labelledby="session-at-a-glance"
    >
      <h2 id="session-at-a-glance" className="m-0 text-value font-semibold">
        {SESSION_LIST_WORDS.atAGlance}
      </h2>
      {figures.length ? (
        <dl className="m-0 grid grid-cols-2 gap-3 [overflow-wrap:anywhere]">
          {figures.map(({ label, value }) => (
            <div key={label} className="flex flex-col-reverse">
              <dt className="text-label text-muted-foreground">{label}</dt>
              {/* The canvas's hero step: the 24 px head size at 800, so the numbers lead their quiet labels. */}
              <dd className="m-0 text-head font-extrabold leading-tight">{value}</dd>
            </div>
          ))}
        </dl>
      ) : (
        <p className="m-0 text-muted-foreground">No figures published for this session.</p>
      )}
    </Card>
  );
}

export function SessionProject({
  project,
  viewOnly,
  companions = null,
}: {
  readonly project: string;
  readonly viewOnly: boolean;
  /** This project's other sessions today, counted from the board's rows (`projectCompanions`). */
  readonly companions?: ProjectCompanions | null;
}) {
  const line = companionsLine(companions);
  return (
    <Card
      as="section"
      variant="drift-panel"
      className="next-session-project grid gap-2 p-4"
      aria-labelledby="session-project"
    >
      <h2 id="session-project" className="m-0 text-value font-semibold">
        Project
      </h2>
      {project ? (
        <div className="grid gap-0.5">
          <p className="m-0 [overflow-wrap:anywhere]">
            {viewOnly ? (
              <span data-authored>{project}</span>
            ) : (
              <RouteAnchor route={{ view: 'project', project }} className="text-primary">
                <span data-authored>{project}</span>
              </RouteAnchor>
            )}
          </p>
          {line ? (
            <p className="m-0 text-label text-muted-foreground" data-next-session-project-today>
              {line}
            </p>
          ) : null}
        </div>
      ) : (
        <p className="m-0 text-muted-foreground">Project not published.</p>
      )}
    </Card>
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
      <RouteAnchor route={{ view: 'intent', project: null, session: null }}>
        {SHOWN.intent}
      </RouteAnchor>
      <Disclosure disclosureKey={disclosureKey} summary="What it keeps">
        <p className="next-why-body">
          {SHOWN.intent} keeps what you saved and what was raised against it after the session
          leaves the board.
        </p>
      </Disclosure>
    </div>
  );
}

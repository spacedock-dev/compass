import { SESSION_ROW_WORDS, SHOWN } from '../language/glossary';
import { UnaskedAttentionCue } from '../drift/UnaskedPermission';
import { Card } from '../ui/card';
import { Button } from '../ui/button';
import { useMemo } from 'react';
import { useControls } from '../controls';
import { useFocusKey } from '../controls/useFocusKey';
import { selectObserved } from '../observed/select';
import { sessionKey, type Observed } from '../observed';
import { sessionRisk } from '../observed/project';
import { formatTimestamp } from '../shell/format';
import { useDisplayed } from '../shell/context';
import { selectDataStatus } from '../store/selectors';
import { RouteAnchor } from '../sessions';
import { CommandReportsSection, CoverageBlock } from './Coverage';
import { RiskItem, SubjectItem } from './Items';
import { type AttentionModel, type Section, type Subject } from './model';
import { boardReports } from './reports';
import { selectAttention, selectAttentionSelection, type AttentionSelection } from './select';
import { riskSubject, modelQuotaRisk } from './subjects';
import { useExpansion } from './expansion';
import './attention.css';

/* Subjects shown before "Show N more". The reader opens the rest, and the choice outlives every revision. */
export const INITIAL_SECTION_SIZE = 3;

function occurrences(keys: readonly string[]): string[] {
  const seen = new Map<string, number>();
  return keys.map((key) => {
    const count = seen.get(key) ?? 0;
    seen.set(key, count + 1);
    return `${key}\u0000${String(count)}`;
  });
}

function Heading({ section, children }: { readonly section: string; readonly children: string }) {
  const controls = useControls();
  const ref = useFocusKey<HTMLHeadingElement>(controls.focusLane, `attention:section:${section}`, {
    fallback: 'attention:title',
  });
  return (
    <h2 ref={ref} tabIndex={-1}>
      {children}
    </h2>
  );
}

/* One of the three queues under At risk. Empty draws nothing at all: a heading over no rows would claim a
   queue that was looked at and held nothing, which the coverage lines say once and in numbers. */
function QueueSection({
  section,
  title,
  subjects,
  model,
}: {
  readonly section: Section;
  readonly title: string;
  readonly subjects: readonly Subject[];
  readonly model: AttentionModel;
}) {
  const controls = useControls();
  const expansion = useExpansion(controls);
  const toggleRef = useFocusKey<HTMLButtonElement>(
    controls.focusLane,
    `attention:toggle:${section}`,
    {
      fallback: `attention:section:${section}`,
    },
  );
  if (!subjects.length) return null;
  const expanded = expansion.has(section);
  const remainder = Math.max(0, subjects.length - INITIAL_SECTION_SIZE);
  const listId = `next-attention-${section}-list`;
  return (
    <section className="next-attention-section" data-next-attention-section={section}>
      <Heading section={section}>{`${title} (${String(subjects.length)})`}</Heading>
      <ol id={listId}>
        {subjects.map((subject, index) => (
          <SubjectItem
            key={subject.key}
            subject={subject}
            model={model}
            hidden={!expanded && index >= INITIAL_SECTION_SIZE}
          />
        ))}
      </ol>
      {remainder ? (
        <Button
          variant="native"
          ref={toggleRef}
          type="button"
          className="next-attention-disclosure"
          data-next-attention-toggle={section}
          aria-expanded={expanded}
          aria-controls={listId}
          onClick={() => expansion.toggle(section)}
        >
          {expanded ? `Show fewer (hide ${String(remainder)})` : `Show ${String(remainder)} more`}
        </Button>
      ) : null}
    </section>
  );
}

function Absence({ unread }: { readonly unread: boolean }) {
  return (
    <p className="next-absence">
      {unread ? 'The first payload has not arrived yet.' : 'No data has been received in this tab.'}
    </p>
  );
}

function Title() {
  const controls = useControls();
  const ref = useFocusKey<HTMLHeadingElement>(controls.focusLane, 'attention:title');
  return (
    <header className="next-attention-heading">
      <h1 ref={ref} tabIndex={-1}>
        {SHOWN.attention}
      </h1>
      <p>what is observed, and what the board could not see</p>
    </header>
  );
}

function Board({
  model,
  observed,
  selection,
}: {
  readonly model: AttentionModel;
  readonly observed: Observed;
  readonly selection: AttentionSelection | null;
}) {
  const data = useDisplayed((snapshot) => snapshot.data);
  const reports = useMemo(() => boardReports(data), [data]);
  const offCountKeys = new Set(selection?.offCountRisks.map((subject) => subject.key));
  const sourceRisks = new Map(
    observed.risks.map((risk) => [sessionKey({ harness: risk.harness, sid: risk.sid }), risk]),
  );
  const collisions = new Map(
    model.risk
      .filter((subject) => subject.primaryKind === 'collision' && !offCountKeys.has(subject.key))
      .flatMap((subject) => subject.sessions.map((row) => [sessionKey(row), subject] as const)),
  );
  const risks = [...(selection?.worthALook ?? [])].map(([session, reason]) => {
    const key = sessionKey(session);
    const source = sourceRisks.get(key);
    const collision = collisions.get(key);
    if (!collision) return source ?? sessionRisk(session, 'risk', session.titleText, reason);
    const warning = collision.signals[0]?.detail.text;
    if (source && reason !== 'Shared project label') return source;
    const member = collision.sessions.find((row) => sessionKey(row) === key);
    const started = formatTimestamp(member?.['started_at'], model.generated, { style: 'clock' });
    const title = `${session.titleKnown ? session.titleText : 'Title not published'} · ${String(member?.['worktree'] || 'No worktree published')} · ${session.harness}:${session.sid} · Start time ${started ?? 'not published'}`;
    const risk = sessionRisk(
      session,
      'collision',
      title,
      [reason, warning].filter(Boolean).join(' · '),
    );
    return { ...risk, src: 'Published project location evidence' };
  });
  const boardRisks = observed.boardRisks.filter((risk) => {
    if (!selection || risk.kind !== 'collision') return true;
    const subject = riskSubject(risk, model);
    return !subject || offCountKeys.has(subject.key);
  });
  const modelQuotas = model.risk.filter(
    (subject) => subject.kind === 'quota' && subject.identity?.project.startsWith('model:'),
  );
  const boardKeys = occurrences(boardRisks.map((risk) => `${risk.kind}\u0000${risk.identity}`));
  const alreadyShown = new Set(
    [...observed.risks, ...observed.boardRisks].map((risk) => riskSubject(risk, model)?.key),
  );
  const next = model.next.filter((subject) => !alreadyShown.has(subject.key));
  const waitingKeys = new Set(selection?.waitingOnYou.map(sessionKey));
  const needs = model.needs.filter((subject) => waitingKeys.has(subject.key));
  const subjects = new Map(
    [...model.needs, ...model.risk, ...model.close].map((subject) => [subject.key, subject]),
  );
  const close = (selection?.readyToWrapUp ?? []).flatMap((row): Subject[] => {
    const subject = subjects.get(sessionKey(row));
    const signal = subject?.signals.find(({ kind }) => kind === 'end-clean');
    return subject && signal
      ? [{ ...subject, section: 'close', primaryKind: signal.kind, signals: [signal] }]
      : [];
  });
  return (
    <section className="next-attention" data-next-view-body="attention">
      <Title />
      {data ? <UnaskedAttentionCue payload={data as unknown as Record<string, unknown>} /> : null}
      {selection ? (
        <section
          className="mt-6 grid grid-cols-2 divide-x divide-[var(--rule)] border-y border-[var(--rule)]"
          aria-label="Request and block facts"
        >
          {observed.counters.map((counter, index) => (
            <section
              className="grid min-w-0 gap-1.5 px-2 py-1.5 min-[621px]:px-[18px] min-[621px]:py-[15px]"
              key={counter.label}
              data-next-fleet-fact={index === 0 ? 'requests' : 'reported-blocks'}
            >
              <span className="text-label font-semibold">{counter.label}</span>
              <strong className="text-value font-semibold min-[621px]:text-hero">
                {counter.value}
              </strong>
              <small className="text-body leading-[1.55] text-muted-foreground">
                {counter.noteText}
              </small>
            </section>
          ))}
        </section>
      ) : null}
      <Card variant="attention-brief" className="next-attention-brief">
        <p>
          <span className="next-attention-brief-label">OBSERVED</span>
          {selection?.counts ? (
            <span>
              {`${selection.counts.waitingOnYou} waiting on you · ${selection.counts.worthALook} worth a look · ${selection.counts.readyToWrapUp} ready to wrap up.`}
              {selection.limitedStateCount
                ? ` ${selection.limitedStateCount} with limited state evidence.`
                : ''}
            </span>
          ) : (
            <span className="next-absence">
              {selection
                ? 'Session counts are unavailable because the sources could not be read.'
                : 'The board published no session collection.'}
            </span>
          )}
        </p>
        <CoverageBlock model={model} observed={observed} />
        <RouteAnchor
          route={{ view: 'projects', project: null, session: null }}
          className="next-attention-projects-link"
        >
          View all projects
        </RouteAnchor>
      </Card>
      {observed.sessions.length || !selection ? null : (
        <p className="next-attention-empty">
          {`No sessions in this ${model.windowHours == null ? 'payload' : `${String(model.windowHours)}-hour payload`}`}
        </p>
      )}
      <section className="next-attention-section" data-next-attention-section="risk">
        <div className="next-attention-section-heading">
          <Heading section="risk">{`${SESSION_ROW_WORDS.worthALook} (${risks.length})`}</Heading>
          <p>{`${String(risks.length)} of ${String(selection?.sessionCount ?? 0)} sessions`}</p>
        </div>
        <ol>
          {risks.map((risk, index) => (
            <RiskItem
              key={sessionKey({ harness: risk.harness, sid: risk.sid })}
              risk={risk}
              index={index}
              model={model}
            />
          ))}
        </ol>
        <QueueSection
          section="needs"
          title={SESSION_ROW_WORDS.waitingOnYou}
          subjects={needs}
          model={model}
        />
        <QueueSection section="close" title="Ready to wrap up" subjects={close} model={model} />
        <QueueSection section="next" title="Coming next" subjects={next} model={model} />
      </section>
      <section className="next-attention-section" data-next-attention-section="board-risk">
        <div className="next-attention-section-heading">
          <Heading section="board-risk">Also at risk, off the session count</Heading>
        </div>
        <ol>
          {boardRisks.map((risk, index) => (
            <RiskItem key={boardKeys[index]} risk={risk} index={index} model={model} board />
          ))}
          {modelQuotas.map((subject, index) => (
            <RiskItem
              key={subject.key}
              risk={modelQuotaRisk(subject, model)}
              index={boardRisks.length + index}
              model={model}
              board
              retained={subject}
            />
          ))}
        </ol>
      </section>
      <CommandReportsSection reports={reports} />
      <section className="next-attention-section" data-next-attention-section="open">
        <div className="next-attention-section-heading">
          <Heading section="open">Not on this board yet</Heading>
        </div>
        <ul className="next-attention-open">
          {observed.open.map(([key, name, note]) => (
            <li key={key} data-next-open={key}>
              <strong>{name}</strong>
              <p>{note}</p>
            </li>
          ))}
        </ul>
      </section>
    </section>
  );
}

/* The Attention screen: what the board asks of the reader, ordered, and what it could not see. A pure
   reading of one displayed payload through the observed model and the Attention model; every count in a
   sentence is derived from the rows drawn beside it. Before the first board it says nothing has arrived,
   and a board that published no session collection says that, because a queue of zeros would be a claim
   about a collection nobody published. Nothing here fetches, polls or acts; a row's controls act only
   when pressed. */
export function AttentionView() {
  const snapshot = useDisplayed((current) => current);
  const model = useDisplayed(selectAttention);
  const observed = useDisplayed(selectObserved);
  const selection = useDisplayed(selectAttentionSelection);
  if (!snapshot.data || !model) {
    return (
      <section className="next-attention" data-next-view-body="attention">
        <Title />
        <Absence unread={selectDataStatus(snapshot) === 'unread'} />
      </section>
    );
  }
  return <Board model={model} observed={observed} selection={selection} />;
}

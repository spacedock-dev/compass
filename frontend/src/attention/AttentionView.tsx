import { UnaskedAttentionCue } from '../drift/UnaskedPermission';
import { Card } from '../ui/card';
import { Button } from '../ui/button';
import { useMemo } from 'react';
import { payloadSessions } from '../api/bootstrap';
import { useControls } from '../controls';
import { useFocusKey } from '../controls/useFocusKey';
import { selectObserved } from '../observed/select';
import type { Observed } from '../observed';
import { useDisplayed } from '../shell/context';
import { selectDataStatus } from '../store/selectors';
import { RouteAnchor } from '../sessions';
import { CommandReportsSection, CoverageBlock } from './Coverage';
import { RiskItem, SubjectItem } from './Items';
import { type AttentionModel, type Section, type Subject } from './model';
import { boardReports } from './reports';
import { selectAttention } from './select';
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
        Attention
      </h1>
      <p>what is observed, and what the board could not see</p>
    </header>
  );
}

function Board({
  model,
  observed,
  collection,
}: {
  readonly model: AttentionModel;
  readonly observed: Observed;
  readonly collection: boolean;
}) {
  const data = useDisplayed((snapshot) => snapshot.data);
  const reports = useMemo(() => boardReports(data), [data]);
  const risks = observed.risks;
  const boardRisks = observed.boardRisks;
  const modelQuotas = model.risk.filter(
    (subject) => subject.kind === 'quota' && subject.identity?.project.startsWith('model:'),
  );
  const rendered = new Set([...risks, ...boardRisks].map((risk) => riskSubject(risk, model)?.key));
  // A payload can publish one session twice, and each copy keeps its own row: the key is the exact identity
  // and which copy it is, never the position, so a reorder moves nodes instead of replacing them.
  const riskKeys = occurrences(risks.map((risk) => `${risk.harness ?? ''}\u0000${risk.sid ?? ''}`));
  const boardKeys = occurrences(boardRisks.map((risk) => `${risk.kind}\u0000${risk.identity}`));
  const remaining = (subjects: readonly Subject[]) =>
    subjects.filter((subject) => !rendered.has(subject.key));
  return (
    <section className="next-attention" data-next-view-body="attention">
      <Title />
      {data ? <UnaskedAttentionCue payload={data as unknown as Record<string, unknown>} /> : null}
      {collection ? (
        <section className="next-operations-fleet" aria-label="Request and block facts">
          {observed.counters.slice(2).map((counter, index) => (
            <section
              key={counter.label}
              data-next-fleet-fact={index === 0 ? 'requests' : 'reported-blocks'}
            >
              <span>{counter.label}</span>
              <strong>{counter.value}</strong>
              <small>{counter.noteText}</small>
            </section>
          ))}
        </section>
      ) : null}
      <Card variant="attention-brief" className="next-attention-brief">
        <p>
          <span className="next-attention-brief-label">OBSERVED</span>
          {collection ? (
            <span>
              {observed.coverage.observed}{' '}
              <span className="next-attention-quiet">{observed.coverage.quiet}</span>
            </span>
          ) : (
            <span className="next-absence">The board published no session collection.</span>
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
      {observed.sessions.length || !collection ? null : (
        <p className="next-attention-empty">
          {`No sessions in this ${model.windowHours == null ? 'payload' : `${String(model.windowHours)}h payload`}`}
        </p>
      )}
      <section className="next-attention-section" data-next-attention-section="risk">
        <div className="next-attention-section-heading">
          <Heading section="risk">At risk</Heading>
          <p>{`${String(risks.length)} of ${String(observed.sessions.length)} sessions · every one names the source that published it`}</p>
        </div>
        <ol>
          {risks.map((risk, index) => (
            <RiskItem key={riskKeys[index]} risk={risk} index={index} model={model} />
          ))}
        </ol>
        <QueueSection
          section="needs"
          title="Needs you now"
          subjects={remaining(model.needs)}
          model={model}
        />
        <QueueSection
          section="close"
          title="Close the loop"
          subjects={remaining(model.close)}
          model={model}
        />
        <QueueSection
          section="next"
          title="Coming next"
          subjects={remaining(model.next)}
          model={model}
        />
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
  if (!snapshot.data || !model) {
    return (
      <section className="next-attention" data-next-view-body="attention">
        <Title />
        <Absence unread={selectDataStatus(snapshot) === 'unread'} />
      </section>
    );
  }
  return (
    <Board model={model} observed={observed} collection={payloadSessions(snapshot.data).present} />
  );
}

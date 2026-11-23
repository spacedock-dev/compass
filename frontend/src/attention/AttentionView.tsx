import { SESSION_ROW_WORDS, SHOWN } from '../language/glossary';
import { UnaskedAttentionCue } from '../drift/UnaskedPermission';
import { Button } from '../ui/button';
import { useMemo, useState, type ReactNode } from 'react';
import { Disclosure, useControls } from '../controls';
import { useFocusKey } from '../controls/useFocusKey';
import { selectObserved } from '../observed/select';
import { sessionKey, type Observed, type ObservedSession } from '../observed';
import { sessionRisk } from '../observed/project';
import { useDisplayed, useShell } from '../shell/context';
import { selectDataStatus } from '../store/selectors';
import { RouteAnchor } from '../sessions';
import { CommandReportsSection, CoverageBlock } from './Coverage';
import { RiskItem, SessionItem } from './Items';
import type { AttentionModel } from './model';
import { boardReports } from './reports';
import { selectAttention, selectAttentionSelection, type AttentionSelection } from './select';
import { riskSubject, modelQuotaRisk } from './subjects';
import { useExpansion } from './expansion';
import './attention.css';

/* Subjects shown before "Show N more". The reader opens the rest, and the choice outlives every revision. */
export const INITIAL_SECTION_SIZE = 3;

const DISMISSAL_WRITE = 'attention:dismiss:';

function isDismissalWrite(key: string) {
  return key.startsWith(DISMISSAL_WRITE);
}

function markKey(row: Pick<ObservedSession, 'harness' | 'sid'>, undo = false) {
  return `${DISMISSAL_WRITE}${undo ? 'undo' : 'mark'}:${sessionKey(row)}`;
}

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

/* Empty queues are omitted. Coverage explains which sessions and signals the board could read. */
function QueueSection({
  section,
  title,
  size,
  children,
}: {
  readonly section: 'needs' | 'risk' | 'close';
  readonly title: string;
  readonly size: number;
  readonly children: (expanded: boolean) => ReactNode;
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
  if (!size) return null;
  const expanded = expansion.has(section);
  const remainder = section === 'risk' ? 0 : Math.max(0, size - INITIAL_SECTION_SIZE);
  const listId = `next-attention-${section}-list`;
  return (
    <section className="next-attention-section" data-next-attention-section={section}>
      <Heading section={section}>{`${title} (${String(size)})`}</Heading>
      <ol id={listId}>{children(expanded)}</ol>
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
  const pending = useDisplayed((snapshot) => snapshot.pending.find(isDismissalWrite));
  const { runtime, controls } = useShell();
  const undoRef = useFocusKey<HTMLButtonElement>(controls.focusLane, 'attention:undo', {
    fallback: 'attention:title',
  });
  const reports = useMemo(() => boardReports(data), [data]);
  const [action, setAction] = useState<{
    readonly identity: { readonly harness: string; readonly sid: string };
    readonly text: string;
    readonly canUndo: boolean;
  } | null>(null);

  async function mark(row: Pick<ObservedSession, 'harness' | 'sid'>, text: string, undo = false) {
    // The dismissals store replaces the whole file. Keep this page's writes in sequence.
    if (runtime.store.getSnapshot().pending.some(isDismissalWrite)) return;
    const identity = { harness: row.harness, sid: row.sid };
    const key = markKey(identity, undo);
    const token = runtime.pending.start(key, 'Saving…');
    if (!token) return;
    try {
      const result = await runtime.client.postDismiss(
        undo ? { ...identity, clear: false } : identity,
      );
      const saved =
        result.kind === 'ok' && result.body?.ok === true && result.body.persisted === true;
      const message = saved ? `${text}.` : 'Compass could not save that change.';
      setAction({ identity, text: message, canUndo: saved && !undo });
      controls.announce(key, message);
      if (saved) void runtime.refresh();
    } finally {
      runtime.pending.end(key, token);
    }
  }

  function rowMark(row: ObservedSession, text: string) {
    if (data?.dismiss !== true) return {};
    return {
      onMark: () => void mark(row, text),
      markPending: pending === markKey(row),
      markDisabled: pending !== undefined,
      markFallback:
        action?.canUndo && sessionKey(action.identity) === sessionKey(row)
          ? 'attention:undo'
          : 'attention:title',
    };
  }

  const offCountKeys = new Set(selection?.offCountRisks.map((subject) => subject.key));
  const sourceRisks = new Map(
    observed.risks.map((risk) => [sessionKey({ harness: risk.harness, sid: risk.sid }), risk]),
  );
  const collisions = new Map(
    model.risk
      .filter((subject) => subject.primaryKind === 'collision' && !offCountKeys.has(subject.key))
      .flatMap((subject) => subject.sessions.map((row) => [sessionKey(row), subject] as const)),
  );
  const subjects = new Map(
    [...model.risk, ...model.needs, ...model.close].map((subject) => [subject.key, subject]),
  );
  const needs = selection?.waitingOnYou ?? [];
  const waitingOrder = new Map(model.needs.map(({ key }, index) => [key, index]));
  const waiting = [...needs].sort(
    (a, b) =>
      (waitingOrder.get(sessionKey(a)) ?? Infinity) - (waitingOrder.get(sessionKey(b)) ?? Infinity),
  );
  const risks = [...(selection?.worthALook ?? [])].map(([session, reason]) => {
    const key = sessionKey(session);
    const source = sourceRisks.get(key);
    const collision = reason === 'Shared project label' ? collisions.get(key) : undefined;
    const risk = collision
      ? sessionRisk(
          session,
          'collision',
          session.titleText,
          collision.signals[0]?.detail.text ?? reason,
        )
      : (source ?? sessionRisk(session, 'risk', session.titleText, reason));
    return { session, reason, risk, subject: collision ?? subjects.get(key) };
  });
  const ready = selection?.readyToWrapUp ?? [];
  const boardRisks = observed.boardRisks.filter((risk) => {
    if (!selection || risk.kind !== 'collision') return true;
    const subject = riskSubject(risk, model);
    return !subject || offCountKeys.has(subject.key);
  });
  const notices = model.risk.filter(
    (subject) => subject.kind === 'quota' && subject.identity?.project.startsWith('model:'),
  );
  const warnings = [
    ...boardRisks.map((risk) => ({ risk, retained: undefined })),
    ...notices.map((retained) => ({ risk: modelQuotaRisk(retained, model), retained })),
  ];
  const boardKeys = occurrences(warnings.map(({ risk }) => `${risk.kind}\u0000${risk.identity}`));
  const dismiss = data?.dismiss === true;
  return (
    <section className="next-attention" data-next-view-body="attention">
      <Title />
      {!selection ? (
        <p className="next-absence">The board published no session collection.</p>
      ) : !selection.counts ? (
        <p className="next-absence">
          Session counts are unavailable because the sources could not be read.
        </p>
      ) : null}
      {observed.sessions.length || !selection?.counts ? null : (
        <p className="next-attention-empty">
          {`No sessions in this ${model.windowHours == null ? 'payload' : `${String(model.windowHours)}-hour payload`}`}
        </p>
      )}
      {action ? (
        <div className="next-attention-actions" data-next-dismiss-receipt>
          <p>{action.text}</p>
          {action.canUndo && dismiss ? (
            <Button
              ref={undoRef}
              type="button"
              aria-busy={pending === markKey(action.identity, true) || undefined}
              busyLabel="Saving…"
              disabled={pending !== undefined}
              onClick={() => void mark(action.identity, 'Restored', true)}
            >
              Undo
            </Button>
          ) : null}
        </div>
      ) : null}
      <QueueSection section="needs" title={SESSION_ROW_WORDS.waitingOnYou} size={waiting.length}>
        {(expanded) =>
          waiting.map((row, index) => (
            <SessionItem
              key={sessionKey(row)}
              row={row}
              section="needs"
              model={model}
              hidden={!expanded && index >= INITIAL_SECTION_SIZE}
              subject={subjects.get(sessionKey(row))}
            />
          ))
        }
      </QueueSection>
      <QueueSection section="risk" title={SESSION_ROW_WORDS.worthALook} size={risks.length}>
        {() =>
          risks.map(({ session, reason, risk, subject }) => (
            <SessionItem
              key={sessionKey(session)}
              row={session}
              section="risk"
              model={model}
              hidden={false}
              subject={subject}
              risk={risk}
              reason={reason}
              {...rowMark(session, 'Dismissed')}
            />
          ))
        }
      </QueueSection>
      <QueueSection section="close" title="Ready to wrap up" size={ready.length}>
        {(expanded) =>
          ready.map((row, index) => (
            <SessionItem
              key={sessionKey(row)}
              row={row}
              section="close"
              model={model}
              hidden={!expanded && index >= INITIAL_SECTION_SIZE}
              subject={subjects.get(sessionKey(row))}
              {...rowMark(row, 'Marked as read')}
            />
          ))
        }
      </QueueSection>
      {data ? <UnaskedAttentionCue payload={data as unknown as Record<string, unknown>} /> : null}
      <Disclosure
        className="next-attention-limits"
        disclosureKey="attention:what-compass-cannot-see"
        headerProps={{ render: <h2 /> }}
        summary="What Compass can't see"
        searchable={false}
      >
        <div className="next-attention-brief">
          <CoverageBlock model={model} observed={observed} />
          {selection &&
            observed.counters.map((counter, index) => (
              <p
                key={counter.label}
                data-next-fleet-fact={index === 0 ? 'requests' : 'reported-blocks'}
              >
                {counter.noteText}.
              </p>
            ))}
          {selection?.limitedStateCount ? (
            <p>{`${selection.limitedStateCount} with limited state evidence.`}</p>
          ) : null}
          <RouteAnchor
            route={{ view: 'projects', project: null, session: null }}
            className="next-attention-projects-link"
          >
            View all projects
          </RouteAnchor>
        </div>
        {warnings.length ? (
          <section className="next-attention-section" data-next-attention-section="board-risk">
            <Heading section="board-risk">Other warnings</Heading>
            <ol>
              {warnings.map(({ risk, retained }, index) => (
                <RiskItem
                  key={boardKeys[index]}
                  risk={risk}
                  index={index}
                  model={model}
                  board
                  retained={retained}
                />
              ))}
            </ol>
          </section>
        ) : null}
        <CommandReportsSection reports={reports} />
        <section className="next-attention-section" data-next-attention-section="open">
          <Heading section="open">Not on this board yet</Heading>
          <ul className="next-attention-open">
            {observed.open.map(([key, name, note]) => (
              <li key={key} data-next-open={key}>
                <strong>{name}</strong>
                <p>{note}</p>
              </li>
            ))}
          </ul>
        </section>
      </Disclosure>
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

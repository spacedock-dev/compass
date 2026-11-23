import { sessionState, sessionStateLimit } from '../observed';
import { declaredRelations } from './declared';
import { RelationshipLabels, LinkedChildren } from './DeclaredRelationships';
import { Badge } from '../ui/badge';
import { useHoldStill } from './useHoldStill';
import { Card } from '../ui/card';
import { useMemo, useState, useSyncExternalStore, type ReactNode } from 'react';
import { Disclosure, RaiseControl, disclosureKey, useFocusKey } from '../controls';
import { noTitleText, pageTitleOf, type ObservedSession, type Row } from '../observed';
import { selectObserved } from '../observed/select';
import type { SessionRoute } from '../router/grammar';
import { isSampleRoute } from '../sample/ids';
import { useDisplayed, useShell } from '../shell/context';
import type { PayloadData } from '../api/types';
import { AnswerBlock } from './AnswerBlock';
import { WaitingBlock } from './WaitingBlock';
import { SessionAge } from './SessionAge';
import { usePruneAnswerNotes } from './usePruneAnswerNotes';
import {
  useDrift,
  DriftBody,
  DriftProvider,
  DriftStamp,
  DriftHeadControls,
  MonitorQuestion,
  ReadingCapBanner,
  WorkListView,
} from '../drift';
import { SessionProgressLevel } from '../drift/DriftLevelView';
import { DriftSlot } from './DriftSlot';
import { SessionTechnicalDetails } from './SessionTechnicalDetails';
import { WhatItDid } from './WhatItDid';
import {
  AtAGlance,
  CommandReportsView,
  DeliveryView,
  DeparturesKept,
  FactsView,
  HealthView,
  InstructionLine,
  LandedView,
  RightNow,
  SessionProject,
  TasksView,
} from './DetailParts';
import {
  askingTitle,
  commandReports,
  detailState,
  raiseLimit,
  sessionAsks,
  sessionDelivery,
  sessionFacts,
  sessionFigures,
  sessionHealth,
  sessionMeta,
  turnEndedSentence,
  sessionSubagents,
  sessionTasks,
} from './detail';
import { harnessLabels } from './rows';
import { sessionInstruction } from './intent';
import { worktreeOf } from './worktree';
import './sessions.css';

/* The two columns and narrow reading order follow the
   [dated layout amendment](../../../docs/design-reading-a-session.md#amended-2026-11-22-owner-the-session-page-has-two-columns-from-1100-px). */

function Controls({
  session,
  observed,
  route,
}: {
  readonly session: Row;
  readonly observed: ObservedSession;
  readonly route: SessionRoute;
}) {
  const shell = useShell();
  const rawHarness = String(session['harness'] == null ? '' : session['harness']);
  const rawSid = String(session['sid'] || '');
  const trimmedSid = rawSid.trim();
  const focusCapability = shell.controls.focus !== null;
  const raisable =
    session['focusable'] === true &&
    Boolean(trimmedSid) &&
    Boolean(rawHarness.trim()) &&
    focusCapability;
  const limit = raiseLimit(raisable, focusCapability);
  const missing = [
    !raisable ? (focusCapability ? 'No terminal to raise' : 'Terminal raise off') : '',
  ].filter(Boolean);
  return (
    <>
      <div className="next-session-controls">
        {observed.isNeeds ? (
          <RaiseControl
            harness={rawHarness.trim()}
            sid={trimmedSid}
            focusable={session['focusable'] === true}
            primary
          />
        ) : null}
      </div>
      {(observed.isNeeds || observed.askKnown) && missing.length ? (
        <div className="next-session-reentry-none">
          <span className="next-session-reentry-clause">{missing.join(' · ')}</span>
          {/* A popover: this row is a flex row ending at the controls, and an in-flow body widened the item to its paragraphs and dragged "Why" 492px left. */}
          <Disclosure
            disclosureKey={disclosureKey({
              project: route.project,
              scope: `${route.harness ?? ''}:${route.session}`,
              name: 'reentry-why',
            })}
            summary="Why"
            variant="popover"
          >
            {!raisable ? <ReentryLine text={limit} /> : null}
          </Disclosure>
        </div>
      ) : null}
    </>
  );
}

function ReentryLine({ text }: { readonly text: string }) {
  return (
    <p className="next-departure-reentry-why" data-absence="not-observed">
      {text}
    </p>
  );
}

function CommandSurface({
  session,
  observed,
  generated,
}: {
  readonly session: Row;
  readonly observed: ObservedSession;
  readonly generated: number | null;
}) {
  const context = sessionInstruction(session, 'agent') ?? sessionInstruction(session, 'earlier');
  const state = observed.isNeeds
    ? 'waiting on you'
    : observed.isEnded
      ? 'session ended'
      : observed.state;
  const turnEnd = session['waiting_on_child']
    ? null
    : turnEndedSentence(session, generated, observed.askKnown);
  return (
    <div className="next-session-command-surface" aria-label="Session command surface">
      <Card
        as="section"
        variant="session-current"
        tone={observed.tone}
        className="next-session-current"
        data-next-session-command="activity"
      >
        <span className="next-session-current-label">CURRENT ACTIVITY</span>
        <strong
          {...(observed.askKnown || observed.nowKnown ? {} : { className: 'next-session-absent' })}
        >
          {observed.askKnown ? observed.askText : (turnEnd ?? `${state} · ${observed.nowText}`)}
        </strong>
        {context ? (
          <InstructionLine
            session={session}
            generated={generated}
            className="next-session-command-context"
          />
        ) : null}
      </Card>
    </div>
  );
}

function SessionMetadata({
  session,
  generated,
  hasOpenRequest,
}: {
  readonly session: Row;
  readonly generated: number | null;
  readonly hasOpenRequest: boolean;
}) {
  const drift = useDrift();
  const meta = sessionMeta(
    session,
    generated,
    drift.model.entryCount,
    drift.model.windowCount,
    drift.model.entriesPartial,
    hasOpenRequest,
  );
  return meta ? <p className="next-session-detail-meta">{meta}</p> : null;
}

function Header({
  session,
  observed,
  route,
  generated,
  payload,
  sessions,
  harnessLabel,
}: {
  readonly payload: Row;
  readonly sessions: readonly ObservedSession[];
  readonly harnessLabel: string | undefined;
  readonly session: Row;
  readonly observed: ObservedSession;
  readonly route: SessionRoute;
  readonly generated: number | null;
}) {
  const shell = useShell();
  const titleRef = useFocusKey<HTMLHeadingElement>(shell.controls.focusLane, 'session-title');
  const relations = declaredRelations(payload, session);
  const status = sessionState(observed);
  const limit = sessionStateLimit(observed, status);
  const showState = status !== 'State not published' && status !== 'Waiting on child';
  const title = pageTitleOf(session);
  return (
    <header
      /* The edge runs beside the title and its status alone, padded off the text: drawn down the whole
         unpadded page it ran its full height and over the title's first letter (owner, 2026-10-29). */
      className={`next-session-detail-header${observed.isNeeds || observed.askKnown ? ' pb-0 border-l-[3px] border-l-[var(--amber)] pl-[14px]' : ''}`}
    >
      <div className="next-session-heading-row">
        <div className="next-session-detail-title">
          <h1
            ref={titleRef}
            tabIndex={-1}
            className={`${title ? '' : 'next-session-absent'}${observed.isNeeds || observed.askKnown ? ' line-clamp-2' : ''}`}
            title={title || noTitleText(session)}
            data-authored={Boolean(title) || undefined}
          >
            {title || noTitleText(session)}
          </h1>
          {showState ? (
            <span className="inline-flex" data-next-session-status>
              <Badge variant="status" className="next-session-state">
                <span className="next-visually-hidden">State: </span>
                {status}
              </Badge>
            </span>
          ) : null}
        </div>
        <DriftStamp />
      </div>
      <div className="next-session-detail-bar">
        <p className="next-session-identity">
          {harnessLabel ?? 'Session source not published'}
          {worktreeOf(session) ? (
            <>
              {' '}
              · worktree <span data-authored>{worktreeOf(session)}</span>
            </>
          ) : null}
          <SessionAge session={session} generated={generated} />
        </p>
        <SessionProgressLevel />
        <Controls session={session} observed={observed} route={route} />
      </div>
      {limit && status !== 'Waiting on child' ? (
        <p className="next-session-detail-meta" data-next-session-state-limit>
          {limit}
        </p>
      ) : null}
      <RelationshipLabels
        source={session}
        relations={relations}
        focusScope={`session:${observed.harness}:${observed.sid}`}
      />
      <LinkedChildren relations={relations} sessions={sessions} />
    </header>
  );
}

function SessionFigures({ session }: { readonly session: Row }) {
  const { model } = useDrift();
  return <AtAGlance figures={sessionFigures(session, model.entryCount, model.entriesPartial)} />;
}

export interface SessionDetailProps {
  readonly route: SessionRoute;
  readonly data: PayloadData;
  readonly session: Row;
}

const sessionColumns = '(min-width: 1100px)';

function subscribeToColumns(listener: () => void) {
  const media = globalThis.matchMedia?.(sessionColumns);
  media?.addEventListener?.('change', listener);
  return () => media?.removeEventListener?.('change', listener);
}

function hasTwoColumns(): boolean {
  return globalThis.matchMedia?.(sessionColumns).matches ?? false;
}

export function SessionDetail({ route, data, session }: SessionDetailProps): ReactNode {
  const payload = data as unknown as Row;
  const model = useDisplayed(selectObserved);
  const observed = useMemo(
    () =>
      model.sessions.find(
        (row) =>
          row.harness === String(session['harness'] ?? '') &&
          row.sid === String(session['sid'] ?? '') &&
          row.project === String(session['project'] ?? ''),
      ) ?? null,
    [model, session],
  );
  const labels = useMemo(() => harnessLabels(payload), [payload]);
  const generated =
    typeof payload['generated'] === 'number' && Number.isFinite(payload['generated'])
      ? payload['generated']
      : null;
  const asks = useMemo(() => sessionAsks(payload, session), [payload, session]);
  usePruneAnswerNotes(payload);
  const scope = `${route.harness ?? ''}:${route.session}`;
  const wide = useSyncExternalStore(subscribeToColumns, hasTwoColumns);
  const [page, setPage] = useState<HTMLElement | null>(null);
  useHoldStill(page);
  if (!observed) return null;
  const blocked = observed.isNeeds ? ' next-session-detail--blocked' : '';
  const state = detailState(session['state']);
  const facts = sessionFacts(observed, asks);
  const tasks = sessionTasks(observed.tasks);
  const subagents = sessionSubagents(observed.subagents, observed.subagentsOmitted, generated);
  const health = sessionHealth(session);
  const reports = commandReports(payload, session);
  const delivery = sessionDelivery(session);
  const asked = sessionInstruction(session, 'asked');
  const factKey = (name: string) => disclosureKey({ project: route.project, scope, name });
  const rightNow = (
    <RightNow session={session} observed={observed} generated={generated} subagents={subagents} />
  );
  return (
    <article
      ref={setPage}
      className={`next-session-detail${blocked}`}
      data-next-session-detail={String(session['sid'] ?? '')}
      {...(state ? { 'data-next-session-state': state.token } : {})}
      data-tone={observed.tone}
    >
      <ReadingCapBanner payload={payload} />
      <MonitorQuestion session={session} payload={payload} />
      <DriftProvider session={session} payload={payload} project={route.project}>
        <Header
          session={session}
          observed={observed}
          route={route}
          generated={generated}
          payload={payload}
          sessions={model.sessions}
          harnessLabel={labels.get(observed.harness)}
        />
        {observed.askKnown ? (
          <AnswerBlock
            payload={payload}
            session={session}
            observed={observed}
            asks={asks}
            title={askingTitle(labels, session)}
          />
        ) : observed.isNeeds ? (
          <WaitingBlock observed={observed} />
        ) : null}
        <div className="next-session-columns" data-wide={wide || undefined}>
          <div className="next-session-column">
            <DriftSlot
              session={session}
              payload={payload}
              project={route.project}
              actions={<DriftHeadControls />}
              drift={<DriftBody primary={!(observed.isNeeds || observed.askKnown)} />}
            />
            {wide ? null : rightNow}
            <WhatItDid
              running={observed.isWorking || observed.isNeeds}
              harness={labels.get(observed.harness) ?? observed.harness}
            />
          </div>
          <div className="next-session-column">
            {wide ? rightNow : null}
            <SessionFigures session={session} />
            <SessionProject project={observed.project} viewOnly={isSampleRoute(route)} />
          </div>
          <SessionTechnicalDetails
            project={route.project}
            session={session}
            reports={
              <div className="flex flex-col gap-3">
                <h2 className="m-0 text-value font-semibold">
                  How it ended, reports and notifications
                </h2>
                {payload['annotate'] === true ? (
                  <LandedView landing={observed.landing} disclosureKey={factKey('landed-why')} />
                ) : null}
                <CommandReportsView reports={reports} disclosureKey={factKey('command-reports')} />
                {delivery ? <DeliveryView delivery={delivery} /> : null}
              </div>
            }
          >
            <SessionMetadata
              session={session}
              generated={generated}
              hasOpenRequest={observed.askKnown}
            />
            <p className="next-session-identity">
              {`${observed.harness} · ${observed.sid}`}
              {observed.rateKnown && !observed.isEnded && !observed.isQuiet
                ? ` · ${observed.rateText.replace(/ \/m$/, ' tokens/min')}`
                : ''}
            </p>
            <WorkListView />
            <CommandSurface session={session} observed={observed} generated={generated} />
            <FactsView facts={facts} disclosureKey={factKey('session-facts')} />
            <div className="next-session-evidence">
              {asked ? (
                <section data-next-session-command-fact="assignment">
                  <h2>Current task</h2>
                  <InstructionLine
                    session={session}
                    generated={generated}
                    className="next-session-command-context"
                  />
                </section>
              ) : null}
            </div>
            {health ? <HealthView health={health} /> : null}
            {tasks ? <TasksView tasks={tasks} /> : null}
            {payload['annotate'] === true ? (
              <DeparturesKept disclosureKey={factKey('kept-why')} />
            ) : null}
          </SessionTechnicalDetails>
        </div>
      </DriftProvider>
    </article>
  );
}

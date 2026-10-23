import { Badge } from '../ui/badge';
import { useHoldStill } from './useHoldStill';
import { Card } from '../ui/card';
import { useMemo, useState, type ReactNode } from 'react';
import { Disclosure, RaiseControl, disclosureKey, useFocusKey } from '../controls';
import { endedAt, noTitleText, pageTitleOf, type ObservedSession, type Row } from '../observed';
import { selectObserved } from '../observed/select';
import { sessionHome, type SessionRoute } from '../router/grammar';
import { useDisplayed, useShell } from '../shell/context';
import type { PayloadData } from '../api/types';
import { AnswerBlock } from './AnswerBlock';
import { SessionAge } from './SessionAge';
import { usePruneAnswerNotes } from './usePruneAnswerNotes';
import {
  useDrift,
  DriftBody,
  DriftPill,
  DriftProvider,
  DriftStamp,
  DriftHeadControls,
  DeparturesSection,
  MonitorQuestion,
  ReadingCapBanner,
  WorkListView,
} from '../drift';
import { DriftSlot } from './DriftSlot';
import { FullActivity } from './FullActivity';
import { WhatItDid } from './WhatItDid';
import {
  CommandReportsView,
  DeliveryView,
  DeparturesKept,
  FactsView,
  HealthView,
  InstructionLine,
  LandedView,
  SubagentsView,
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
  sessionFooter,
  sessionHealth,
  sessionMeta,
  turnEndedSentence,
  sessionSubagents,
  sessionTasks,
} from './detail';
import { RouteAnchor } from './SessionsView';
import { harnessLabels } from './rows';
import { sessionInstruction } from './intent';
import { worktreeOf } from './worktree';
import './sessions.css';

/* The session page: one exact session, its state, what it is waiting on, and what it has done. Identity is
   the harness and the sid together, never the display id, and every control it carries acts only when
   pressed. The legacy `next-session.js` is the oracle for every sentence outside the Intent, summary and
   Drift cards.

   One column at every width, top to bottom: the header, the answer block when the session needs input, the
   Intent card, the What the session has done card, the Drift card, and Full activity, collapsed. The owner
   reversed the two-column layout on 2026-10-19:
   [one column again](../../../docs/design-reading-a-session.md#amended-2026-10-19-owner-one-column-again). */

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
  const turnEnd = turnEndedSentence(session);
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
        <strong {...(observed.nowKnown ? {} : { className: 'next-session-absent' })}>
          {turnEnd ?? `${state} · ${observed.nowText}`}
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
}: {
  readonly session: Row;
  readonly generated: number | null;
}) {
  const drift = useDrift();
  const meta = sessionMeta(
    session,
    generated,
    drift.model.entryCount,
    drift.model.windowCount,
    drift.model.entriesPartial,
  );
  return meta ? <p className="next-session-detail-meta">{meta}</p> : null;
}

function Header({
  session,
  observed,
  route,
  generated,
}: {
  readonly session: Row;
  readonly observed: ObservedSession;
  readonly route: SessionRoute;
  readonly generated: number | null;
}) {
  const shell = useShell();
  const titleRef = useFocusKey<HTMLHeadingElement>(shell.controls.focusLane, 'session-title');
  const state = detailState(session['state']);
  const ended = endedAt(session) !== null && !observed.askKnown;
  /* An observed end retires the state word, as it does on the Sessions rows: "working" beside "ended 1s ago"
     contradicts the line under it. A question still waiting says "needs input" whatever the collector
     inferred, because after `session_ended` pops the overlay the state is the collector's `working` or
     `idle` while the ask stays open. */
  const word = ended ? 'ended' : observed.askKnown ? 'needs input' : state?.label;
  const label = observed.project;
  const title = pageTitleOf(session);
  const showRate = observed.rateKnown && !observed.isEnded && !observed.isQuiet;
  return (
    <header
      className={`next-session-detail-header${observed.isNeeds || observed.askKnown ? ' pb-0' : ''}`}
    >
      <div className="next-session-detail-title">
        <h1
          ref={titleRef}
          tabIndex={-1}
          className={`${title ? '' : 'next-session-absent'}${observed.isNeeds || observed.askKnown ? ' line-clamp-2' : ''}`}
          title={title || noTitleText(session)}
        >
          {title || noTitleText(session)}
        </h1>
      </div>
      <div className="next-session-detail-bar">
        {/* The state with its dot leads the measured line, which already says what the session is doing and
            how long its turn has run, so the header reads "working · running Bash · turn started 3m ago"
            without a second copy of either. */}
        {state ? (
          <span className="inline-flex" data-next-session-status>
            <Badge
              variant="session-state"
              className="next-session-state inline-flex items-center gap-2"
            >
              <span
                aria-hidden="true"
                className={`inline-block size-2 shrink-0 rounded-pill ${statusDot(observed, ended)}`}
                data-next-session-status-dot
              />
              <span>
                <span className="next-visually-hidden">State: </span>
                {word}
              </span>
            </Badge>
          </span>
        ) : null}
        <p className="next-session-identity">
          {`${observed.harness} · ${observed.sid}`}
          {/* A rate belongs to a session that is producing tokens: an idle or ended one reports its last burst, which reads as speed it no longer has.
              Named in full here, where it stands alone among identifiers: a bare "44 /m" said no unit. */}
          {showRate ? ` · ${observed.rateText.replace(/ \/m$/, ' tokens/min')}` : ''}
          {label && sessionHome(route) !== 'projects' ? (
            <>
              {' · '}
              <RouteAnchor route={{ view: 'project', project: label }}>{label}</RouteAnchor>
            </>
          ) : null}
          {worktreeOf(session) ? ` · worktree ${worktreeOf(session)}` : ''}
          <SessionAge session={session} generated={generated} />
        </p>
        {!(observed.isNeeds || observed.askKnown) ? (
          <SessionMetadata session={session} generated={generated} />
        ) : null}
        <DriftPill />
        <Controls session={session} observed={observed} route={route} />
      </div>
    </header>
  );
}

/* The dot beside the state takes the colour the page gives that state everywhere else: amber when it waits on
   the reader, the accent while it works, and no colour once it rests or ends. */
function statusDot(observed: ObservedSession, ended: boolean): string {
  if (observed.isNeeds || observed.askKnown) return 'bg-[var(--amber)]';
  if (!ended && observed.isWorking) return 'bg-[var(--accent)]';
  return 'bg-[var(--ink3)]';
}

export interface SessionDetailProps {
  readonly route: SessionRoute;
  readonly data: PayloadData;
  readonly session: Row;
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
  const footer = sessionFooter(session);
  const asked = sessionInstruction(session, 'asked');
  const factKey = (name: string) => disclosureKey({ project: route.project, scope, name });
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
        <Header session={session} observed={observed} route={route} generated={generated} />
        {observed.askKnown ? (
          <AnswerBlock
            payload={payload}
            observed={observed}
            asks={asks}
            title={askingTitle(labels, session)}
          />
        ) : null}
        <div className="next-session-columns flex flex-col gap-5">
          <DriftSlot
            session={session}
            payload={payload}
            project={route.project}
            summary={
              <WhatItDid
                // Running is what the session is doing now, not that it has not ended: an idle or
                // completed session is open but does nothing until the person writes again.
                running={observed.isWorking || observed.isNeeds}
                harness={labels.get(observed.harness) ?? observed.harness}
              />
            }
            stamp={<DriftStamp />}
            actions={<DriftHeadControls />}
            drift={<DriftBody primary={!(observed.isNeeds || observed.askKnown)} />}
          >
            <DeparturesSection />
          </DriftSlot>
          <FullActivity project={route.project} session={session}>
            {observed.isNeeds || observed.askKnown ? (
              <SessionMetadata session={session} generated={generated} />
            ) : null}
            <CommandSurface session={session} observed={observed} generated={generated} />
            {/* The numbered record every "#<n>" on this page names, right after CURRENT ACTIVITY. */}
            <WorkListView />
            {subagents ? <SubagentsView subagents={subagents} /> : null}
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
            <CommandReportsView reports={reports} disclosureKey={factKey('command-reports')} />
            {delivery ? <DeliveryView delivery={delivery} /> : null}
            {/* The record under Full activity belongs to the annotation store: with it off the page this ports
              draws neither card nor pointer, and a card claiming an end the store cannot back would be new. */}
            {payload['annotate'] === true ? (
              <>
                <LandedView landing={observed.landing} disclosureKey={factKey('landed-why')} />
                <DeparturesKept disclosureKey={factKey('kept-why')} />
              </>
            ) : null}
          </FullActivity>
        </div>
        {footer ? (
          <footer className="next-session-footer" data-next-session-tokens={footer.source}>
            {footer.text}
          </footer>
        ) : null}
      </DriftProvider>
    </article>
  );
}

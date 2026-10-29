import { Card } from '../ui/card';
import { Button } from '../ui/button';
import type { ReactNode } from 'react';
import {
  CopyControl,
  Disclosure,
  disclosureKey,
  HumanContextField,
  RaiseControl,
  resumeCommand,
} from '../controls';
import { useControls, useValueStore } from '../controls/kit';
import { annotationOf } from '../intent/annotation';
import { sessionKey } from '../observed/values';
import type { ObservedSession } from '../observed';
import { RouteAnchor } from '../sessions/RouteAnchor';
import { sessKey, workingSessions } from './group';
import { instructionHeading, projectGoal } from './goal';
import { briefingOf, noteKey, type ProjectModel } from './model';
import { Value } from './parts';
import { authorityVerb, recoveryFactSource, type Briefing, type Child } from './recovery';
import { field } from './raw';
import type { Row } from './raw';

/* The strip that opens a project page: what the work is, who is doing it, what needs the captain, and the
   newest direction and result, each with where it came from. Every claim carries its source or its absence
   ("Task evidence not published", "Actionable direction not observed"), and a scan that did not
   finish says so before anything is concluded from it. The reader's own browser-local note sits at the end
   and is never presented as something the agents observed. Ported from `nextCockpitRecoveryStrip`. */

export const AUTHORITY_GLOSS =
  'FO is the first officer, the agent driving this workflow; Captain is you.';

function Source({ children }: { readonly children: ReactNode }) {
  return <span className="next-cockpit-source">{children}</span>;
}

function taskSource(source: string): string {
  return source === 'assignment source unavailable' ? 'task source unavailable' : source;
}

function disclosureKeys(model: ProjectModel) {
  return (name: string) =>
    disclosureKey({ project: model.route.project, scope: model.route.focus ?? '', name });
}

function ChildEvidence({ child, model }: { readonly child: Child; readonly model: ProjectModel }) {
  const key = disclosureKeys(model);
  const assignmentMissing = child.assignment === 'assignment unavailable';
  const resultMissing = child.result === 'result unavailable';
  const missing = [
    assignmentMissing ? 'task unavailable' : '',
    resultMissing ? child.result : '',
  ].filter(Boolean);
  return (
    <>
      {assignmentMissing || resultMissing ? (
        <p className="next-cockpit-evidence-missing">{missing.join(' · ')}</p>
      ) : null}
      <Disclosure
        disclosureKey={key(`child:${child.sourceSession}:${child.worker}:${child.lifecycle}`)}
        summary="Evidence · child handoff"
        focusKey={`cockpit-disclosure:child:${child.sourceSession}:${child.worker}:${child.lifecycle}`}
      >
        <small>
          {assignmentMissing ? 'task unavailable' : <Source>{child.assignment}</Source>}
          {child.result ? (
            <>
              {' · '}
              {resultMissing ? child.result : <Source>{child.result}</Source>}
            </>
          ) : null}
          {' · '}
          {/unavailable/i.test(child.assignmentSource) ? (
            `source ${taskSource(child.assignmentSource)}`
          ) : (
            <Source>{`source ${child.assignmentSource}`}</Source>
          )}
          {' · '}
          <Source>{`source session ${child.sourceSession}`}</Source>
          {child.lifecycle === 'returned' ? (
            <>
              {' · '}
              <Source>{`event ${String(child.at || 'unavailable')}`}</Source>
              {' · '}
              <Source>{`age ${child.age ? `${child.age} ago` : 'unavailable'}`}</Source>
            </>
          ) : null}
        </small>
      </Disclosure>
    </>
  );
}

function Execution({
  model,
  briefing,
  compactIdle,
}: {
  readonly model: ProjectModel;
  readonly briefing: Briefing;
  readonly compactIdle: boolean;
}) {
  if (compactIdle)
    return (
      <strong>
        {model.env.workflow
          ? 'No execution observed · Captain not needed'
          : 'No execution observed · You are not needed'}
      </strong>
    );
  const { group, harnesses } = model;
  const children: Child[] = [...briefing.children.active];
  if (briefing.children.latestReturn) children.push(briefing.children.latestReturn);
  const working = new Set(workingSessions(group).map((session) => sessKey(session)));
  const sessions = group.sessions.filter(
    (session) =>
      working.has(sessKey(session)) ||
      children.some((child) => child.sourceSession === sessKey(session)),
  );
  if (!sessions.length) return <strong>No execution observed</strong>;
  return (
    <>
      {sessions.map((session, index) => {
        const key = sessKey(session);
        const harness =
          harnesses.get(String(session['harness'] || '')) ||
          String(session['harness'] || 'Session');
        const state =
          session['state'] === 'needs_input'
            ? 'needs input'
            : String(session['state'] || 'unknown');
        return (
          // The same pair twice is a malformed board, and the list still needs two keys.
          <div className="next-cockpit-execution-root" key={`${key}#${String(index)}`}>
            <strong>{`${harness} · ${state}`}</strong>
            {children
              .filter((child) => child.sourceSession === key)
              .map((child, childIndex) => {
                const returned =
                  child.lifecycle === 'returned' && (child.ageSec ?? 0) >= 600
                    ? ` · stale ${child.age || 'age unavailable'}`
                    : '';
                const handoff =
                  child.lifecycle === 'returned' && child.handoffUnavailable
                    ? ' · handoff unavailable'
                    : '';
                return (
                  <div
                    className="next-cockpit-child-row"
                    key={`${child.worker}:${child.lifecycle}:${String(childIndex)}`}
                  >
                    <strong>{`${child.worker} · ${child.lifecycle}${handoff}${returned}`}</strong>
                    <ChildEvidence child={child} model={model} />
                  </div>
                );
              })}
          </div>
        );
      })}
    </>
  );
}

function Waiting({
  session,
  project,
}: {
  readonly session: ObservedSession;
  readonly project: string;
}) {
  const route = {
    view: 'session',
    project,
    harness: session.harness,
    session: session.sid,
  } as const;
  const command = resumeCommand(session.harness, String(session.resume_id || ''));
  const sid = session.sid.trim();
  return (
    <div className="next-cockpit-waiting" data-next-cockpit-waiting="">
      <span>WAITING ON YOU</span>
      <RouteAnchor route={route}>
        <Value text={session.titleText} known={session.titleKnown} />
      </RouteAnchor>
      <Value text={session.waitedText} known={session.waitedKnown} />
      {session.askKnown ? <p className="next-cockpit-source">{session.askText}</p> : null}
      <div className="next-rail-wait-controls">
        <RaiseControl
          harness={session.harness.trim()}
          sid={sid}
          focusable={session.focusable === true}
        />
        {command ? (
          <CopyControl kind="command" harness={session.harness} sid={session.sid} value={command} />
        ) : sid ? (
          <CopyControl kind="id" harness={session.harness} sid={sid} value={sid} />
        ) : null}
      </div>
    </div>
  );
}

function Attention({
  model,
  briefing,
}: {
  readonly model: ProjectModel;
  readonly briefing: Briefing;
}) {
  const key = disclosureKeys(model);
  const { attention } = model;
  const { coverage } = briefing;
  const captain = attention.filter((item) => item.owner === 'CAPTAIN');
  const system = attention.filter((item) => item.owner === 'FO');
  const needs = model.group.observed.needs.length;
  const state = captain.length
    ? 'captain-needed'
    : coverage.state !== 'complete' || system.length
      ? 'fo-inspecting'
      : 'fo-continues';
  const workflow = model.env.workflow === true;
  const stateLabel = !workflow
    ? state === 'captain-needed'
      ? 'NEEDS YOU'
      : state === 'fo-inspecting'
        ? 'CHECKING'
        : 'CONTINUES'
    : state === 'captain-needed'
      ? 'CAPTAIN NEEDED'
      : state === 'fo-inspecting'
        ? 'FO INSPECTING'
        : 'FO CONTINUES';
  const { children } = briefing;
  const compactIdle =
    state === 'fo-continues' && !children.active.length && !children.latestReturn && !needs;
  const captainTruth =
    captain.length || needs
      ? ''
      : coverage.state === 'complete'
        ? workflow
          ? 'Captain not needed'
          : 'You are not needed'
        : workflow
          ? 'Captain state unknown'
          : 'Your attention is unknown';
  const heading = compactIdle
    ? workflow
      ? 'FO CONTINUES · Continue current task'
      : 'CONTINUES · Continue the current task'
    : stateLabel;
  const row = (item: (typeof attention)[number]) => (
    <strong key={`${item.owner}\n${item.label}`}>{`${authorityVerb(item)} · ${item.label}`}</strong>
  );
  const remainder = Math.max(0, system.length - 1);
  const first = system[0];
  return (
    <div
      className={`next-cockpit-authority next-cockpit-authority--${state}`}
      data-next-cockpit-authority-state={state}
    >
      <span>{heading}</span>
      {compactIdle ? null : (
        <>
          {captain.map(row)}
          {first ? row(first) : null}
          {captainTruth ? <small>{captainTruth}</small> : null}
        </>
      )}
      {coverage.state !== 'complete' ? (
        <p className="next-cockpit-evidence-missing">{`${coverage.label} · ${coverage.source}`}</p>
      ) : null}
      <Disclosure
        disclosureKey={key('attention')}
        summary="Evidence · attention sources"
        focusKey="cockpit-disclosure:attention"
      >
        {attention.map((item) => (
          <small key={`${item.owner}\n${item.label}`}>
            {`${workflow ? item.owner : item.owner === 'CAPTAIN' ? 'YOU' : 'AGENT'} · ${item.kind || 'attention'} · ${item.label} · ${taskSource(String(field(item.evidence, 'source') || 'source unavailable'))} · ${String(field(item.evidence, 'confidence') || 'confidence unavailable')}`}
          </small>
        ))}
        {remainder ? (
          <small>{`${String(remainder)} more ${workflow ? 'FO ' : ''}${remainder === 1 ? 'action' : 'actions'}`}</small>
        ) : null}
        <small data-next-cockpit-attention-coverage="">{`${coverage.label} · ${coverage.source}`}</small>
      </Disclosure>
    </div>
  );
}

function Goal({ model }: { readonly model: ProjectModel }) {
  const focusObserved = model.focus
    ? (model.group.observed.sessions.find(
        (session) => sessionKey(session as unknown as Row) === sessionKey(model.focus),
      ) ?? null)
    : null;
  const goal = projectGoal(
    model.group.observed,
    annotationOf(model.focus),
    focusObserved,
    model.generated,
  );
  const row = (tag: string, text: string, source: string, known = true) => (
    <div className="next-project-goal-row" key={tag}>
      <span className="next-project-goal-tag">{tag}</span>
      <Value text={text} known={known} className="next-project-goal-text" />
      {source ? <span className="next-project-goal-source">{source}</span> : null}
    </div>
  );
  return (
    <Card as="section" variant="project-goal" className="next-project-goal">
      <header>
        <h2>{instructionHeading(model.group.observed, focusObserved)}</h2>
        {!goal.typed.length && goal.scope.known ? (
          <span className="next-project-goal-source">{goal.derivedSource}</span>
        ) : null}
      </header>
      {goal.typed.map((entry) => row(entry.tag, entry.text, entry.source))}
      {goal.typed.length ? (
        row('DERIVED FROM THE HARNESS', goal.scope.text, goal.derivedSource, goal.scope.known)
      ) : (
        <Value text={goal.scope.text} known={goal.scope.known} className="next-project-goal-text" />
      )}
      {goal.binding ? <p className="next-project-goal-gap">{goal.binding}</p> : null}
      {goal.gap ? <p className="next-project-goal-gap">{goal.gap}</p> : null}
    </Card>
  );
}

function Notes({ model, briefing }: { readonly model: ProjectModel; readonly briefing: Briefing }) {
  const controls = useControls();
  const editing = useValueStore(controls.memoEditing);
  if (model.focus) return null;
  const outcomeKey = noteKey(model, 'outcome');
  const focusKey = noteKey(model, 'focus');
  const open = editing !== null && [outcomeKey, focusKey].includes(editing.key);
  if (briefing.outcome === 'Not set' && briefing.currentFocus === 'Not set' && !open) {
    // The menu offers the same words where the briefing is complete, so the strip does not say it twice.
    if (briefing.task.known && briefing.coverage.state === 'complete') return null;
    return (
      <div className="next-cockpit-recovery-memos" data-next-cockpit-memo-empty="">
        <Button
          variant="context-add"
          type="button"
          onClick={() => controls.startMemoEdit(outcomeKey)}
        >
          + Add human context · this browser
        </Button>
      </div>
    );
  }
  return (
    <div className="next-cockpit-recovery-memos">
      <span>OPTIONAL HUMAN NOTE · THIS BROWSER</span>
      <HumanContextField
        key={outcomeKey}
        memoKey={outcomeKey}
        kind="outcome"
        label="OUTCOME"
        placeholder="What result should this scope achieve?"
      />
      <HumanContextField
        key={focusKey}
        memoKey={focusKey}
        kind="focus"
        label="FOCUS"
        placeholder="What are you concentrating on now?"
      />
    </div>
  );
}

export function RecoveryStrip({ model }: { readonly model: ProjectModel }) {
  const controls = useControls();
  // Opening or closing a note's editor is what changes what the strip says about the notes, so it is a
  // reason to read them again. Typing is not: it writes the memory the next draw reads.
  useValueStore(controls.memoEditing);
  // The two notes are read as the strip draws: a draw is a read, and storage is never written by one.
  const briefing = briefingOf(model, (memo) => controls.memo.read(memo));
  const key = disclosureKeys(model);
  const { attention, group } = model;
  const captain = attention.filter((item) => item.owner === 'CAPTAIN');
  const system = attention.filter((item) => item.owner === 'FO');
  const authorityState = captain.length
    ? 'captain-needed'
    : briefing.coverage.state !== 'complete' || system.length
      ? 'fo-inspecting'
      : 'fo-continues';
  const compactIdle =
    authorityState === 'fo-continues' &&
    !briefing.children.active.length &&
    !briefing.children.latestReturn &&
    !group.observed.needs.length &&
    !workingSessions(group).length;
  const { task, latest } = briefing;
  const exactLabel = latest.stale
    ? 'ACTIONABLE DIRECTION · STALE CACHED'
    : 'LATEST ACTIONABLE DIRECTION';
  const directionSource = latest.direction ? recoveryFactSource(latest.direction) : 'unavailable';
  const resultSource = latest.result ? recoveryFactSource(latest.result) : 'unavailable';
  const resultLabel =
    latest.resultKind === 'semantic'
      ? latest.stale
        ? 'LATEST EXACT RESULT · STALE CACHED'
        : 'LATEST EXACT RESULT'
      : 'LATEST SESSION RESULT';
  const directionEvidence = latest.direction
    ? `promoted exact direction · source session ${directionSource}`
    : 'actionable direction not observed';
  const resultEvidence =
    latest.resultKind === 'semantic'
      ? `exact semantic result · source session ${resultSource}`
      : latest.resultKind === 'session'
        ? `session output; semantic result not published · source session ${resultSource}`
        : '';
  const taskText = task.known
    ? [task.label, task.stage].filter(Boolean).join(' · ')
    : 'Not observed';
  const fact = task.fact;
  const latestEvidence = [
    latest.direction ? directionEvidence : '',
    latest.result ? resultEvidence : '',
  ].filter(Boolean);
  const waiting = group.observed.needs[0];
  return (
    <Card
      as="section"
      variant="project-recovery"
      className="next-cockpit-recovery"
      aria-label="Recovery summary"
    >
      <header>
        <strong>Where this project stands</strong>
        {model.env.workflow ? (
          <small className="next-cockpit-recovery-gloss">{AUTHORITY_GLOSS}</small>
        ) : null}
      </header>
      <div
        data-next-cockpit-task=""
        {...(task.id ? { 'data-work-item': task.id } : {})}
        {...(task.known ? { 'data-next-cockpit-task-known': '' } : {})}
      >
        <span>Current task</span>
        <strong>{taskText}</strong>
        {task.known && task.qualifier ? <small>{task.qualifier}</small> : null}
        {task.known && task.provenance ? (
          <Disclosure
            disclosureKey={key(`assignment:${task.id || task.sourceSession}`)}
            summary="Evidence · task source"
            focusKey={`cockpit-disclosure:assignment:${task.id || task.sourceSession}`}
          >
            <small className="next-cockpit-source">
              {`${task.provenance}${task.sourceSession ? ` · source session ${task.sourceSession}` : ''}${fact && fact['at'] ? ` · event ${String(fact['at'])}` : ''}`}
            </small>
          </Disclosure>
        ) : task.known ? (
          <small className="next-cockpit-evidence-missing">Task evidence not published</small>
        ) : null}
        <Goal model={model} />
      </div>
      <div>
        <span>Running now</span>
        <Execution model={model} briefing={briefing} compactIdle={compactIdle} />
      </div>
      <div>
        <span>Needs you</span>
        {waiting ? <Waiting session={waiting} project={model.route.project} /> : null}
        <Attention model={model} briefing={briefing} />
      </div>
      <div className="next-cockpit-recovery-evidence">
        <span>Latest result</span>
        {latest.directionInAssignment ? (
          <p>Direction shown in the current task</p>
        ) : latest.direction ? (
          <>
            <span>{exactLabel}</span>
            <strong>{String(latest.direction['summary'])}</strong>
          </>
        ) : null}
        {latest.result ? (
          <>
            <span>{resultLabel}</span>
            <strong>
              {String(field(latest.result, 'display') || field(latest.result, 'summary') || '')}
            </strong>
          </>
        ) : null}
        {latest.direction || latest.result ? (
          <>
            {!latest.direction ? (
              <p className="next-cockpit-evidence-missing">Actionable direction not observed</p>
            ) : null}
            {!latest.result ? (
              <p className="next-cockpit-evidence-missing">Session result not observed</p>
            ) : null}
            <Disclosure
              disclosureKey={key('latest')}
              summary="Evidence · direction and result sources"
              focusKey="cockpit-disclosure:latest"
            >
              {latestEvidence.map((value) => (
                <small className="next-cockpit-source" key={value}>
                  {value}
                </small>
              ))}
            </Disclosure>
          </>
        ) : (
          <p className="next-cockpit-evidence-missing">
            Actionable direction not observed · Session result not observed
          </p>
        )}
      </div>
      <Notes model={model} briefing={briefing} />
    </Card>
  );
}

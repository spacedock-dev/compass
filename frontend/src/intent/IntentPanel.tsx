import { Card } from '../ui/card';
import './intent.css';
import { useEffect, useLayoutEffect, useMemo, type ReactNode } from 'react';
import { payloadSessions } from '../api/bootstrap';
import { compatSessKey, contextKey, stableProjectKey } from '../api/identity';
import { nextFiniteNumber } from '../api/bootstrap';
import type { Row } from '../observed';
import { goalFocusFor } from '../sessions/heldState';
import { useDisplayed, useShell } from '../shell/context';
import { annotationOf, annotateOn, heldCap } from './annotation';
import { DirectionQuestion } from './DirectionQuestion';
import { chosenIsStale, goalKey, intentDraft, type DraftInput } from './derive';
import { reconcileDirection } from './directions';
import { IntentSection } from './IntentSection';
import { LIVE_HARNESSES } from './liveMonitor';
import { LiveMonitorSwitch } from './LiveMonitorSwitch';
import { DRIFT_SUBTITLE } from './sentences';
import { LIVE_HINT } from '../drift/sentences';
import { PanelContext, useHeldVersion, useIntentCtx, type Panel } from './useIntent';
import { workSource } from './work';

/* The Intent card, the What the session has done card and the Drift card, top to bottom in the session page's
   one column: the reader's own words first (the goal, the expected outcome and the one save for both), then
   what the session did, then the Drift section, where the reading, its control and the departures belong to
   the Analyze step and arrive through `drift`. Your words come first, so nothing above the reading is a
   model's.

   Everything the panel sends it sends on a press: a save, a discard, an adopted prompt, a direction opened
   for review. Mounting it, mounting it twice under StrictMode, a board refresh or a reconnect sends none of
   them. The only reads it starts are passive ones of the observed record, which spend nothing. */

export interface IntentPanelProps {
  /** The session's row as the board published it. */
  readonly session: Row;
  /** The board the page is showing. */
  readonly payload: Row;
  /** The session's project label, which names disclosures and, with the project key, its context. */
  readonly project: string;
  /** The Drift section's body: the live estimate, the reading control, the reading and its departures. */
  readonly drift?: ReactNode;
  /** The What the session has done card, drawn between the Intent card and the Drift card. */
  readonly summary?: ReactNode;
  /** The Drift card header's model and when the analysis last ran, beside its title. */
  readonly stamp?: ReactNode;
  /** What the session page composes beneath: the delegated-work line and the departures raised away. */
  readonly children?: ReactNode;
}

export const DRIFT_SLOT_PLACEHOLDER =
  'The drift reading and Analyze are not available in the React interface yet. They arrive with a later migration step (drift and analysis); the Python dashboard still serves them.';

function DriftSlotPlaceholder() {
  return (
    <p className="next-placeholder" data-next-placeholder="session-drift" data-next-owner="drift">
      {DRIFT_SLOT_PLACEHOLDER}
    </p>
  );
}

export function IntentPanel({
  session,
  payload,
  project,
  drift,
  summary,
  stamp,
  children,
}: IntentPanelProps) {
  const shell = useShell();
  const { runtime, controls } = shell;
  const ctx = useIntentCtx();
  useHeldVersion(ctx.held);
  useEffect(() => ctx.held.activate(), [ctx]);
  const contexts = useDisplayed((snapshot) => snapshot.contexts);
  const generated = nextFiniteNumber(payload['generated']);
  const harness = String(session['harness'] || '');
  const sid = String(session['sid'] || '');
  const annotating = annotateOn(payload);
  const monitor = annotating && LIVE_HARNESSES.has(harness);
  const projectKey = useMemo(
    () =>
      stableProjectKey({
        label: project,
        sessions: payloadSessions(payload as never).rows.filter(
          (row) => String(row.project ?? '') === project,
        ),
      }),
    [payload, project],
  );
  const annotation = useMemo(() => annotationOf(session), [session]);
  const input: DraftInput = useMemo(
    () => ({ held: ctx.held, contexts, payload, session, annotation }),
    [ctx.held, contexts, payload, session, annotation],
  );
  const records = useDisplayed((snapshot) => snapshot.records);
  const source = workSource(
    contexts,
    projectKey,
    session,
    records.get(contextKey(projectKey, session as never)),
  );

  /* The passive reads of the observed record this panel's later directions and prompt menu stand on, started
     once per board revision and never by an action. The runtime makes a repeat for a revision it has settled
     a no-op, which is what keeps StrictMode and a remount from reading twice. */
  // biome-ignore lint/correctness/useExhaustiveDependencies: the revision is the refetch trigger, not a value the body reads.
  useEffect(() => {
    if (!annotating || !harness || !sid) return;
    runtime.loadContext({ projectKey, focus: null });
    runtime.loadContext({ projectKey, focus: { harness, sid } });
  }, [runtime, annotating, projectKey, harness, sid, generated]);

  /* A held choice that no longer stands, and a pending line whose direction left the list, are dropped once
     the render that found them has drawn. */
  useEffect(() => {
    if (chosenIsStale(input)) {
      ctx.held.chosen.delete(goalKey(session));
      ctx.held.notify();
    }
    reconcileDirection(ctx, input, projectKey);
  });

  /* The focus a press asked for, once its controls are drawn. */
  useLayoutEffect(() => {
    const name = ctx.held.takeFocus();
    if (name) controls.focusLane.focus(name);
  });

  /* A goal link opened this session and asked for focus on its goal. Over an untouched draft it lands on the
     panel's heading, not the box: a focused box that holds still under the mouse cannot also grow to show
     the whole draft, and Keep adopts all of it. With nothing drafted the empty box is what the link offered.
     Consumed once, by the first panel drawn for this exact session. */
  useEffect(() => {
    if (!goalFocusFor(controls).take({ harness, sid })) return;
    const drafted = intentDraft(input);
    const held = ctx.held.goals;
    const untouched =
      Boolean(drafted) &&
      (!held.has(goalKey(session)) || held.get(goalKey(session)) === drafted?.text);
    const heading = `intent:${compatSessKey(session)}`;
    if (annotating && !untouched && controls.focusLane.focus(goalKey(session))) return;
    controls.focusLane.focus(heading);
  }, [controls, harness, sid, input, session, annotating, ctx.held.goals]);

  const panel: Panel = {
    ctx,
    input,
    session,
    payload,
    harness,
    sid,
    project,
    projectKey,
    source,
    cap: heldCap(payload),
  };
  return (
    <PanelContext value={panel}>
      <div
        className="next-session-panel max-[760px]:gap-1"
        data-next-session-drift
        data-next-session-panel="intent"
      >
        {annotating ? <IntentSection /> : null}
        {summary}
        <Card
          variant="drift-panel"
          as="section"
          className="next-session-drift"
          id="next-session-drift"
          aria-labelledby="next-session-drift-heading"
        >
          <header className="next-session-drift-head max-[760px]:py-0">
            <div className="next-session-drift-titles flex flex-wrap items-baseline gap-x-2">
              <h2 id="next-session-drift-heading" className="next-session-drift-heading">
                Drift
              </h2>
              {stamp}
              <p className="next-session-drift-sub basis-full text-body">{DRIFT_SUBTITLE}</p>
            </div>
            {/* The live monitor and what it does, in the head of the card it controls now that More is retired:
                placement only, its value and default are unchanged.
                [The More inventory](../../../docs/design-reading-a-session.md#where-everything-in-more-went) */}
            <LiveMonitorSwitch />
            {monitor ? (
              <div className="basis-full">
                <p className="next-cockpit-reading-why m-0" data-next-live-hint>
                  {LIVE_HINT}
                </p>
              </div>
            ) : null}
          </header>
          {drift ?? (
            <>
              <DirectionQuestion />
              <DriftSlotPlaceholder />
            </>
          )}
          {children}
        </Card>
      </div>
    </PanelContext>
  );
}

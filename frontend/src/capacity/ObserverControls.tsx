import { Alert } from '../ui/alert';
import { Card } from '../ui/card';
import { Button } from '../ui/button';
import { useEffect, useState } from 'react';
import { contextKey, exactIdentity } from '../api/identity';
import type { ProjectContext, SessionIdentity } from '../api/types';
import { useFocusKey } from '../controls/useFocusKey';
import { useDisplayed, useShell } from '../shell/context';
import { selectObserverModel, selectObserverRequest, selectObserverOff } from '../store/selectors';
import { resumeModelCalls, turnOffReadings } from '../api/readings';
import { isRecord } from '../observed';
import { ModelNotice } from '../drift/ModelNotice';
import { noticeAnnouncement, noticeLabel } from '../drift/notice';
import { MODEL_PAUSE_EXPLANATION, READINGS_OFF_CONSOLE } from '../drift/sentences';
import { heldFor, useConsent } from './held';
import './capacity.css';

/* The optional model goal summary, offered in the Console for one exact session. It runs without a prior
   question and the server records the notice
   ([the widening](../../../docs/design-session-summary.md#the-widening-opt-out-with-a-notice-for-every-call-a-reader-starts)),
   but a request still goes out only on the press of "Summarize this session", for the exact session drawn,
   and the press names the disclosure the reader was shown: if the offer the board holds now is not the one on
   screen, nothing is sent and the reader is told so. Mounting, a poll, a reconnect and a route change send
   nothing. */

const ABSENT = 'Observer model availability has not been read.';
const DISABLED =
  'Observer model is disabled for this run. Restart without --no-observer-model or its alias --no-harness-usage to offer goal summaries.';
const NO_SESSION = 'Select one exact session to request an optional model goal summary.';
const NO_DISCLOSURE = 'Observer disclosure is unavailable; model requests are withheld.';
const SUMMARIES_DECLINED =
  'Goal summaries are off in this browser. Nothing is sent for a summary until you turn them back on.';
const DISCLOSURE_CHANGED =
  'The observer model offer changed since this page was drawn, so nothing was sent; read it now and press again.';

export interface ObserverControlsProps {
  /** The stable project key the context is read by, which is not always the route's label. */
  readonly projectKey: string;
  /** The exact selected session, or null at project scope. A display id is not an identity. */
  readonly focus: SessionIdentity | null;
}

function Absence({ children }: { readonly children: string }) {
  return <p className="next-cockpit-empty">{children}</p>;
}

export function ObserverControls({ projectKey, focus }: ObserverControlsProps) {
  const { runtime, controls, display, announcer } = useShell();
  const identity = focus ? exactIdentity(focus) : null;
  const key = contextKey(projectKey, identity);
  const entry = useDisplayed((snapshot) => snapshot.contexts.get(key));
  /* Two primitives, not `selectObserverRequest`'s pair: a selector that builds an object returns a new one
     on every read, and a subscription over it would never settle. */
  const pending = useDisplayed((snapshot) => selectObserverRequest(snapshot, key).pending);
  const state = useDisplayed((snapshot) => selectObserverRequest(snapshot, key).state);
  const off = useDisplayed((snapshot) => selectObserverOff(snapshot, key, identity));
  const offPending = useDisplayed((snapshot) => snapshot.pending.includes('observer:off'));
  /* The notice the last Summarize reply carried, held by the store past the passive reads that replace the
     context entry, so the notice and its off switch stay until a turn-off or the next reply. */
  const notice = useDisplayed((snapshot) => snapshot.observer.notices.get(key));
  const declined = useConsent('observer') === 'declined';
  useEffect(() => {
    if (!notice || off) return;
    const said = noticeAnnouncement({ ...notice });
    announcer.announce(said.key, said.sentence);
  }, [notice, off, announcer]);
  const [refused, setRefused] = useState<string | null>(null);
  const requestRef = useFocusKey<HTMLButtonElement>(controls.focusLane, 'observer:request');
  const offRef = useFocusKey<HTMLButtonElement>(controls.focusLane, 'observer:off');
  const model = selectObserverModel(entry);
  if (!model) return <Absence>{ABSENT}</Absence>;
  if (model.enabled !== true) return <Absence>{DISABLED}</Absence>;
  if (!identity) return <Absence>{NO_SESSION}</Absence>;
  const disclosure = String(model.disclosure || '');
  if (!disclosure) return <Absence>{NO_DISCLOSURE}</Absence>;

  const summarize = () => {
    setRefused(null);
    if (selectObserverOff(runtime.store.getSnapshot(), key, identity)) {
      setRefused(READINGS_OFF_CONSOLE);
      return;
    }
    const now: ProjectContext['observer_model'] | null = selectObserverModel(
      runtime.store.getSnapshot().contexts.get(key),
    );
    if (now?.enabled !== true || String(now.disclosure || '') !== disclosure) {
      setRefused(DISCLOSURE_CHANGED);
      return;
    }
    void runtime.requestObserverSummary({ projectKey, focus: identity });
  };
  const turnOff = async () => {
    const press = runtime.pending.start(
      'observer:off',
      off ? 'Resuming…' : 'Pausing…',
      off ? 'Resuming model calls.' : 'Pausing model calls.',
    );
    if (!press) return;
    setRefused(null);
    try {
      const reply = await (off ? resumeModelCalls : turnOffReadings)(runtime.client, press.signal);
      const body = reply.kind === 'ok' && isRecord(reply.body) ? reply.body : null;
      const reading = body && isRecord(body['reading']) ? body['reading'] : null;
      if (body?.['ok'] !== true || !reading) throw new Error('off not confirmed');
      // The server cleared every notice with the off.
      runtime.store.clearObserverNotices();
      const snapshot = runtime.store.getSnapshot();
      if (snapshot.data) runtime.store.acceptData({ ...snapshot.data, reading }, snapshot.revision);
      await display.paint({ manual: true, accepted: true });
    } catch {
      setRefused(
        off
          ? 'Could not confirm model calls resumed. Try resuming again.'
          : 'Could not confirm model calls are paused. Try pausing again.',
      );
    } finally {
      runtime.pending.end('observer:off', press);
    }
  };
  const turnOn = () => {
    setRefused(null);
    heldFor(runtime).observer.answer('granted');
  };
  /* Pause model calls is drawn whenever readings are on: inside the notice while one is shown, and beside
     Summarize otherwise, so the off switch never depends on a notice the next read could replace. */
  const offButton = (
    <Button
      ref={offRef}
      type="button"
      data-next-observer-action="off"
      data-next-focus="observer:off"
      disabled={offPending}
      onClick={() => void turnOff()}
    >
      {offPending
        ? off
          ? 'Resuming…'
          : 'Pausing…'
        : off
          ? 'Resume model calls'
          : 'Pause model calls'}
    </Button>
  );
  const shownNotice = notice && !off ? notice : null;
  const request = declined ? (
    <Button
      size="consent"
      ref={requestRef}
      type="button"
      data-next-observer-action="on"
      data-next-focus="observer:request"
      onClick={turnOn}
    >
      Turn on summaries
    </Button>
  ) : (
    <Button
      size="consent"
      ref={requestRef}
      type="button"
      data-next-observer-action="request"
      data-next-focus="observer:request"
      disabled={pending || offPending}
      onClick={summarize}
    >
      {pending ? 'Request in progress' : 'Summarize this session'}
    </Button>
  );
  const actions = (
    <>
      {off ? null : request}
      {shownNotice ? null : (
        <>
          {offButton}
          <p>{MODEL_PAUSE_EXPLANATION}</p>
        </>
      )}
    </>
  );
  const status = off
    ? READINGS_OFF_CONSOLE
    : declined
      ? SUMMARIES_DECLINED
      : pending
        ? 'The requested model summary is in progress.'
        : state === 'error'
          ? 'The summary request failed. Local analysis remains available.'
          : state === 'ready'
            ? 'The refresh returned. Model failures fall back to local analysis.'
            : 'Use Summarize this session for each model request.';
  const observed = (Array.isArray(entry?.data?.observers) ? entry.data.observers : []).find(
    (row) => row.harness === identity.harness && row.sid === identity.sid,
  );
  const goal = observed ? String(observed.goal || '').trim() : '';
  const modelStatus = observed?.model?.status;
  return (
    <Card
      as="section"
      variant="observer-controls"
      className="next-usage-consent"
      data-next-observer-controls=""
      aria-label="Observer model disclosure"
    >
      <p>{disclosure}</p>
      <p>Credential redaction does not remove private prose.</p>
      <div className="next-usage-consent-actions">{actions}</div>
      {shownNotice ? (
        <ModelNotice
          notice={{ ...shownNotice }}
          provider={noticeLabel({ ...shownNotice })}
          parts={[disclosure]}
        >
          {offButton}
          <p>{MODEL_PAUSE_EXPLANATION}</p>
        </ModelNotice>
      ) : null}
      <Alert as="p" variant="observer-status">
        {status}
      </Alert>
      {refused === null ? null : (
        <Alert as="p" variant="observer-status" data-next-observer-refused="">
          {refused}
        </Alert>
      )}
      {state === 'ready' ? (
        goal ? (
          <>
            <p>
              Observed goal: <span className="next-cockpit-source">{goal}</span>
            </p>
            {modelStatus ? (
              <p>
                Model status: <code>{modelStatus}</code>
              </p>
            ) : (
              <p>Model status was not published.</p>
            )}
          </>
        ) : (
          <p>No goal summary was published by this refresh.</p>
        )
      ) : null}
    </Card>
  );
}

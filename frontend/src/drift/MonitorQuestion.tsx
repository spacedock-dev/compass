import { useEffect, useRef, useState } from 'react';
import { compatSessKey } from '../api/identity';
import { identityOf } from '../intent/context';
import { liveMonitorFor, monitorKey, useLiveMonitor, useMonitorEntry } from '../intent/liveMonitor';
import type { Row } from '../observed';
import { useShell } from '../shell/context';
import { Alert } from '../ui/alert';
import { Button } from '../ui/button';
import { answerMinutes, countdown, countdownWords, parseLease, serverNow } from './monitor';
import { useFocusKey } from '../controls';

/* "Do you still want to monitor this session?" The server holds the clock: it publishes `confirm_by` from 20
   minutes after the monitor started, or after the last Yes, until 10 minutes later, and the page counts down to
   that time on the clock it holds. Yes posts `confirm: yes`, which resets the server's clock; No posts
   `confirm: no`, which turns the monitor off. With no answer the monitor turns off, with a note saying why, so a
   tab left open does not keep spending. An answer from any tab clears the question in every tab, because the
   next state the server publishes carries no `confirm_by`
   ([DEC-26](../../../docs/design-reading-a-session.md#amended-2026-10-23-owner-the-live-level-comes-from-a-haiku-check)).

   Announced through the cue live region when it opens, and drawn as ordinary buttons in the tab order: it
   steals no focus, so a reader mid-edit is told and not interrupted. */
export function MonitorQuestion({
  session,
  payload,
}: {
  readonly session: Row;
  readonly payload: Row;
}) {
  const shell = useShell();
  const store = liveMonitorFor(shell);
  const view = useLiveMonitor(session, payload);
  const entry = useMonitorEntry(session);
  const key = monitorKey(session);
  const lease = entry.lease;
  const open = view.on && lease !== null && lease.on && lease.confirmBy !== null;
  const [, setTick] = useState(0);
  const [answering, setAnswering] = useState(false);
  const yes = useFocusKey<HTMLButtonElement>(shell.controls.focusLane, `live-monitor-yes:${key}`);
  const no = useFocusKey<HTMLButtonElement>(shell.controls.focusLane, `live-monitor-no:${key}`);
  const answered = useRef(false);

  // The countdown moves each second while the question stands, on the page's own clock, which render reads.
  useEffect(() => {
    if (!open) return undefined;
    const timer = shell.clock.setInterval(() => setTick((n) => n + 1), 1000);
    return () => shell.clock.clearInterval(timer);
  }, [shell, open]);

  const left =
    open && lease && lease.confirmBy !== null
      ? lease.confirmBy - serverNow(lease, entry.observedAt, shell.clock.now())
      : null;
  const deadline = left !== null && left <= 0;

  /* The deadline passed with no answer. This tab does not end the monitor itself: it beats once and acts on
     what the server says, so another tab's Yes, which the server holds, is not undone here. The server ends it
     at the same moment, so the answer is normally that it has. A tab that cannot reach the server ends it
     locally, because a monitor nobody can confirm should not go on spending. */
  const beatFor = useRef<number | null>(null);
  const deadlineOf = lease?.confirmBy ?? null;
  useEffect(() => {
    if (!deadline || deadlineOf === null || beatFor.current === deadlineOf) return;
    beatFor.current = deadlineOf;
    const identity = identityOf(session);
    if (!identity) return;
    void shell.runtime.client
      .postLiveMonitor({
        harness: identity.harness,
        sid: identity.sid,
        action: 'beat',
        tab_id: shell.env.tabId,
        visible: !shell.env.isHidden(),
      })
      .then((result) => {
        const next = result.kind === 'ok' ? parseLease(result.body.state) : null;
        if (next) store.observe(key, next);
        if (result.kind !== 'ok' || !result.body.ok) {
          store.end(key, next?.lastEnd?.reason ?? 'unanswered', {
            answerMinutes: answerMinutes(next ?? lease),
          });
        }
      });
  }, [deadline, deadlineOf, shell, session, store, key, lease]);

  // Said once for each question the server opens, which its `confirm_by` names; a refreshed state does not say it again.
  const asked = open && left !== null && left > 0 ? (lease?.confirmBy ?? null) : null;
  const said = useRef<number | null>(null);
  useEffect(() => {
    if (asked === null) {
      said.current = null;
      return;
    }
    if (said.current === asked || lease === null) return;
    said.current = asked;
    const remaining = asked - serverNow(lease, entry.observedAt, shell.clock.now());
    shell.announcer.announce(
      `live-monitor-question:${compatSessKey(session)}:${String(asked)}`,
      `Do you still want to monitor this session? Live monitor turns off in ${countdownWords(remaining)} unless you answer.`,
    );
  }, [shell, session, asked, lease, entry.observedAt]);

  /* After an answer the question closes under the button that had focus, and focus goes to the switch it is
     about; where the settings holding the switch are closed, to the control that opens them. */
  const shown = left !== null && left > 0;
  useEffect(() => {
    if (shown || !answered.current) return;
    answered.current = false;
    const lane = shell.controls.focusLane;
    lane.focus(`live-monitor:${compatSessKey(session)}`);
    if (!document.activeElement || document.activeElement === document.body)
      lane.focus(`drift-settings:${compatSessKey(session)}`);
  }, [shown, shell, session]);

  if (left === null || left <= 0) return null;
  const answer = async (yesNo: 'yes' | 'no') => {
    if (answering) return;
    setAnswering(true);
    answered.current = true;
    const identity = {
      harness: String(session['harness'] ?? ''),
      sid: String(session['sid'] ?? ''),
    };
    const result = await shell.runtime.client.postLiveMonitor({
      ...identity,
      action: 'confirm',
      tab_id: shell.env.tabId,
      answer: yesNo,
    });
    setAnswering(false);
    if (result.kind !== 'ok') return;
    const next = parseLease(result.body.state);
    if (next) store.observe(key, next);
    if (!result.body.ok || (next && !next.on)) {
      store.end(key, next?.lastEnd?.reason ?? (yesNo === 'no' ? 'declined' : 'unanswered'), {
        answerMinutes: answerMinutes(next ?? lease),
      });
    }
  };
  return (
    <Alert
      variant="shell-notice"
      role="region"
      aria-label="Live monitor question"
      className="sticky top-0 z-20 mx-4 my-2"
      data-next-live-question
    >
      <strong>Do you still want to monitor this session?</strong>
      <span
        data-next-live-countdown
      >{`Live monitor turns off in ${countdown(left)} unless you answer.`}</span>
      <Button
        variant="retry"
        ref={yes}
        type="button"
        aria-disabled={answering || undefined}
        onClick={() => void answer('yes')}
      >
        Yes
      </Button>
      <Button
        variant="retry"
        ref={no}
        type="button"
        aria-disabled={answering || undefined}
        onClick={() => void answer('no')}
      >
        No
      </Button>
    </Alert>
  );
}

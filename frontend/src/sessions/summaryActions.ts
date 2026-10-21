import { compatSessKey } from '../api/identity';
import { parseGrant, parseJob, parseLargestRead } from '../api/summary';
import type { ApiResult, SessionIdentity, SummaryReceipt } from '../api/types';
import { noticeAnnouncement } from '../drift/notice';
import { clock } from '../observed';
import type { Shell } from '../shell/context';
import { DISCARD_DWELL_MS } from '../intent/sentences';
import {
  DELETE_LAPSE_SECONDS,
  SUMMARY_CANCEL_FAILED,
  SUMMARY_FAILED_SEND,
  summaryDeleted,
} from './summary';
import { summaryHeldFor } from './summaryHeld';

/* The summary's presses. Each sends one request, keeps what the answer says in the tab's held store, and asks
   for the next board; the summary, its job and the grant are drawn from what the server publishes, never from
   the press. None moves focus: a summary that lands while the reader is typing elsewhere leaves the caret
   where it is, and a press keeps focus on the control the reader pressed through the pending lane's busy
   state. */

type Body = Readonly<Record<string, unknown>> | null;

function bodyOf(result: ApiResult<SummaryReceipt>): { status: number; body: Body } | null {
  if (result.kind === 'ok') return { status: result.status, body: result.body };
  if (result.kind === 'http-error')
    return {
      status: result.status,
      body:
        result.body && typeof result.body === 'object' && !Array.isArray(result.body)
          ? (result.body as Body)
          : null,
    };
  return null;
}

function generatedOf(shell: Shell): number {
  const value = shell.runtime.store.getSnapshot().data?.generated;
  return typeof value === 'number' ? value : 0;
}

/* Summarize, Update summary, Summarize again, or the open of a finished session. */
export async function startSummary(
  shell: Shell,
  identity: SessionIdentity,
  action: 'start' | 'update' | 'rerun',
  origin: 'press' | 'open',
): Promise<void> {
  const key = compatSessKey(identity);
  const held = summaryHeldFor(shell.runtime);
  const control = `summary:${key}`;
  /* An open is posted at most once per session per page load, whatever else is in flight: marked before
     anything is sent, so a second render, a remount or StrictMode's second effect sends nothing. */
  if (origin === 'open') {
    if (held.get(key).opened) return;
    held.patch(key, { opened: true, opening: true });
  }
  const token = shell.runtime.pending.start(control, 'Starting…');
  if (!token) {
    if (origin === 'open') held.patch(key, { opening: false });
    return;
  }
  held.patch(key, { refusal: null, failed: '', deletedAt: 0 });
  try {
    const answer = bodyOf(await shell.runtime.client.postSummary({ ...identity, action, origin }));
    /* A lost reply may still have been admitted and charged, so the card asks the board rather than saying
       nothing changed. */
    if (!answer) {
      held.patch(key, { failed: SUMMARY_FAILED_SEND });
      await shell.runtime.refresh();
      return;
    }
    const { status, body } = answer;
    if (status === 202 && body?.['ok'] === true) {
      const job = parseJob(body['job']);
      const notice =
        body['notice'] && typeof body['notice'] === 'object'
          ? (body['notice'] as Record<string, unknown>)
          : null;
      held.patch(key, {
        job,
        jobAt: generatedOf(shell),
        ...(origin === 'press' || notice ? { notice } : {}),
      });
      if (notice) {
        const { key: said, sentence } = noticeAnnouncement(notice);
        shell.announcer.announce(said, sentence);
      }
    } else {
      const reason = String(body?.['reason'] ?? '');
      const grant = parseGrant(body?.['summaries']);
      if (grant) held.setGrant(grant, generatedOf(shell));
      /* An open that found a summary already saved, or a job already running, refuses nothing the reader
         asked for: the next board draws what is there. */
      held.patch(key, {
        refusal:
          origin === 'open' && (reason === 'summary-exists' || reason === 'in-flight')
            ? null
            : { reason: reason || 'job-failed', largest: parseLargestRead(body?.['largest_read']) },
      });
    }
    await shell.runtime.refresh();
  } finally {
    shell.runtime.pending.end(control, token);
    if (origin === 'open') held.patch(key, { opening: false });
  }
}

export async function cancelSummary(shell: Shell, identity: SessionIdentity): Promise<void> {
  const key = compatSessKey(identity);
  const held = summaryHeldFor(shell.runtime);
  const control = `summary-cancel:${key}`;
  const token = shell.runtime.pending.start(control, 'Cancelling…', 'Cancelling the summary.');
  if (!token) return;
  held.patch(key, { failed: '' });
  try {
    const answer = bodyOf(await shell.runtime.client.postSummaryCancel(identity));
    if (!answer || (answer.status !== 202 && answer.status !== 409)) {
      held.patch(key, { failed: SUMMARY_CANCEL_FAILED });
      return;
    }
    await shell.runtime.refresh();
  } finally {
    shell.runtime.pending.end(control, token);
  }
}

/* Turn off summaries and Turn summaries on: the one grant, for every session. Off also ends the notice it
   stood beside. */
export async function setSummaries(
  shell: Shell,
  identity: SessionIdentity,
  on: boolean,
): Promise<void> {
  if (shell.runtime.store.getSnapshot().data?.reading?.off === true) return;
  const key = compatSessKey(identity);
  const held = summaryHeldFor(shell.runtime);
  const control = `summary-grant:${key}`;
  const token = shell.runtime.pending.start(
    control,
    on ? 'Turning on…' : 'Turning off…',
    on ? 'Turning summaries on.' : 'Turning summaries off.',
  );
  if (!token) return;
  held.patch(key, { failed: '', refusal: null });
  try {
    const answer = bodyOf(await shell.runtime.client.postSummary({ consent: on ? 'on' : 'off' }));
    const grant = parseGrant(answer?.body?.['summaries']);
    if (!answer || answer.body?.['ok'] !== true || !grant) {
      if (grant) held.setGrant(grant, generatedOf(shell));
      held.patch(key, {
        failed: on
          ? 'Could not confirm summaries are on. Try turning them on again.'
          : 'Could not confirm summaries are off. Try turning them off again.',
      });
      return;
    }
    held.setGrant(grant, generatedOf(shell));
    if (!on) held.clearNotices();
    await shell.runtime.refresh();
  } finally {
    shell.runtime.pending.end(control, token);
  }
}

/* Delete summary is two presses, as Discard everything is: the first arms it and says what will go and what
   will not, the second performs it. A press inside the dwell after the arm, and a double click, are another
   arm and never the deletion, for the reason the discard's dwell gives. The arm lapses on its own after
   `DELETE_LAPSE_SECONDS`, so a reader who walked away returns to a control that is not armed. */
const lapseKey = (key: string) => `summary-delete:${key}`;

export function pressDeleteSummary(
  shell: Shell,
  identity: SessionIdentity,
  detail: number,
  armedSentence: string,
): void {
  const key = compatSessKey(identity);
  const held = summaryHeldFor(shell.runtime);
  const armedAt = held.get(key).deleteArmedAt;
  const slip = detail > 1 || shell.clock.now() - armedAt < DISCARD_DWELL_MS;
  if (armedAt === 0 || slip) {
    const at = shell.clock.now();
    held.patch(key, { deleteArmedAt: at });
    shell.announcer.announce(lapseKey(key), armedSentence, { assertive: true });
    shell.clock.setTimeout(() => {
      if (held.get(key).deleteArmedAt !== at) return;
      held.patch(key, { deleteArmedAt: 0 });
      shell.announcer.retractArmed(lapseKey(key));
      shell.announcer.forget(lapseKey(key));
    }, DELETE_LAPSE_SECONDS * 1000);
    return;
  }
  void deleteSummary(shell, identity);
}

/* Keep summary, and Escape on the armed control: the arm is dropped on purpose, so the next one is a fresh offer. */
export function disarmDeleteSummary(shell: Shell, identity: SessionIdentity): boolean {
  const key = compatSessKey(identity);
  const held = summaryHeldFor(shell.runtime);
  if (held.get(key).deleteArmedAt === 0) return false;
  held.patch(key, { deleteArmedAt: 0 });
  shell.announcer.retractArmed(lapseKey(key));
  shell.announcer.forget(lapseKey(key));
  return true;
}

/* Delete summary: removes the saved summary and stops a job on it. The session is not summarized again on
   this open: the reader removed what was there. The deletion is said with its time, because the card returns
   to its first-visit state and would otherwise read as though no summary had ever been there. */
export async function deleteSummary(shell: Shell, identity: SessionIdentity): Promise<void> {
  const key = compatSessKey(identity);
  const held = summaryHeldFor(shell.runtime);
  const control = `summary-delete:${key}`;
  const token = shell.runtime.pending.start(control, 'Deleting…', 'Deleting the summary.');
  if (!token) return;
  held.patch(key, { failed: '', refusal: null, opened: true, job: null });
  try {
    const answer = bodyOf(await shell.runtime.client.postSummaryDelete(identity));
    const outcome = String(answer?.body?.['outcome'] ?? '');
    shell.announcer.retractArmed(lapseKey(key));
    if (outcome !== 'deleted' && outcome !== 'absent') {
      held.patch(key, {
        failed: 'Compass could not delete the summary. Try again.',
        deleteArmedAt: 0,
      });
      return;
    }
    const at = shell.clock.now();
    held.patch(key, { deleteArmedAt: 0, deletedAt: at });
    shell.announcer.announce(lapseKey(key), summaryDeleted(clock(at / 1000)));
    await shell.runtime.refresh();
  } finally {
    shell.runtime.pending.end(control, token);
  }
}

import { nextNumber } from '../api/bootstrap';
import { longJobProgress, longCleanupUnresolved } from '../api/longProgress';
import { sessionLongDiagnostic, longOutcomeSentence, hasBoundLongReading } from './longOutcome';
import { compatSessKey } from '../api/identity';
import { annotationOf } from '../intent/annotation';
import { announce } from '../intent/context';
import { isRecord, type Row } from '../observed';
import { REGION_IDS } from '../shell/announcer';
import { JOB_TITLE, READING_FINISHED, LONG_STAGE, LONG_CLEANUP_UNRESOLVED } from './sentences';
import type { DriftCtx, JobSeen } from './state';

/* How an analysis ended, said once. A withheld, cancelled or interrupted end is the server's own
   `reading_withheld` sentence; a stored reading is this one. No positional word, so it is true at every
   width: the result stands in the Drift card, in the button's place. */
function outcome(payload: Row, key: string, readingAtSeen: string): string {
  const sessions = Array.isArray(payload['sessions']) ? (payload['sessions'] as Row[]) : [];
  const row = sessions.find((session) => compatSessKey(session) === key);
  const annotation = row ? annotationOf(row) : null;
  const withheld = String(annotation?.['reading_withheld'] || '');
  if (withheld) return withheld;
  const reading = JSON.stringify(annotation?.['assessment'] || null);
  return reading !== 'null' && reading !== readingAtSeen ? READING_FINISHED : '';
}

function sessionOf(payload: Row, key: string): Row {
  const sessions = Array.isArray(payload['sessions']) ? (payload['sessions'] as Row[]) : [];
  return sessions.find((session) => compatSessKey(session) === key) ?? {};
}

function longEnd(payload: Row, key: string, seen: JobSeen): { sentence: string; stored: boolean } {
  const row = sessionOf(payload, key),
    watched = seen.long;
  const none = { sentence: '', stored: false };
  if (!watched || watched.startedAt === null) return none;
  const diagnostic = sessionLongDiagnostic(row);
  if (diagnostic?.binding && diagnostic.binding.job_started_at > watched.startedAt) return none;
  const withheld = JSON.stringify([
    row['annotation_reading_withheld'],
    row['annotation_reading_withheld_at'],
  ]);
  const at = nextNumber(row['annotation_reading_withheld_at']);
  if (
    withheld !== watched.withheld &&
    at !== null &&
    at >= watched.startedAt &&
    typeof row['annotation_reading_withheld'] === 'string' &&
    row['annotation_reading_withheld']
  ) {
    return { sentence: row['annotation_reading_withheld'], stored: false };
  }
  if (
    !diagnostic ||
    diagnostic.binding?.job_started_at !== watched.startedAt ||
    JSON.stringify(sessionLongDiagnostic(row)) === watched.diagnostic ||
    diagnostic.outcome === 'pending'
  )
    return none;
  const saved = ['completed', 'partial'].includes(diagnostic.outcome);
  if (saved && (readingOf(payload, key) === seen.reading || !hasBoundLongReading(row, diagnostic)))
    return none;
  return { sentence: longOutcomeSentence(diagnostic), stored: saved };
}

function readingOf(payload: Row, key: string): string {
  const sessions = Array.isArray(payload['sessions']) ? (payload['sessions'] as Row[]) : [];
  const row = sessions.find((session) => compatSessKey(session) === key);
  const annotation = row ? annotationOf(row) : null;
  return JSON.stringify(annotation?.['assessment'] || null);
}

/* "Analyzing drift" is said when a job this tab had not seen is first drawn, and the outcome when a job whose
   box was drawn leaves `reading_jobs`, so a redraw, a phase revision or a reload says nothing again. The
   first pass only records what is already running: a reload pressed nothing. Run after the card commits, and
   never from a render: a region and its first message must not arrive in the same mutation.

   `drawn` is the ids of the boxes the committed card drew. A job first seen undrawn never announces its
   start, even if its box is drawn later: the reader did not watch it begin.

   Returns the sessions whose watched analysis just stored a reading, so the card can ask for the older
   record pages that reading cites. A withheld, cancelled or interrupted end stored none and is not one. */
export function trackJobs(ctx: DriftCtx, payload: Row, drawn: ReadonlySet<string>): string[] {
  const finished: string[] = [];
  const { drift } = ctx;
  const rawJobs = payload['reading_jobs'];
  const jobs: Record<string, unknown> = isRecord(rawJobs) ? rawJobs : {};
  const primed = drift.isPrimed();
  drift.prime();
  /* Emptying a region is silent, so a stale "Analyzing drift" is taken back without a second announcement. */
  const clearTitle = () => {
    const region = typeof document === 'undefined' ? null : document.getElementById(REGION_IDS.cue);
    if (
      region &&
      [JOB_TITLE, LONG_CLEANUP_UNRESOLVED, ...Object.values(LONG_STAGE)].includes(
        region.textContent ?? '',
      )
    )
      region.textContent = '';
  };
  const say = (key: string, sentence: string) => {
    /* A region already holding the sentence is a write the reader's software does not read again, so the
       guard goes first: the same sentence for a new job is a new event. */
    ctx.shell.announcer.forget(key);
    announce(ctx.intent, key, sentence);
  };
  for (const [key, seen] of [...drift.jobsSeen]) {
    const job = jobs[key];
    if (isRecord(job) && String(job['id']) === seen.id) continue;
    drift.jobsSeen.delete(key);
    const ended = seen.drawn && seen.long ? longEnd(payload, key, seen) : null;
    const said = seen.drawn
      ? seen.long
        ? (ended?.sentence ?? '')
        : outcome(payload, key, seen.reading)
      : '';
    if (said) {
      say(`job:${seen.id}`, said);
      if (said === READING_FINISHED || ended?.stored) finished.push(key);
    } else {
      /* Ended unannounced: a virtual cursor must not still find "Analyzing drift" in the region, and the
         next start must not set that same text again, which is not read. */
      ctx.shell.announcer.forget(`job:${seen.id}`);
      clearTitle();
    }
  }
  for (const [key, job] of Object.entries(jobs)) {
    if (!isRecord(job) || typeof job['id'] !== 'string') continue;
    const seen = drift.jobsSeen.get(key);
    const isDrawn = drawn.has(job['id']);
    if (seen) {
      const progress = seen.long ? longJobProgress(job) : null;
      if (seen.long && longCleanupUnresolved(job) && !seen.long.blocked) {
        if (seen.drawn && isDrawn) say(`job:${seen.id}:blocked`, LONG_CLEANUP_UNRESOLVED);
        seen.long.blocked = true;
      }
      if (seen.long && progress && !seen.long.blocked) {
        const order = Object.keys(LONG_STAGE);
        if (order.indexOf(progress.stage) > order.indexOf(seen.long.stage ?? '')) {
          if (seen.drawn && isDrawn && seen.long.stage !== null)
            say(`job:${seen.id}:stage`, LONG_STAGE[progress.stage]);
          seen.long.stage = progress.stage;
        }
      }
      seen.drawn = isDrawn;
      continue;
    }
    const row = sessionOf(payload, key);
    drift.jobsSeen.set(key, {
      id: job['id'],
      drawn: isDrawn,
      reading: readingOf(payload, key),
      ...(job['mode'] === 'long'
        ? {
            long: {
              startedAt: nextNumber(job['started_at']),
              stage: longJobProgress(job)?.stage ?? null,
              blocked: longCleanupUnresolved(job),
              diagnostic: JSON.stringify(sessionLongDiagnostic(row)),
              withheld: JSON.stringify([
                row['annotation_reading_withheld'],
                row['annotation_reading_withheld_at'],
              ]),
            },
          }
        : {}),
    });
    if (primed && isDrawn)
      say(`job:${job['id']}`, longCleanupUnresolved(job) ? LONG_CLEANUP_UNRESOLVED : JOB_TITLE);
  }
  return finished;
}

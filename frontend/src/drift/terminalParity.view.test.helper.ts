/* What the Drift card would hold for a session on a fresh load, derived by the PAGE and projected onto closed
   tokens, numbers and the reader's own words. Both the parity check and the recorded-server check read it, so
   the two ask the page one question. */
import { nextNumber } from '../api/bootstrap';
import { contextKey } from '../api/identity';
import { createHeld } from '../intent/held';
import type { Row } from '../observed';
import { createAnnouncer } from '../shell/announcer';
import { createFakeClock } from '../transport/testing';
import { analysisRow, workObject } from './level';
import { conflictCandidates } from '../intent/work';
import { buildModel } from './model';
import { monitorLevel, parseLease } from './monitor';
import { resultStale, resultState } from './result';
import {
  ASSISTANT_ONLY,
  BASELINE_OPEN,
  BLOCKER_LINES,
  GOAL_NOT_SHOWN,
  CHECK_DOES_NOT_SHOW_IT,
  CHECK_READ_INCOMPLETE,
  CLAIM_UNCITED,
  DERIVED_ONLY,
  FAILED_CHECK_ON_RECORD,
  FAILED_CHECK_UNREAD,
  MALFORMED,
  OWN_WORDS_ONLY,
  REASON_LINES,
  STORED_WHY,
  UNCITED,
} from './sentences';
import type { DriftCase } from './terminalParity.corpus.test.helper';

/* The page words a row's reason in sentences; the port says it as the closed token the producer stores, so a
   sentence is mapped to its token here and an unfamiliar one fails the write rather than leaking through. */
const WHY = new Map<string, string>([
  [BASELINE_OPEN, 'baseline-open'],
  [MALFORMED, 'malformed'],
  [UNCITED, 'uncited'],
  [CHECK_DOES_NOT_SHOW_IT, 'check-does-not-show-it'],
  [CHECK_READ_INCOMPLETE, 'check-read-incomplete'],
  [CLAIM_UNCITED, 'claim-uncited'],
  [DERIVED_ONLY, 'board-quoting-itself'],
  [ASSISTANT_ONLY, 'no-work-shown'],
  [OWN_WORDS_ONLY, 'uncorroborated'],
  [FAILED_CHECK_ON_RECORD, 'failed-check-on-record'],
  [FAILED_CHECK_UNREAD, 'failed-check-unread'],
]);
for (const [token, sentence] of Object.entries(STORED_WHY)) {
  if (!WHY.has(sentence)) WHY.set(sentence, token);
}

function whyToken(sentence: string): string {
  if (!sentence) return '';
  const token = WHY.get(sentence);
  if (token === undefined) throw new Error(`no token for the reason: ${sentence}`);
  return token;
}

function limitToken(sentence: string): string {
  if (!sentence) return '';
  return sentence === STORED_WHY['not-asked'] ? 'not-asked' : 'route';
}

/* The tokens an analysis level is explained from: the server's, and the one the page adds where it withholds
   a level the server drew. The page says the added one as a blocker sentence, so the sentence is the evidence. */
function analysisReasons(served: Row | null, blockers: readonly string[]): string[] {
  const tokens = Array.isArray(served?.['reasons'])
    ? (served['reasons'] as unknown[]).map(String)
    : [];
  for (const added of ['line-not-shown-by-a-check', 'claim-not-shown']) {
    const sentence = BLOCKER_LINES[added] ?? REASON_LINES[added]?.('');
    /* A reading of the goal alone says the first as "Your goal is not shown by any check." */
    const said =
      (sentence && blockers.includes(sentence)) ||
      (added === 'line-not-shown-by-a-check' && blockers.includes(GOAL_NOT_SHOWN));
    if (said && !tokens.includes(added)) tokens.push(added);
  }
  return [...new Set(tokens)];
}

/* What the Drift card would hold for the case's session on a fresh load, projected onto closed tokens, numbers
   and the reader's own words. Nothing here is a sentence of the page's. */
export function pageView(item: DriftCase): unknown {
  const session = item.session as Row;
  const payload = item.payload as Row;
  const contexts = new Map([
    [contextKey('p', session as never), { data: item.context as never, revision: 1, error: null }],
  ]);
  /* The monitor counts as on exactly while the server's lease stands: a terminal has no tab to hold the
     switch, so the lease is the definition. */
  const lease = parseLease(workObject(contexts, 'p', session, 'live_monitor'));
  const liveOn = lease?.on === true;
  const model = buildModel({
    session,
    payload,
    base: payload,
    project: 'p',
    projectKey: 'p',
    contexts,
    held: createHeld({ clock: createFakeClock(), announcer: createAnnouncer() }),
    liveOn,
    monitor: liveOn && lease ? monitorLevel(lease) : null,
  });
  const numbers = (ids: readonly string[]): string[] => ids.map((id) => model.labels.get(id) ?? '');
  const shape = model.shape;
  const stale =
    model.annotate && shape && !shape.malformed && model.raw && model.annotation
      ? resultStale(shape, model.raw, model.annotation, model.entries)
      : null;
  const served = analysisRow(contexts, 'p', session);
  const reasons = analysisReasons(served, model.analysis?.reasons.blockers ?? []);
  const revision = nextNumber(model.annotation?.['revision']);
  const view = {
    live_on: model.liveOn,
    revision,
    analysis: model.analysis
      ? {
          level: model.analysis.level,
          reasons,
          withheld: model.analysis.level !== String(served?.['level'] ?? ''),
        }
      : null,
    estimate: model.estimate
      ? 'save' in model.estimate
        ? { save: true }
        : { level: model.estimate.level, source: model.estimate.monitor ? 'monitor' : 'live' }
      : null,
    pill: model.pill
      ? {
          level: model.pill.level,
          source: model.pill.analysis ? 'analysis' : model.pill.monitor ? 'monitor' : 'live',
          so_far: model.pillSoFar,
        }
      : null,
    stale: stale ? { kind: stale.kind, before: stale.before } : null,
    harness: model.harness,
    sid: String(session['sid']),
    annotate: model.annotate,
    reading: shape !== null,
    malformed: shape?.malformed ?? '',
    unsettled: model.unsettled,
    /* The messages the direction question lists: the same open set that demotes, counted. */
    unsettled_count: model.annotate
      ? conflictCandidates(model.annotation, model.entries, session, model.draft).length
      : 0,
    drafted: model.drafted,
    limited: model.limit !== '',
    entry_count: model.entryCount,
    window_count: model.windowCount,
    lines: (shape?.criteria ?? []).map((row) => ({
      key: row.key,
      state: resultState(row),
      result: row.result,
      why: whyToken(row.why),
      rests_on: row.restsOn,
      limit: limitToken(row.limit),
      clause: row.clauseKnown ? row.clause : '',
      detail: row.detail,
      cites: [...row.citedIds],
      numbers: numbers(row.citedIds),
      unloaded: row.unloaded,
      partial: Boolean(row.coverage),
    })),
    departures: (shape?.departures ?? []).map((row) => row.key),
    cited: [...model.cited].sort(),
    priors: model.priors.map((prior) => ({
      key: prior.key,
      read_at: prior.readAt,
      answer: prior.answer,
      cites: [...prior.cites],
      numbers: numbers(prior.cites),
      clause: prior.row.clause,
      detail: prior.row.detail,
    })),
  };
  return JSON.parse(JSON.stringify(view)) as unknown;
}

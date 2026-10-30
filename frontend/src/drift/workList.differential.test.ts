// @vitest-environment jsdom
import { describe, expect, it } from 'vitest';
import { compatSessKey } from '../api/identity';
import { annotationOf } from '../intent/annotation';
import { intentDraft } from '../intent/derive';
import { createHeld } from '../intent/held';
import { createAnnouncer } from '../shell/announcer';
import { createFakeClock } from '../transport/testing';
import { genSession } from '../intent/generate.test.helper';
import { baselineAt, workSource, type WorkSource } from '../intent/work';
import type { ContextEntry } from '../store/board';
import { genEntries, mulberry32, pick, type Rng } from './generate.test.helper';
import { loadLegacyDrift } from './legacy.test.helper';
import { WORK_READ_FROM } from './sentences';
import { workList } from './workList';
import { harnessLabels } from '../sessions/rows';
import { recordedActivityActor } from '../../test/recorded-activity';
import { projectRecordedLoadedActivity } from '../../test/recorded-loaded-activity';

/* The numbered activity list, run next to the legacy page's over generated records: which entries it draws,
   at which numbers, with which flags, and every sentence about what it left out. Compared as the words a
   reader reads, in order. */
const legacy = loadLegacyDrift();
legacy.lift([
  'NEXT_READING_DEPARTURE',
  'NEXT_READING_CONSISTENT',
  'NEXT_READING_UNVERIFIABLE',
  'NEXT_READING_UNSUPPORTED',
  'NEXT_READING_NOT_REACHED',
  'NEXT_READING_RESULTS',
  'NEXT_READING_CRITERION_KEYS',
  'nextReadingCopied',
  'nextReadingAuthor',
  'NEXT_COCKPIT_WORK_ROWS',
  'NEXT_COCKPIT_AGENT_ROWS',
  'NEXT_COCKPIT_WORK_READ_FROM',
  'NEXT_COCKPIT_WORK_AS_REPORTED',
  'NEXT_COCKPIT_ENTRY_KIND',
  'NEXT_COCKPIT_CHECK_RESULTS',
  'NEXT_READING_ROUTE_UNREAD',
  'NEXT_READING_TURN_STOP_HARNESSES',
  'nextCockpitHumanLabel',
  'nextCockpitToolReportLine',
  'nextCockpitCheckScan',
  'nextCockpitLastTurn',
  'nextCockpitEntryActor',
  'nextCockpitEntryCount',
  'nextCockpitJoinClauses',
  'nextCockpitUnlistedClause',
  'nextReadingRoute',
  'nextCockpitWorkEvidenceLimit',
  'nextCockpitWorkEvidenceOwn',
  'nextCockpitWorkMix',
  'nextCockpitWorkFooter',
  'nextCockpitWorkEvidence',
]);
legacy.lift(['nextSessionStop'], 'next-observed.js');
legacy.lift(['nextHarnessLabels'], 'next-boot.js');

/* Two departures from the recording since 2026-10-30, when Codex's record began to list checks
   (docs/design-frontend-migration.md#held-to-recorded-answers). The sentence naming the harnesses Compass reads
   work from now names Codex, so the recorded one is read as the new one; and a Codex session's list now carries
   its record line under "About this record" as Claude Code's does, so on Codex this page's list is compared in the
   shape the retired page drew, with its "publishes no demonstrated work results" line, and every row, number,
   flag and count is still held to the recording. The new Codex line is held by the Drift stories. */
const RECORDED_READ_FROM = 'Compass reads work results from Claude Code and Pi only.';
function asRecorded(list: ReturnType<typeof workList>, harness: string, payload: unknown) {
  if (harness !== 'codex') return list;
  const label = harnessLabels(payload as never).get('codex') || 'Codex';
  return {
    ...list,
    reads: false,
    limit: `${WORK_READ_FROM} ${label} publishes no demonstrated work results, so nothing above is an inspected file, test or deliverable.`,
  };
}

const CASES = 80;
const SEEDS = CASES;
const squash = (value: string): string => value.replace(/\s+/g, '');
const text = (html: string): string => {
  const node = document.createElement('div');
  node.innerHTML = html;
  recordedActivityActor(node);
  // The row's hidden source line is read out, so it is part of the words.
  return squash(node.textContent ?? '');
};

function assemble(list: ReturnType<typeof workList>, disclosed: boolean): string {
  const out: string[] = [list.anchor, list.unnumbered];
  for (const row of list.rows) {
    out.push(row.n === null ? 'not numbered' : `#${String(row.n)}`);
    out.push('report' in row.head ? row.head.report : `${row.head.actor}${row.head.type}`);
    if (row.flags.includes('later')) out.push('A later direction you gave');
    if (row.flags.includes('cited')) out.push('Cited');
    out.push(row.entry.summary, row.source, row.at);
    if (row.turn) out.push('from the last turn');
    if (row.add) out.push('Add to my intent');
  }
  if (!list.rows.length && !list.unnumbered) out.push(list.absent);
  out.push(list.reads ? 'Results are as the tool reported; not inspected.' : list.limit);
  if (list.mix || list.unlisted.length || list.checks || list.bound || list.reads) {
    out.push('About this record');
    out.push(list.mix, ...list.unlisted, list.checks, list.bound);
    if (list.reads) out.push(list.limit);
  }
  void disclosed;
  return squash(out.join(''));
}

function genState(rnd: Rng, seed: number) {
  const harness = pick(rnd, ['claude', 'pi', 'codex']);
  const session: Record<string, unknown> = {
    ...genSession(rnd, seed),
    harness,
    sid: 's1',
    project: 'alpha/app',
    first_prompt: 'Fix it',
    first_prompt_at: 100,
    state: pick(rnd, ['idle', 'working']),
    turn_end_at: pick(rnd, [300, undefined]),
    annotation_window_start: pick(rnd, [100, 200, null]),
    annotation_goal: pick(rnd, ['Ship it', '']),
    annotation_at: pick(rnd, [150, 250]),
    annotation_goal_saved_at: pick(rnd, [150, null]),
    annotation_settled_through: pick(rnd, [null, 120]),
  };
  const entries = genEntries(rnd, harness).map((entry, index) => ({
    fact_id: entry.id || `e${String(index)}`,
    type: entry.type,
    by: entry.by,
    summary: entry.summary,
    at: entry.at,
    result_at: entry.resultAt,
    source_session: { harness, sid: 's1' },
    actor_claim: entry.actorClaim,
    subject: entry.subject,
    copied: entry.copied,
    result: entry.result,
    result_source: entry.resultSource,
    earlier_failed: entry.earlierFailed,
    before_last_change: entry.beforeLastChange,
    evidence: { source: entry.source || 'transcript', confidence: 'exact' },
  }));
  // More entries than the bounds, on some seeds, so the sentence about what was left out is reached.
  const many = rnd() < 0.3;
  const facts = many
    ? [
        ...entries,
        ...Array.from({ length: 30 }, (_, index) => ({
          fact_id: `m${String(index)}`,
          type: index % 4 === 0 ? 'agent_message' : 'user_message',
          by: 'person:me',
          summary: `Message ${String(index)}`,
          at: 300 + index,
          source_session: { harness, sid: 's1' },
          evidence: { source: 'transcript', confidence: 'exact' },
        })),
      ]
    : entries;
  const scan = pick(rnd, [
    { harness, sid: 's1', check_runs: 3, distinct_checks: 2, failed: 1, passed: 2, more: 0 },
    { harness, sid: 's1', check_runs: 0, written_paths: 4, other_commands: 2, background: 1 },
    undefined,
  ]);
  const data = {
    semantic: { facts },
    sources: { work: { tool_reports: scan ? [scan] : [], line_requests: [] } },
  };
  const payload = {
    annotate: pick(rnd, [true, true, false]),
    generated: 1000,
    harnesses: [{ key: harness, label: pick(rnd, ['Claude Code', harness]) }],
    reading_routes: pick(rnd, [
      undefined,
      { [harness]: { provider: harness, tool_output: 'Tool output goes to the api.' } },
      { [harness]: { provider: '' } },
    ]),
  };
  return { harness, session, data, payload };
}

describe('the numbered list reads as the legacy page reads it', () => {
  it(`agrees on ${String(SEEDS)} generated records`, () => {
    const failures: string[] = [];
    let drew = 0;
    for (let seed = 1; seed <= SEEDS && failures.length < 3; seed += 1) {
      const rnd = mulberry32(seed + 1234);
      const { session, data, payload } = genState(rnd, seed);
      const group = { label: 'alpha/app', sessions: [session] };
      legacy.setData(payload);
      legacy.run('nextCockpitContexts.clear();');
      const key = legacy.call<string>('nextCockpitContextKey', group, session);
      legacy.run('nextCockpitContexts.set(__key, __entry);', { key, entry: { data, revision: 1 } });
      const contexts = new Map<string, ContextEntry>([
        [key, { data: data as never, revision: 1, error: null }],
      ]);
      const projectKey = legacy.call<string>('nextCockpitStableKey', group);
      const source = workSource(contexts, projectKey, session as never);
      const legacySource = legacy.call<WorkSource>('nextCockpitWorkSource', group, session);
      const entries = source.all || source.entries;
      const cited = new Set(
        entries.filter(() => rnd() < 0.2).map((entry) => String(entry.id || '')),
      );
      const html = legacy.call<string>('nextCockpitWorkEvidence', session, legacySource, cited);
      const annotation = payload.annotate ? annotationOf(session as never) : null;
      const draft = intentDraft({
        held: createHeld({ clock: createFakeClock(), announcer: createAnnouncer() }),
        contexts,
        payload: payload as never,
        session: session as never,
        annotation,
      });
      const mine = workList({
        session: session as never,
        payload: payload as never,
        source,
        annotation,
        draft,
        cited,
        generated: 1000,
      });
      if (mine.rows.length) drew += 1;
      const recorded = text(
        projectRecordedLoadedActivity(
          html,
          legacySource,
          session,
          payload,
          cited,
          baselineAt(annotation, session, draft),
        ),
      );
      const a = recorded.replace(squash(RECORDED_READ_FROM), squash(WORK_READ_FROM));
      const b = assemble(asRecorded(mine, String(session['harness']), payload), false);
      if (a !== b) {
        let at = 0;
        while (a[at] === b[at]) at += 1;
        failures.push(
          `seed ${String(seed)} ${compatSessKey(session as never)}: ${a.slice(Math.max(0, at - 60), at + 100)} || ${b.slice(Math.max(0, at - 60), at + 100)}`,
        );
      }
    }
    expect(failures).toEqual([]);
    expect(drew).toBeGreaterThan(20);
  });
});

// @vitest-environment jsdom
import { describe, expect, it } from 'vitest';
import { compatSessKey } from '../api/identity';
import { annotationOf } from '../intent/annotation';
import { genSession } from '../intent/generate.test.helper';
import { workSource } from '../intent/work';
import { canonical, firstDifference } from '../observed/legacy.test.helper';
import type { ContextEntry } from '../store/board';
import { mulberry32, pick, type Rng } from './generate.test.helper';
import { loadLegacyDrift } from './legacy.test.helper';
import { analysisLevel, liveEstimate, readingStored, type DriftLevel, type Signals } from './level';
import { BLOCKER_LINES, REASON_LINES } from './sentences';
import { readingShape } from './shape';

/* The live estimate and the analysis level, run next to the legacy page's over generated contexts. The two
   levels are different claims with different sources, so each is compared with its own source line. */
const legacy = loadLegacyDrift();
legacy.lift([
  'NEXT_READING_DEPARTURE',
  'NEXT_READING_CONSISTENT',
  'NEXT_READING_UNVERIFIABLE',
  'NEXT_READING_UNSUPPORTED',
  'NEXT_READING_NOT_REACHED',
  'NEXT_READING_RESULTS',
  'NEXT_READING_CRITERION_KEYS',
  'NEXT_READING_ASSISTANT_ONLY',
  'NEXT_READING_UNCITED',
  'NEXT_READING_BASELINE_OPEN',
  'NEXT_READING_CLAUSE_UNRETAINED',
  'NEXT_READING_MALFORMED',
  'NEXT_READING_NOT_ASKED',
  'NEXT_READING_VERDICT_STATED',
  'NEXT_READING_CHECK_DOES_NOT_SHOW_IT',
  'NEXT_READING_CHANGED_AFTER_CHECK',
  'NEXT_READING_CHECK_READ_INCOMPLETE',
  'NEXT_READING_CHECKS_NOT_READ',
  'NEXT_READING_TELLS_THE_PERSON',
  'NEXT_READING_FAILED_CHECK_ON_RECORD',
  'NEXT_READING_FAILED_CHECK_UNREAD',
  'NEXT_READING_CLAIM_RECORD_UNREAD',
  'NEXT_READING_CLAIM_UNCITED',
  'NEXT_READING_DERIVED_ONLY',
  'NEXT_READING_OWN_WORDS_ONLY',
  'NEXT_READING_STORED_WHY',
  'NEXT_READING_PI_CHECK_SOURCE',
  'NEXT_READING_COVERAGE_KEYS',
  'NEXT_READING_COVERAGE_GOALS',
  'nextReadingConstraints',
  'nextReadingCopied',
  'nextReadingAgentMessage',
  'nextReadingDemonstratesWork',
  'nextReadingEvidenceAt',
  'nextReadingBeforeWindow',
  'nextCockpitLineRequests',
  'nextReadingCheckSupports',
  'nextReadingSubjectlessPiCheck',
  'nextReadingAuthor',
  'nextReadingCitations',
  'nextCockpitReadingCriterion',
  'nextCockpitLineLabel',
  'nextCockpitReadingClause',
  'nextReadingCoverage',
  'nextReadingWindowPartial',
  'nextCockpitReadingShape',
  'nextCockpitStableKey',
  'NEXT_LIVE_ESTIMATE_KEY',
  'nextLiveMonitorMemory',
  'NEXT_LIVE_HARNESSES',
  'nextLiveMonitorOn',
  'NEXT_DRIFT_LEVEL_NAMES',
  'NEXT_DRIFT_SCALE',
  'NEXT_DRIFT_REASON_LINES',
  'NEXT_DRIFT_BLOCKER_LINES',
  'nextDriftLiveRow',
  'nextDriftSignalAnchored',
  'nextDriftEstimate',
  'nextDriftAnalysisRow',
  'nextDriftAnalysisShown',
  'nextDriftAnalysis',
  'nextDriftRange',
  'nextDriftLiveTokens',
  'nextDriftRecordedTime',
  'nextDriftRecordedSignals',
  'nextDriftEvidenceRows',
  'nextDriftReasons',
  'nextDriftReadingStored',
  'nextCockpitConflictCandidates',
]);
legacy.lift(['fmtDur'], 'next-cockpit-compat.js');

const CASES = 80;
const SEEDS = CASES;
const squash = (value: string): string => value.replace(/\s+/g, '');
const htmlText = (html: string): string => {
  const node = document.createElement('div');
  node.innerHTML = html;
  return squash(node.textContent ?? '');
};

function signalsText(signals: Signals | null): string {
  if (!signals) return '';
  const parts: string[] = [];
  if (signals.lines.length || signals.evidence.length) {
    parts.push('Recorded signals', ...signals.lines);
    for (const row of signals.evidence) {
      parts.push(
        row.label,
        `${row.kind} · ${row.who}`,
        `${row.eventLabel} ${row.at}`,
        row.result,
        'Source',
        row.source,
      );
    }
  }
  if (signals.limits.length) parts.push('Limits of this estimate', ...signals.limits);
  return squash(parts.join(''));
}

const LEVELS = [
  'none_or_low',
  'medium',
  'high',
  'extreme',
  'not_enough',
  'no_live_level',
  'bogus',
  '',
];
const REASONS = [
  'failed-check',
  'departure',
  'pass-then-write',
  'claim-contradicted',
  'claim-not-shown',
  'writes-outside-folders',
  'most-writes-outside-folders',
  'no-passing-check',
  'check-not-recorded',
  'background-run',
  'later-direction',
  'scan-incomplete',
  'intent-names-no-folder',
  'floor-met',
  'mystery',
];

function genFacts(rnd: Rng, session: Record<string, unknown>) {
  return Array.from({ length: Math.floor(rnd() * 8) }, (_, index) => {
    const type = pick(rnd, ['user_message', 'agent_message', 'tool_report', 'tool_report']);
    return {
      fact_id: `f${String(index)}`,
      type,
      by: pick(rnd, ['person:me', 'agent']),
      summary: pick(rnd, ['pytest', 'A direction', 'src/a.ts']),
      at: pick(rnd, [800, 900, 950, 1010, 0, null]),
      result_at: pick(rnd, [undefined, 960, 1020]),
      subject: type === 'tool_report' ? pick(rnd, ['check', 'check', 'write']) : '',
      result: pick(rnd, ['failed', 'passed', '']),
      before_last_change: pick(rnd, [true, undefined]),
      source_session: { harness: session['harness'], sid: session['sid'] },
      evidence: { source: 'transcript', confidence: 'exact' },
    };
  });
}

function genRow(rnd: Rng, session: Record<string, unknown>, ids: string[], withRead: boolean) {
  const cites = Array.from({ length: Math.floor(rnd() * 4) }, () => pick(rnd, [...ids, 'gone']));
  return {
    harness: session['harness'],
    sid: session['sid'],
    level: pick(rnd, LEVELS),
    revision: pick(rnd, [3, 3, 3, 2, null]),
    computed_at: pick(rnd, [990, null]),
    rose_at: pick(rnd, [...ids, '', 'gone']),
    rose_from: pick(rnd, ['medium', 'not_enough', 'none_or_low', '', 'bogus']),
    reasons: Array.from({ length: Math.floor(rnd() * 3) }, () => pick(rnd, REASONS)),
    cites,
    ...(withRead ? { read_at: 260, revision_read: 3 } : {}),
  };
}

describe('the live estimate and the analysis level read as the legacy page reads them', () => {
  it(`agree on ${String(SEEDS)} generated contexts`, () => {
    const failures: string[] = [];
    const seen: Record<string, number> = {};
    const note = (name: string) => {
      seen[name] = (seen[name] ?? 0) + 1;
    };
    for (let seed = 1; seed <= SEEDS && failures.length < 3; seed += 1) {
      const rnd = mulberry32(seed + 5);
      const session: Record<string, unknown> = {
        ...genSession(rnd, seed),
        harness: 'claude',
        project: 'alpha/app',
        project_key: '/repo',
      };
      const annotation = {
        ...(annotationOf(session as never) ?? {}),
        revision: pick(rnd, [3, 3, 2]),
        goal: 'Ship the queue',
        assessment: pick(rnd, [
          {
            revision_read: 3,
            read_at: 260,
            window_start: 100,
            evidence_through: 300,
            goal_source: 'typed',
            criteria: {
              goal: { result: 'departure', cites: ['f0'], detail: 'x', clause: 'Ship the queue' },
              line_1: {
                result: 'consistent with the evidence read',
                cites: ['f1', 'f2'],
                clause: 'A line',
              },
            },
          },
          null,
          { revision_read: 3, read_at: 260, criteria: {} },
        ]),
        not_accurate: pick(rnd, [undefined, undefined, true]),
        reading_count: pick(rnd, [0, 2]),
        reading_refused: pick(rnd, [undefined, true]),
      };
      const facts = genFacts(rnd, session);
      const ids = facts.map((fact) => fact.fact_id);
      const data = {
        semantic: { facts },
        sources: {
          work: {
            live_levels: [genRow(rnd, session, ids, false)],
            analysis_levels: [genRow(rnd, session, ids, true)],
            tool_reports: [],
          },
        },
      };
      const group = { label: 'alpha/app', sessions: [session] };
      const key = legacy.call<string>('nextCockpitContextKey', group, session);
      const entry = { data, revision: 1 };
      legacy.setData({ annotate: true, generated: 1000 });
      legacy.run('nextCockpitContexts.clear(); nextLiveMonitorMemory.clear();');
      legacy.run('nextCockpitContexts.set(__key, __entry);', { key, entry });
      const on = rnd() < 0.8;
      legacy.run('nextLiveMonitorMemory.set(__key, __on);', {
        key: `compass.next.live-estimate:${compatSessKey(session as never)}`,
        on,
      });
      const contexts = new Map<string, ContextEntry>([
        [key, { data: data as never, revision: 1, error: null }],
      ]);
      const projectKey = legacy.call<string>('nextCockpitStableKey', group);
      const payload = { annotate: true, generated: 1000 };
      const work = workSource(contexts, projectKey, session as never);
      const row = session as never;
      // The session in the legacy page carries the annotation it published.
      const theirs = legacy.call<Record<string, unknown> | null>(
        'nextDriftEstimate',
        group,
        session,
      );
      void theirs;
      const mine = liveEstimate({
        on,
        harness: 'claude',
        contexts,
        projectKey,
        session: row,
        annotation: annotation as never,
        work,
        payload: payload as never,
        generated: 1000,
      });
      void mine;
      // The legacy estimate reads the session's own annotation: make both read the same one.
      const annotated = { ...session };
      for (const [name, value] of Object.entries(annotation))
        annotated[`annotation_${name}`] = value;
      const group2 = { label: 'alpha/app', sessions: [annotated] };
      const key2 = legacy.call<string>('nextCockpitContextKey', group2, annotated);
      legacy.run('nextCockpitContexts.clear(); nextCockpitContexts.set(__key, __entry);', {
        key: key2,
        entry,
      });
      legacy.run('nextLiveMonitorMemory.set(__key, __on);', {
        key: `compass.next.live-estimate:${compatSessKey(annotated as never)}`,
        on,
      });
      const contexts2 = new Map<string, ContextEntry>([
        [key2, { data: data as never, revision: 1, error: null }],
      ]);
      const projectKey2 = legacy.call<string>('nextCockpitStableKey', group2);
      const work2 = workSource(contexts2, projectKey2, annotated as never);
      const theirs2 = legacy.call<Record<string, unknown> | null>(
        'nextDriftEstimate',
        group2,
        annotated,
      );
      const mine2 = liveEstimate({
        on,
        harness: 'claude',
        contexts: contexts2,
        projectKey: projectKey2,
        session: annotated as never,
        annotation: annotationOf(annotated as never),
        work: work2,
        payload: payload as never,
        generated: 1000,
      });
      if (theirs2 === null) {
        if (mine2 !== null) failures.push(`seed ${String(seed)} estimate: expected null`);
      } else if ('save' in theirs2) {
        if (!mine2 || !('save' in mine2)) failures.push(`seed ${String(seed)} estimate save`);
        note('estimate:save');
      } else {
        const level = mine2 as DriftLevel | null;
        if (!level || 'save' in level) {
          failures.push(`seed ${String(seed)} estimate: missing`);
        } else {
          note(`estimate:${level.level}`);
          const a = { ...theirs2, signals: htmlText(String(theirs2['signals'] || '')) };
          const b = {
            level: level.level,
            label: level.label,
            source: level.source,
            rose: level.rose,
            anchored: level.anchored,
            signals: signalsText(level.signals),
            reasons: level.reasons,
          };
          const found = firstDifference(canonical(a), canonical(b));
          if (found) failures.push(`seed ${String(seed)} estimate: ${found}`);
        }
      }
      // The analysis level, over the shape of the stored reading.
      const entries = work2.all || work2.entries || [];
      const ann2 = annotationOf(annotated as never);
      const shape = readingShape(ann2?.['assessment'], ann2, entries, '', false, () => 'typed');
      const legacyShape = legacy.call(
        'nextCockpitReadingShape',
        ann2?.['assessment'],
        ann2,
        entries,
        '',
        false,
        () => 'typed',
        {},
      );
      const analysisA = legacy.call<Record<string, unknown> | null>(
        'nextDriftAnalysis',
        group2,
        annotated,
        ann2,
        legacyShape,
      );
      const analysisB = analysisLevel({
        contexts: contexts2,
        projectKey: projectKey2,
        session: annotated as never,
        annotation: ann2,
        shape,
        work: work2,
        payload: payload as never,
        generated: 1000,
      });
      if (analysisA === null) {
        if (analysisB !== null) failures.push(`seed ${String(seed)} analysis: expected null`);
      } else if (!analysisB) {
        failures.push(`seed ${String(seed)} analysis: missing`);
      } else if (
        ['medium', 'high', 'extreme'].includes(String(analysisA['level'])) &&
        shape.departures.length === 0
      ) {
        /* A named departure: the page draws no level above None or low beside a reading that shows no
           departure, where the retired page drew the server's. The level is the one field held here; the
           card says what the reading did find instead.
           docs/design-frontend-migration.md#held-to-recorded-answers */
        note('analysis:withheld-without-departure');
        if (analysisB.level !== 'not_enough') {
          failures.push(`seed ${String(seed)} analysis: ${analysisB.level} without a departure`);
        }
      } else {
        note(`analysis:${analysisB.level}`);
        /* A second named departure: where the page holds a server None or low to its own rows it says which
           row held it, a sentence the retired page left out of the blockers. */
        const theirBlockers = new Set<unknown>(
          (analysisA['reasons'] as { blockers?: unknown[] } | undefined)?.blockers ?? [],
        );
        const pageBlockers = new Set<string | undefined>([
          BLOCKER_LINES['line-not-shown-by-a-check'],
          REASON_LINES['claim-not-shown']?.(''),
        ]);
        const reasons = {
          ...analysisB.reasons,
          blockers: analysisB.reasons.blockers.filter(
            (line) => !(pageBlockers.has(line) && !theirBlockers.has(line)),
          ),
        };
        const found = firstDifference(
          canonical({
            ...analysisA,
            /* A named departure: the recording says "Analysis at HH:MM · intent against ...", the page
               leaves the time to the card header and begins at "Intent".
               docs/design-frontend-migration.md#held-to-recorded-answers */
            line: String(analysisA['line']).replace(
              /^Analysis at \d\d:\d\d · (.)/,
              (_all, first: string) => first.toUpperCase(),
            ),
          }),
          canonical({
            level: analysisB.level,
            label: analysisB.label,
            source: analysisB.source,
            line: analysisB.line,
            analysis: true,
            rose: '',
            range: analysisB.range,
            reasons,
          }),
        );
        if (found) failures.push(`seed ${String(seed)} analysis: ${found}`);
      }
      const stored = legacy.call<boolean>('nextDriftReadingStored', ann2);
      if (stored !== readingStored(ann2)) failures.push(`seed ${String(seed)} stored`);
    }
    if (process.env['DRIFT_VERBOSE']) console.log(JSON.stringify(seen));
    expect(failures).toEqual([]);
    expect(Object.keys(seen).filter((name) => name.startsWith('estimate:')).length).toBeGreaterThan(
      2,
    );
    expect(Object.keys(seen).filter((name) => name.startsWith('analysis:')).length).toBeGreaterThan(
      0,
    );
  });
});

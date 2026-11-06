import {
  mulberry32,
  pick,
  genAnnotation,
  genAssessment,
  genEntries,
  type GenEntry,
} from './generate.test.helper';
import {
  CONSISTENT,
  DEPARTURE,
  GOAL_UNCLEAR_RESULT,
  NOT_REACHED,
  UNSUPPORTED,
  UNVERIFIABLE,
} from './sentences';

/* The inputs the drift parity check feeds both readers: the page's own derivation (`terminalParity.test.ts`)
   and the terminal's port of it (`tests/test_drift_view.py`). A case is the published JSON a freshly loaded
   page receives and nothing a tab holds: the session row, the payload bits the page reads, and the focused
   context's body. Expected values are never written here; the page writes them. */

export type Json = Record<string, unknown>;

export interface DriftCase {
  readonly name: string;
  /** The inventory rules this case is the evidence for. */
  readonly rules: readonly string[];
  readonly session: Json;
  readonly payload: Json;
  readonly context: Json;
}

/* The rules the named cases must cover, each owned by one row of the shape contract or the earlier-departure
   rules. The Python test fails on a rule no named case lists, so a rule cannot lose its coverage silently. */
export const RULES: readonly string[] = [
  'S1',
  'S2',
  'S3',
  'S4',
  'S5',
  'S6',
  'S7',
  'S8',
  'S9',
  'S10',
  'S11',
  'S12',
  'S13',
  'S14',
  'S15',
  'S16',
  'S17',
  'P1',
  'P2',
  'W1',
  'W2',
  'W3',
  'L1',
  'L2',
  'L3',
  'L4',
  'L5',
  'L6',
  'L7',
  'L8',
  'L9',
  'L10',
  'L11',
  'L12',
];

interface Spec {
  readonly harness?: string;
  readonly annotation?: Json;
  /** Merged over the default reading; `criteria` replaces the default rows whole. */
  readonly reading?: Json | null;
  readonly facts?: readonly Json[];
  readonly session?: Json;
  readonly payload?: Json;
  readonly work?: Json;
  readonly priors?: readonly Json[];
  /** The server's analysis level row for the session, as `sources.work.analysis_levels` carries it. */
  readonly analysis?: Json;
  /** The server's live estimate row, as `sources.work.live_levels` carries it. */
  readonly live?: Json;
  /** The Live monitor's lease, as `sources.work.live_monitor` carries it. */
  readonly lease?: Json;
}

const ROUTES = {
  claude: { provider: 'claude' },
  codex: { provider: 'claude', destination: 'codex' },
};

export function fact(id: string, type: string, at: number, over: Json = {}): Json {
  return {
    fact_id: id,
    type,
    by: type === 'user_message' ? 'person:me' : 'agent',
    summary: id,
    at,
    evidence: { source: 'transcript', confidence: 'exact' },
    ...over,
  };
}

const M1 = fact('m1', 'agent_message', 150);
const check = (id: string, at: number, result: string, over: Json = {}): Json =>
  fact(id, 'tool_report', at, { subject: 'check', result, ...over });

const goalRow = (over: Json = {}): Json => ({
  result: DEPARTURE,
  cites: ['m1'],
  detail: 'It went elsewhere',
  clause: 'Ship the queue',
  ...over,
});
const lineRow = (over: Json = {}): Json => ({
  result: CONSISTENT,
  cites: ['m1'],
  detail: '',
  clause: 'Run the tests',
  ...over,
});

const LINE_1: Json = { line_1: 'Run the tests' };

function build(name: string, rules: readonly string[], spec: Spec = {}): DriftCase {
  const harness = spec.harness ?? 'claude';
  const identity = { harness, sid: 's1' };
  const annotation: Json = {
    goal: 'Ship the queue',
    revision: 3,
    revision_count: 3,
    at: 100,
    goal_saved_at: 100,
    window_start: 100,
    ...spec.annotation,
  };
  const assessment: Json | null =
    spec.reading === null
      ? null
      : {
          revision_read: 3,
          revision_read_at: 100,
          window_start: 100,
          read_at: 200,
          stamp: 'model · today',
          cutoff: 'Evidence read up to its end.',
          scope: 'last-turn',
          scope_text: 'Read to its last turn.',
          evidence_through: 190,
          criteria: { goal: goalRow() },
          ...spec.reading,
        };
  const session: Json = {
    ...identity,
    state: 'idle',
    ended_at: 400,
    ...Object.fromEntries(
      Object.entries(annotation).map(([key, value]) => [`annotation_${key}`, value]),
    ),
    ...(assessment ? { annotation_assessment: assessment } : {}),
    ...(spec.priors ? { annotation_prior_departures: spec.priors } : {}),
    ...spec.session,
  };
  const facts = (spec.facts ?? [M1]).map((entry) => ({
    source_session: identity,
    ...entry,
  }));
  return {
    name,
    rules,
    session,
    payload: { annotate: true, generated: 1000, reading_routes: ROUTES, ...spec.payload },
    context: {
      semantic: { facts },
      sources: {
        work: {
          ...(spec.analysis ? { analysis_levels: [{ ...identity, ...spec.analysis }] } : {}),
          ...(spec.live ? { live_levels: [{ ...identity, ...spec.live }] } : {}),
          ...(spec.lease ? { live_monitor: spec.lease } : {}),
          ...spec.work,
        },
      },
    },
  };
}

const lineRequests = (extra: Json): Json => ({
  line_requests: [{ harness: 'claude', sid: 's1', revision: 3, lines: extra }],
});

/* The twin set DRC-5102's second criterion names: one base, a goal that departs on the agent's message, and a
   person's message after the reading's words. */
const twin = (name: string, rules: readonly string[], spec: Spec): DriftCase =>
  build(name, rules, spec);
const U170 = fact('u1', 'user_message', 170);

const CI = {
  read_at: 150,
  error: '',
  source: 'goal',
  repository: 'acme/widgets',
  number: 12,
  head: 'a'.repeat(40),
  session_head: 'a'.repeat(40),
  head_matches: true,
  required_only: false,
  not_counted: 0,
  counts: { pass: 1, fail: 0, pending: 0, skipping: 0, cancel: 0 },
  caution: false,
  checks: [{ name: 'lint', bucket: 'pass', completed_at: 140 }],
};

/* An earlier departure resting on a recorded write: a failed check on the record would also make the later
   message-only pass read as not verifiable, which is a different rule. */
const W0 = fact('w0', 'tool_report', 120, { subject: 'write' });
const PRIOR = (over: Json = {}): Json => ({
  key: 'line_1',
  read_at: 150,
  criterion: {
    result: DEPARTURE,
    cites: ['w0'],
    detail: 'It wrote elsewhere',
    clause: 'Run the tests',
    why: 'recorded-write',
  },
  ...over,
});
const T1 = check('t1', 120, 'failed');
const T2 = check('t2', 170, 'passed');

export function namedCases(): DriftCase[] {
  return [
    build('a-departure-on-the-agent-s-message-stands', ['S4', 'S16', 'S17']),
    build('a-reading-with-an-unknown-key-is-malformed', ['S1'], { reading: { surprise: true } }),
    build('a-reading-with-bad-coverage-is-malformed', ['S1'], {
      reading: { coverage: { tail_truncated: 'x' } },
    }),
    build('a-reading-with-a-bad-goal-verdict-is-malformed', ['S1'], {
      reading: { goal_verdict: { at: 1 } },
    }),
    build('a-reading-with-a-bad-ci-record-is-malformed', ['S1'], {
      reading: { ci: { read_at: 1 } },
    }),
    build('a-reading-with-counted-coverage-marks-rows-partial', ['S1'], {
      reading: {
        coverage: {
          tail_truncated: true,
          tail_start: 120,
          unlisted: 2,
          unread_checks: 1,
          goal_source: 'whole',
          other_commands: 3,
          read_only_commands: 1,
        },
      },
    }),
    build('a-reading-with-a-valid-goal-verdict-reads-as-a-reading', ['S1'], {
      reading: { goal_verdict: { at: 150, check: 'agrees', why: 'written-before', cites: [] } },
    }),
    build('a-typed-line-the-reading-read-has-no-row', ['S2'], {
      annotation: LINE_1,
      reading: { criteria: { goal: goalRow() } },
    }),
    build('a-line-typed-after-an-older-reading-is-left-out', ['S2'], {
      annotation: LINE_1,
      reading: { revision_read: 2, criteria: { goal: goalRow() } },
    }),
    build('the-output-row-owns-the-first-typed-line', ['S2'], {
      annotation: LINE_1,
      reading: { criteria: { goal: goalRow(), output: lineRow() } },
    }),
    build('a-result-outside-the-set-is-malformed', ['S3'], {
      reading: { criteria: { goal: goalRow({ result: 'met' }) } },
    }),
    build('not-reached-stands-in-a-last-turn-scope', ['S3', 'S17'], {
      annotation: LINE_1,
      reading: {
        criteria: { goal: goalRow(), line_1: lineRow({ result: NOT_REACHED, detail: 'Stopped' }) },
      },
    }),
    build('not-reached-outside-a-last-turn-scope-is-malformed', ['S3'], {
      annotation: LINE_1,
      reading: {
        scope: 'session-end',
        criteria: { goal: goalRow(), line_1: lineRow({ result: NOT_REACHED }) },
      },
    }),
    build('a-departure-citing-nothing-is-demoted', ['S4'], {
      reading: { criteria: { goal: goalRow({ cites: [] }) } },
    }),
    build('a-citation-to-an-entry-the-page-does-not-hold-is-demoted', ['S4'], {
      reading: { criteria: { goal: goalRow({ cites: ['nope'] }) } },
    }),
    build('a-cited-entry-with-no-source-does-not-count', ['S4'], {
      facts: [M1, fact('m2', 'agent_message', 160, { evidence: {} })],
      reading: { criteria: { goal: goalRow({ cites: ['m2'] }) } },
    }),
    build('an-entry-before-the-window-does-not-count', ['S5'], {
      facts: [M1, fact('m0', 'agent_message', 50)],
      reading: { criteria: { goal: goalRow({ cites: ['m0'] }) } },
    }),
    build('a-line-request-floor-drops-an-earlier-entry', ['S5'], {
      annotation: {
        ...LINE_1,
        line_1_source: 'entry',
        line_1_source_id: 'u9',
        settled_through: 300,
      },
      facts: [M1, fact('u9', 'user_message', 120), fact('m3', 'agent_message', 110)],
      work: lineRequests({ line_1: { at: 120, source_id: 'u9' } }),
      reading: { criteria: { goal: goalRow(), line_1: lineRow({ cites: ['m3'] }) } },
    }),
    build('a-line-request-floor-keeps-a-later-entry', ['S5'], {
      annotation: {
        ...LINE_1,
        line_1_source: 'entry',
        line_1_source_id: 'u9',
        settled_through: 300,
      },
      facts: [M1, fact('u9', 'user_message', 120), fact('m4', 'agent_message', 130)],
      work: lineRequests({ line_1: { at: 120, source_id: 'u9' } }),
      reading: { criteria: { goal: goalRow(), line_1: lineRow({ cites: ['m4'] }) } },
    }),
    build('an-outcome-line-reads-cant-tell-where-the-route-has-no-provider', ['S6'], {
      annotation: LINE_1,
      payload: { reading_routes: { claude: {} } },
      reading: { criteria: { goal: goalRow(), line_1: lineRow() } },
    }),
    build('a-claims-row-is-withheld-where-the-route-has-no-provider', ['S6'], {
      payload: { reading_routes: { claude: {} } },
      facts: [M1, T1],
      reading: {
        criteria: { goal: goalRow(), claims: { result: DEPARTURE, cites: ['m1', 't1'] } },
      },
    }),
    build('codex-limits-an-outcome-line-when-the-route-has-no-destination', ['S6'], {
      harness: 'codex',
      annotation: LINE_1,
      payload: { reading_routes: { codex: { provider: 'claude' } } },
      facts: [M1, T2],
      reading: { criteria: { goal: goalRow(), line_1: lineRow({ cites: ['t2'] }) } },
    }),
    build('codex-lifts-the-limit-when-the-route-has-a-destination', ['S6'], {
      harness: 'codex',
      annotation: LINE_1,
      facts: [M1, T2],
      reading: { criteria: { goal: goalRow(), line_1: lineRow({ cites: ['t2'] }) } },
    }),
    build('a-codex-final-answer-is-not-demonstrated-work', ['S12'], {
      harness: 'codex',
      annotation: LINE_1,
      facts: [fact('r1', 'result', 160)],
      reading: { criteria: { goal: goalRow(), line_1: lineRow({ cites: ['r1'] }) } },
    }),
    build('a-codex-departure-reads-as-a-departure', ['S17'], { harness: 'codex' }),
    build('a-codex-reading-with-a-goal-verdict', ['S1'], {
      harness: 'codex',
      reading: { goal_verdict: { at: 150, check: 'unconfirmed', why: 'check-failed', cites: [] } },
    }),
    twin('a-later-direction-unsettled-demotes-the-departure', ['S7'], {
      facts: [M1, U170],
    }),
    twin('a-later-direction-settled-lets-the-departure-stand', ['S7'], {
      annotation: { settled_through: 170 },
      facts: [M1, U170],
    }),
    twin('a-later-direction-after-the-reading-leaves-the-departure', ['S7'], {
      facts: [M1, fact('u2', 'user_message', 250)],
    }),
    twin('a-later-direction-never-demotes-the-claims-row', ['S7', 'S16'], {
      facts: [M1, T1, U170],
      reading: {
        criteria: { goal: goalRow(), claims: { result: DEPARTURE, cites: ['m1', 't1'] } },
      },
    }),
    twin('a-person-s-gate-decision-is-a-later-direction', ['S7'], {
      facts: [M1, fact('g1', 'gate_decision', 170, { by: 'person:x' })],
    }),
    twin('a-correction-copied-from-compass-is-not-a-later-direction', ['S7'], {
      facts: [M1, fact('u3', 'user_message', 170, { copied: true })],
    }),
    twin('a-message-at-the-baseline-is-not-later', ['S7'], {
      facts: [M1, fact('u4', 'user_message', 100)],
    }),
    twin('later-directions-two-one-settled', ['S7'], {
      annotation: { settled_through: 170 },
      facts: [M1, fact('u5', 'user_message', 160), fact('u6', 'user_message', 180)],
    }),
    twin('later-directions-two-both-settled', ['S7'], {
      annotation: { settled_through: 180 },
      facts: [M1, fact('u5', 'user_message', 160), fact('u6', 'user_message', 180)],
    }),
    twin('codex-later-direction-unsettled', ['S7'], {
      harness: 'codex',
      facts: [M1, U170],
    }),
    build('a-reading-over-no-saved-goal-floors-directions-at-the-prompt', ['S7', 'L11'], {
      annotation: { goal: '', goal_saved_at: null },
      session: { first_prompt: 'Ship the queue', first_prompt_at: 90 },
      facts: [M1, U170],
    }),
    build('the-rescope-floors-at-the-revision-time-not-the-draft', ['S7', 'L11'], {
      annotation: { goal: '', goal_saved_at: null },
      session: { first_prompt: 'Ship the queue', first_prompt_at: 90 },
      facts: [M1, fact('u7', 'user_message', 95)],
    }),
    build('a-row-with-an-unknown-key-is-malformed', ['S8'], {
      reading: { criteria: { goal: goalRow({ extra: 1 }) } },
    }),
    build('a-stored-reason-this-build-does-not-know-is-malformed', ['S8'], {
      annotation: LINE_1,
      reading: { criteria: { goal: goalRow(), line_1: { result: UNVERIFIABLE, why: 'mystery' } } },
    }),
    build('a-goal-too-vague-takes-no-citation-and-no-demotion', ['S9'], {
      facts: [M1, U170],
      payload: { reading_routes: { claude: {} } },
      reading: { criteria: { goal: { result: GOAL_UNCLEAR_RESULT, clause: 'Ship the queue' } } },
    }),
    build('a-too-vague-result-on-an-outcome-line-is-malformed', ['S9'], {
      annotation: LINE_1,
      reading: { criteria: { goal: goalRow(), line_1: { result: GOAL_UNCLEAR_RESULT } } },
    }),
    build('a-failed-check-carries-a-line-departure', ['S10'], {
      annotation: LINE_1,
      facts: [M1, check('t3', 160, 'failed')],
      reading: {
        criteria: { goal: goalRow(), line_1: lineRow({ result: DEPARTURE, cites: ['t3'] }) },
      },
    }),
    build('a-passed-check-carries-a-line-consistent', ['S10', 'S15'], {
      annotation: LINE_1,
      facts: [M1, T2],
      reading: { criteria: { goal: goalRow(), line_1: lineRow({ cites: ['t2'] }) } },
    }),
    build('a-pass-before-the-last-change-carries-nothing', ['S10'], {
      annotation: LINE_1,
      facts: [M1, check('t4', 170, 'passed', { before_last_change: true })],
      reading: { criteria: { goal: goalRow(), line_1: lineRow({ cites: ['t4'] }) } },
    }),
    build('a-pass-with-an-incomplete-read-says-so', ['S10'], {
      annotation: LINE_1,
      facts: [M1, check('t5', 170, 'passed', { read_incomplete: true })],
      reading: { criteria: { goal: goalRow(), line_1: lineRow({ cites: ['t5'] }) } },
    }),
    build('a-created-pull-request-carries-a-consistent', ['S10'], {
      annotation: LINE_1,
      facts: [M1, fact('p1', 'tool_report', 170, { subject: 'pr' })],
      reading: { criteria: { goal: goalRow(), line_1: lineRow({ cites: ['p1'] }) } },
    }),
    build('a-recorded-write-carries-a-departure-when-stored-so', ['S10'], {
      annotation: LINE_1,
      facts: [M1, fact('w1', 'tool_report', 170, { subject: 'write' })],
      reading: {
        criteria: {
          goal: goalRow(),
          line_1: lineRow({ result: DEPARTURE, cites: ['w1'], why: 'recorded-write' }),
        },
      },
    }),
    build('a-written-path-without-the-token-carries-nothing', ['S10'], {
      annotation: LINE_1,
      facts: [M1, fact('w1', 'tool_report', 170, { subject: 'write' })],
      reading: {
        criteria: { goal: goalRow(), line_1: lineRow({ result: DEPARTURE, cites: ['w1'] }) },
      },
    }),
    build('a-recorded-command-carries-a-departure-when-stored-so', ['S10'], {
      annotation: LINE_1,
      facts: [M1, fact('c1', 'tool_report', 170, { subject: 'command', result: 'passed' })],
      reading: {
        criteria: {
          goal: goalRow(),
          line_1: lineRow({ result: DEPARTURE, cites: ['c1'], why: 'recorded-command' }),
        },
      },
    }),
    build('a-command-that-cannot-fail-carries-nothing', ['S10'], {
      annotation: LINE_1,
      facts: [
        M1,
        fact('c2', 'tool_report', 170, { subject: 'command', result: 'passed', cannot_fail: true }),
      ],
      reading: {
        criteria: {
          goal: goalRow(),
          line_1: lineRow({ result: DEPARTURE, cites: ['c2'], why: 'recorded-command' }),
        },
      },
    }),
    build('a-ci-check-that-counts-settles-a-line', ['S10', 'S1'], {
      annotation: LINE_1,
      reading: {
        ci: CI,
        criteria: { goal: goalRow(), line_1: lineRow({ cites: ['ci:12:0'] }) },
      },
    }),
    build('a-ci-pass-on-another-commit-does-not-count', ['S10'], {
      annotation: LINE_1,
      reading: {
        ci: { ...CI, head_matches: false, session_head: 'b'.repeat(40) },
        criteria: { goal: goalRow(), line_1: lineRow({ cites: ['ci:12:0'] }) },
      },
    }),
    build('a-claim-the-record-contradicts-stands', ['S11', 'S16'], {
      facts: [M1, T1],
      reading: {
        criteria: { goal: goalRow(), claims: { result: DEPARTURE, cites: ['m1', 't1'] } },
      },
    }),
    build('a-claim-with-no-agent-message-is-uncited', ['S11'], {
      facts: [M1, T1],
      reading: { criteria: { goal: goalRow(), claims: { result: DEPARTURE, cites: ['t1'] } } },
    }),
    build('a-claim-resting-on-the-observer-snapshot-alone', ['S11'], {
      facts: [M1, fact('o1', 'observer_snapshot', 160)],
      reading: {
        criteria: { goal: goalRow(), claims: { result: DEPARTURE, cites: ['m1', 'o1'] } },
      },
    }),
    build('an-unsupported-claim-needs-only-the-message', ['S11', 'S17'], {
      reading: { criteria: { goal: goalRow(), claims: { result: UNSUPPORTED, cites: ['m1'] } } },
    }),
    build('a-consistent-claim-shown-by-work', ['S11'], {
      facts: [M1, T2],
      reading: {
        criteria: { goal: goalRow(), claims: { result: CONSISTENT, cites: ['m1', 't2'] } },
      },
    }),
    build('a-consistent-claim-with-nothing-shown-is-uncited', ['S11'], {
      annotation: { settled_through: 300 },
      facts: [M1, fact('u8', 'user_message', 160)],
      reading: {
        criteria: { goal: goalRow(), claims: { result: CONSISTENT, cites: ['m1', 'u8'] } },
      },
    }),
    build('a-contradiction-before-the-claim-does-not-count', ['S11'], {
      facts: [M1, fact('d0', 'decision', 140)],
      reading: {
        criteria: { goal: goalRow(), claims: { result: DEPARTURE, cites: ['m1', 'd0'] } },
      },
    }),
    build('a-line-citing-only-the-reader-s-message-shows-no-work', ['S12'], {
      annotation: { ...LINE_1, settled_through: 300 },
      facts: [M1, fact('u8', 'user_message', 160)],
      reading: { criteria: { goal: goalRow(), line_1: lineRow({ cites: ['u8'] }) } },
    }),
    build('a-line-resting-on-the-agent-s-message-alone', ['S12', 'S15'], {
      annotation: LINE_1,
      reading: { criteria: { goal: goalRow(), line_1: lineRow() } },
    }),
    build('a-goal-resting-on-the-observer-snapshot-is-the-board-quoting-itself', ['S13'], {
      facts: [M1, fact('o1', 'observer_snapshot', 160)],
      reading: { criteria: { goal: goalRow({ result: CONSISTENT, cites: ['o1'] }) } },
    }),
    build('a-goal-agreeing-with-the-reader-s-own-words-is-circular', ['S13'], {
      annotation: { settled_through: 300 },
      facts: [M1, fact('u8', 'user_message', 160)],
      reading: { criteria: { goal: goalRow({ result: CONSISTENT, cites: ['u8'] }) } },
    }),
    build('a-passing-line-beside-a-failed-check-on-record', ['S13'], {
      annotation: LINE_1,
      facts: [M1, T1],
      reading: { criteria: { goal: goalRow(), line_1: lineRow({ cites: ['m1'] }) } },
    }),
    build('a-failed-check-the-reading-had-no-room-for-says-so', ['S13'], {
      annotation: LINE_1,
      facts: [M1, T1],
      reading: {
        criteria: {
          goal: goalRow(),
          line_1: lineRow({ cites: ['m1'], why: 'failed-check-unread' }),
        },
      },
    }),
    build('a-stored-reason-fills-the-gap-the-page-left', ['S14'], {
      annotation: LINE_1,
      reading: {
        criteria: { goal: goalRow(), line_1: { result: UNVERIFIABLE, why: 'verdict-stated' } },
      },
    }),
    build('a-stored-not-asked-becomes-the-limit', ['S14'], {
      annotation: LINE_1,
      reading: {
        criteria: { goal: goalRow(), line_1: { result: UNVERIFIABLE, why: 'not-asked' } },
      },
    }),
    build('today-s-limit-wins-over-a-stored-reason', ['S14', 'S6'], {
      annotation: LINE_1,
      payload: { reading_routes: { claude: {} } },
      reading: {
        criteria: { goal: goalRow(), line_1: { result: UNVERIFIABLE, why: 'verdict-stated' } },
      },
    }),
    build('a-line-resting-on-agent-entries-that-are-not-all-messages', ['S15'], {
      annotation: LINE_1,
      facts: [M1, fact('d1', 'decision', 150)],
      reading: { criteria: { goal: goalRow(), line_1: lineRow({ cites: ['m1', 'd1'] }) } },
    }),
    build('an-earlier-departure-is-listed-beside-a-message-only-pass', ['P1', 'P2'], {
      annotation: LINE_1,
      facts: [M1, W0],
      priors: [PRIOR()],
      reading: { criteria: { goal: goalRow(), line_1: lineRow() } },
    }),
    build('an-earlier-departure-is-listed-beside-a-cant-tell', ['P1'], {
      annotation: LINE_1,
      facts: [M1, W0],
      priors: [PRIOR()],
      reading: { criteria: { goal: goalRow(), line_1: lineRow({ cites: [] }) } },
    }),
    build('an-earlier-departure-is-listed-beside-a-not-reached', ['P1'], {
      annotation: LINE_1,
      facts: [M1, W0],
      priors: [PRIOR()],
      reading: { criteria: { goal: goalRow(), line_1: lineRow({ result: NOT_REACHED }) } },
    }),
    build('an-earlier-departure-is-hidden-beside-a-check-backed-pass', ['P1'], {
      annotation: LINE_1,
      facts: [M1, W0, T2],
      priors: [PRIOR()],
      reading: { criteria: { goal: goalRow(), line_1: lineRow({ cites: ['t2'] }) } },
    }),
    build('an-earlier-departure-on-changed-words-is-hidden', ['P2'], {
      annotation: LINE_1,
      facts: [M1, W0],
      priors: [
        PRIOR({
          criterion: {
            result: DEPARTURE,
            cites: ['w0'],
            clause: 'Other words',
            why: 'recorded-write',
          },
        }),
      ],
      reading: { criteria: { goal: goalRow(), line_1: lineRow() } },
    }),
    build('the-newest-earlier-departure-per-line-wins', ['P2'], {
      annotation: LINE_1,
      facts: [M1, W0, fact('w6', 'tool_report', 125, { subject: 'write' })],
      priors: [
        PRIOR(),
        PRIOR({
          read_at: 180,
          criterion: {
            result: DEPARTURE,
            cites: ['w6'],
            clause: 'Run the tests',
            why: 'recorded-write',
          },
        }),
      ],
      reading: { criteria: { goal: goalRow(), line_1: lineRow() } },
    }),
    build('an-earlier-departure-citing-entries-the-page-lacks-is-hidden', ['P2'], {
      annotation: LINE_1,
      priors: [
        PRIOR({
          criterion: {
            result: DEPARTURE,
            cites: ['gone'],
            clause: 'Run the tests',
            why: 'recorded-write',
          },
        }),
      ],
      reading: { criteria: { goal: goalRow(), line_1: lineRow() } },
    }),
    build('an-earlier-departure-for-the-goal-is-listed-in-reading-order', ['P1', 'P2'], {
      facts: [M1, W0],
      priors: [
        PRIOR({
          key: 'goal',
          criterion: {
            result: DEPARTURE,
            cites: ['w0'],
            clause: 'Ship the queue',
            why: 'recorded-write',
          },
        }),
      ],
      reading: { criteria: { goal: goalRow({ result: CONSISTENT }) } },
    }),
    build('earlier-departures-beside-a-malformed-reading-are-not-listed', ['P1'], {
      facts: [M1, W0],
      priors: [PRIOR()],
      reading: { surprise: true },
    }),
    build('facts-of-another-session-in-the-context-are-ignored', ['W1'], {
      facts: [
        M1,
        fact('x1', 'agent_message', 160, { source_session: { harness: 'claude', sid: 'other' } }),
      ],
      reading: { criteria: { goal: goalRow({ cites: ['x1'] }) } },
    }),
    build('fixed-numbers-label-the-cited-entries', ['W2'], {
      facts: [
        { ...M1, ordinal: 41 },
        { ...T1, ordinal: 41, ordinal_sub: 2 },
      ],
      reading: { criteria: { goal: goalRow({ cites: ['m1', 't1'] }) } },
    }),
    build('without-fixed-numbers-the-window-is-counted', ['W2'], {
      facts: [fact('m0', 'agent_message', 50), M1, T1],
      reading: { criteria: { goal: goalRow({ cites: ['t1', 'm1'] }) } },
    }),
    build('an-entry-before-the-window-is-in-the-count-and-not-the-numbers', ['W2'], {
      facts: [
        { ...fact('m0', 'agent_message', 50), ordinal: 3 },
        { ...M1, ordinal: 4 },
      ],
    }),
    build('a-session-with-no-saved-goal-drafts-its-first-prompt', ['L11'], {
      reading: null,
      annotation: {
        goal: '',
        revision: 0,
        revision_count: 0,
        at: null,
        goal_saved_at: null,
        window_start: null,
      },
      session: { first_prompt: 'Ship the queue', first_prompt_at: 90 },
    }),
    build('a-session-goal-is-drafted-ahead-of-the-prompts', ['L11'], {
      reading: null,
      annotation: {
        goal: '',
        revision: 0,
        revision_count: 0,
        at: null,
        goal_saved_at: null,
        window_start: null,
      },
      session: {
        first_prompt: 'Ship the queue',
        first_prompt_at: 90,
        session_goal: { text: 'Land it', at: 95 },
      },
    }),
    build('a-session-that-opened-with-a-control-drafts-nothing', ['L11'], {
      reading: null,
      annotation: {
        goal: '',
        revision: 0,
        revision_count: 0,
        at: null,
        goal_saved_at: null,
        window_start: null,
      },
      session: { first_prompt: '/clear', first_prompt_at: 90, first_prompt_control: true },
    }),
    build('a-saved-goal-is-not-a-draft', ['L11']),
    build('with-the-store-off-nothing-is-read', ['L11'], { payload: { annotate: false } }),
    build('a-session-with-no-reading-has-no-lines', ['S17'], { reading: null }),
    ...levelCases(),
    build('an-empty-record-reads-as-empty', ['W1'], { facts: [] }),
    build('a-session-the-scan-left-out-reads-as-partial', ['W1'], {
      facts: [],
      work: { omitted: [{ harness: 'claude', sid: 's1' }] },
    }),
  ];
}

const ANALYSIS = (over: Json = {}): Json => ({
  read_at: 200,
  revision_read: 3,
  level: 'medium',
  reasons: ['departure'],
  cites: ['m1'],
  ...over,
});
const LIVE = (over: Json = {}): Json => ({
  level: 'high',
  revision: 3,
  computed_at: 180,
  reasons: ['failed-check'],
  cites: [],
  ...over,
});
const LEASE = (over: Json = {}): Json => ({
  on: true,
  level: null,
  label: 'Live monitor · Haiku',
  now: 300,
  ...over,
});
const CHECKED = (level: string): Json => ({ level, checked_at: 290, reason: 'Heading elsewhere' });
const NO_DEPARTURE: Json = { criteria: { goal: goalRow({ cites: [] }) } };
const NO_DRAFT: Json = {
  goal: '',
  revision: 0,
  revision_count: 0,
  at: null,
  goal_saved_at: null,
  window_start: null,
};

/* The level precedence and the stale note: which level the page shows, from what, and why none. */
function levelCases(): DriftCase[] {
  return [
    build('a-departure-reading-draws-the-level-the-server-computed', ['L5', 'L9'], {
      analysis: ANALYSIS(),
    }),
    build('a-level-above-low-needs-a-departure-the-page-kept', ['L9'], {
      analysis: ANALYSIS(),
      reading: NO_DEPARTURE,
    }),
    build('none-or-low-is-withheld-while-a-line-is-not-shown-by-a-check', ['L8'], {
      annotation: LINE_1,
      analysis: ANALYSIS({ level: 'none_or_low', reasons: [] }),
      reading: {
        criteria: {
          goal: goalRow({ result: CONSISTENT }),
          line_1: { result: UNVERIFIABLE, clause: 'Run the tests' },
        },
      },
    }),
    build('none-or-low-stands-when-every-line-reads-consistent-on-a-source', ['L8'], {
      analysis: ANALYSIS({ level: 'none_or_low', reasons: [] }),
      reading: { criteria: { goal: goalRow({ result: CONSISTENT }) } },
    }),
    build('an-unsupported-claim-withholds-none-or-low', ['L8'], {
      analysis: ANALYSIS({ level: 'none_or_low', reasons: [] }),
      reading: {
        criteria: {
          goal: goalRow({ result: CONSISTENT }),
          claims: { result: UNSUPPORTED, cites: ['m1'] },
        },
      },
    }),
    build('a-level-for-another-reading-time-is-not-drawn', ['L6'], {
      analysis: ANALYSIS({ read_at: 199 }),
    }),
    build('a-level-for-another-revision-read-is-not-drawn', ['L6'], {
      analysis: ANALYSIS({ revision_read: 2 }),
    }),
    build('a-level-name-the-page-does-not-know-is-not-drawn', ['L6'], {
      analysis: ANALYSIS({ level: 'severe' }),
    }),
    build('a-reading-the-reader-marked-not-accurate-draws-no-level', ['L5'], {
      annotation: { not_accurate: true },
      analysis: ANALYSIS(),
    }),
    build('a-reading-of-replaced-words-yields-its-level-to-the-estimate', ['L7', 'L4'], {
      annotation: { revision: 4 },
      analysis: ANALYSIS(),
      lease: LEASE(),
      live: LIVE({ revision: 4 }),
    }),
    build('the-reading-that-stands-owns-the-slot-over-the-monitor', ['L10'], {
      analysis: ANALYSIS(),
      reading: NO_DEPARTURE,
      lease: LEASE({ level: CHECKED('high') }),
    }),
    build('without-a-reading-the-monitor-level-is-the-pill', ['L2'], {
      reading: null,
      lease: LEASE({ level: CHECKED('high') }),
      live: LIVE({ level: 'medium' }),
    }),
    build('the-monitor-replaces-the-estimate-while-it-stands', ['L2'], {
      reading: null,
      lease: LEASE({ level: CHECKED('none_or_low') }),
      live: LIVE(),
    }),
    build('a-lease-that-is-off-leaves-the-estimate-off', ['L1'], {
      reading: null,
      lease: LEASE({ on: false, level: CHECKED('extreme') }),
      live: LIVE(),
    }),
    build('with-no-lease-the-live-estimate-is-off', ['L1'], { reading: null, live: LIVE() }),
    build('a-lease-with-no-completed-check-shows-the-estimate', ['L1', 'L2'], {
      reading: null,
      lease: LEASE(),
      live: LIVE({ level: 'medium' }),
    }),
    build('a-live-level-that-asks-for-the-intent-first', ['L3'], {
      reading: null,
      lease: LEASE(),
      live: LIVE({ level: 'no_live_level' }),
    }),
    build('a-live-row-measured-against-another-revision-is-not-drawn', ['L4'], {
      reading: null,
      lease: LEASE(),
      live: LIVE({ revision: 2 }),
    }),
    build('codex-has-no-live-estimate-whatever-the-lease-says', ['L1'], {
      harness: 'codex',
      reading: null,
      lease: LEASE({ level: CHECKED('high') }),
      live: LIVE(),
    }),
    build('a-drafted-intent-draws-no-pill', ['L11'], {
      reading: null,
      annotation: NO_DRAFT,
      session: { first_prompt: 'Ship the queue', first_prompt_at: 90 },
      lease: LEASE(),
      live: LIVE({ revision: 0 }),
    }),
    build('a-running-session-reads-so-far', ['L12'], {
      session: { state: 'working', ended_at: null },
      analysis: ANALYSIS(),
    }),
    build('a-reading-of-a-turn-still-open-reads-so-far', ['L12'], {
      reading: { scope: 'mid-flight' },
      analysis: ANALYSIS(),
    }),
    build('a-finished-reading-of-a-finished-turn-does-not', ['L12'], { analysis: ANALYSIS() }),
    build('a-reading-is-stale-when-the-words-changed', ['W3'], {
      annotation: { revision: 4 },
      analysis: ANALYSIS(),
    }),
    build('a-reading-is-stale-when-work-landed-after-it-read', ['W3'], {
      facts: [M1, fact('m5', 'agent_message', 195)],
    }),
    build('a-stale-reading-names-the-message-it-was-read-before', ['W3'], {
      annotation: { settled_through: 300 },
      facts: [M1, fact('u9', 'user_message', 210)],
    }),
    build('compass-s-own-turn-is-not-new-work', ['W3'], {
      facts: [M1, fact('c9', 'agent_message', 195, { compass_turn: true })],
    }),
    build('a-reading-with-nothing-after-it-is-not-stale', ['W3']),
    build('a-malformed-reading-has-no-stale-note', ['W3'], { reading: { surprise: true } }),
  ];
}

const TYPE_SOURCE = (source: string): { source: string; confidence: string } => {
  const [head = '', tail = ''] = source.split(' · ');
  return { source: head, confidence: tail };
};

/* A generated entry as the server publishes it as a fact. A string time becomes null: the page sorts entries
   with a comparator a NaN breaks, and V8's and Python's sorts disagree on an inconsistent one. Both read a
   string time as no time elsewhere, so the rules lose nothing. */
function toFact(entry: GenEntry): Json {
  return {
    fact_id: entry.id,
    type: entry.type,
    by: entry.by,
    summary: entry.summary,
    at: typeof entry.at === 'string' ? null : entry.at,
    result_at: entry.resultAt,
    source_session: entry.sourceSession,
    worker_kind: entry.workerKind,
    actor_claim: entry.actorClaim,
    subject: entry.subject,
    copied: entry.copied,
    result: entry.result,
    result_source: entry.resultSource,
    earlier_failed: entry.earlierFailed,
    before_last_change: entry.beforeLastChange,
    changed_after: entry.changedAfter,
    read_incomplete: entry.readIncomplete,
    evidence: TYPE_SOURCE(entry.source),
    ...(entry.changedAfter && entry.copied ? { compass_turn: true } : {}),
  };
}

/* Most of what the generators write is refused somewhere, which is the point of them, but a set that
   departs almost never would hold the later rules to nothing. A share of cases has its rows made sound: a
   known result, a citation to an entry the case holds, and no unknown key or reason. */
function tidy(reading: Json, entries: readonly GenEntry[], rnd: () => number): Json {
  const criteria = reading['criteria'];
  if (typeof criteria !== 'object' || criteria === null || Array.isArray(criteria)) return reading;
  const ids = entries.map((entry) => entry.id).filter(Boolean);
  const sound = Object.fromEntries(
    Object.entries(criteria as Json).map(([key, row]) => {
      if (typeof row !== 'object' || row === null || Array.isArray(row)) return [key, row];
      const next: Json = { ...(row as Json) };
      delete next['extra'];
      if (next['why'] === 'mystery') delete next['why'];
      next['result'] = pick(
        rnd,
        key === 'claims'
          ? [DEPARTURE, CONSISTENT, UNSUPPORTED, UNVERIFIABLE]
          : [DEPARTURE, DEPARTURE, CONSISTENT, CONSISTENT, UNVERIFIABLE, NOT_REACHED],
      );
      next['cites'] = ids.length
        ? Array.from({ length: 1 + Math.floor(rnd() * 2) }, () => pick(rnd, ids))
        : [];
      return [key, next];
    }),
  );
  const out: Json = { ...reading, criteria: sound };
  delete out['surprise'];
  return out;
}

export function generatedCase(seed: number): DriftCase {
  const rnd = mulberry32(seed);
  const harness = pick(rnd, ['claude', 'claude', 'codex', 'pi']);
  const entries = genEntries(rnd, harness);
  /* Most cases hold entries the rules can use (a time and a source); the rest keep the generator's awkward ones. */
  const usable = rnd() < 0.7;
  const held = usable
    ? entries.map((entry, index) => ({
        ...entry,
        at: 100 + index * 10,
        source: 'transcript · exact',
      }))
    : entries;
  const facts = held.map(toFact);
  const annotation = genAnnotation(rnd);
  const drawn =
    rnd() < 0.9 ? genAssessment(rnd, entries) : pick(rnd, [null, {}, { revision_read: 'x' }]);
  const reading = drawn !== null && rnd() < 0.75 ? tidy(drawn, entries, rnd) : drawn;
  /* Earlier departures: most are the standing reading's own rows made into departures, so their clauses match
     and the rules after the clause check run; the rest come from an unrelated reading. */
  const rows = ((reading as Json | null)?.['criteria'] ?? {}) as Json;
  const priors =
    rnd() < 0.5
      ? [
          ...Object.entries(rows).flatMap(([key, row]) =>
            rnd() < 0.6 && typeof row === 'object' && row !== null && !Array.isArray(row)
              ? [
                  {
                    key,
                    read_at: pick(rnd, [120, 150, 180, 0, 'x']),
                    criterion: { ...(row as Json), result: DEPARTURE },
                  },
                ]
              : [],
          ),
          ...Object.entries((genAssessment(rnd, entries)['criteria'] as Json) ?? {}).flatMap(
            ([key, row]) => (rnd() < 0.15 ? [{ key, read_at: 150, criterion: row }] : []),
          ),
        ]
      : undefined;
  const session: Json = {
    harness,
    sid: 's1',
    state: pick(rnd, ['idle', 'working']),
    ...(rnd() < 0.5 ? { ended_at: 400 } : {}),
    ...Object.fromEntries(
      Object.entries(annotation).map(([key, value]) => [`annotation_${key}`, value]),
    ),
    annotation_window_start: pick(rnd, [null, 100, 140]),
    ...(reading !== null ? { annotation_assessment: reading } : {}),
    ...(priors ? { annotation_prior_departures: priors } : {}),
    ...(rnd() < 0.3
      ? { first_prompt: 'Ship the queue', first_prompt_at: pick(rnd, [90, 120, 0]) }
      : {}),
    ...(rnd() < 0.15 ? { session_goal: { text: 'Land it', at: 95 } } : {}),
    ...(rnd() < 0.1 ? { first_prompt_control: true } : {}),
  };
  const routes = pick(rnd, [
    ROUTES,
    { claude: {}, codex: {} },
    { claude: { provider: 'p' }, codex: { provider: 'p' } },
  ]);
  const analysis =
    reading !== null && rnd() < 0.7
      ? [
          {
            harness,
            sid: 's1',
            read_at: rnd() < 0.85 ? (reading as Json)['read_at'] : 199,
            revision_read: rnd() < 0.85 ? (reading as Json)['revision_read'] : 2,
            level: pick(rnd, [
              'none_or_low',
              'medium',
              'medium',
              'high',
              'extreme',
              'not_enough',
              'bogus',
            ]),
            reasons: pick(rnd, [
              [],
              ['departure'],
              ['later-direction'],
              ['failed-check', 'departure'],
            ]),
            cites: [],
          },
        ]
      : undefined;
  const live =
    rnd() < 0.5
      ? [
          {
            harness,
            sid: 's1',
            level: pick(rnd, ['none_or_low', 'medium', 'high', 'no_live_level', 'bogus']),
            revision: pick(rnd, [3, 3, 2, null]),
            computed_at: 180,
            reasons: [],
            cites: [],
          },
        ]
      : undefined;
  const lease = pick(rnd, [
    undefined,
    undefined,
    { on: true, level: null, now: 300 },
    {
      on: true,
      level: {
        level: pick(rnd, ['none_or_low', 'high', 'not_enough', 'bogus']),
        checked_at: 290,
        reason: 'x',
      },
      now: 300,
    },
    { on: false, level: { level: 'high', checked_at: 290, reason: 'x' }, now: 300 },
    { on: 'x' },
  ]);
  return {
    name: `generated-${String(seed)}`,
    rules: [],
    session,
    payload: { annotate: rnd() < 0.9, generated: 1000, reading_routes: routes },
    context: {
      semantic: { facts },
      sources: {
        work: {
          ...(rnd() < 0.3 ? lineRequestsFor(harness) : {}),
          ...(analysis ? { analysis_levels: analysis } : {}),
          ...(live ? { live_levels: live } : {}),
          ...(lease ? { live_monitor: lease } : {}),
        },
      },
    },
  };
}

function lineRequestsFor(harness: string): Json {
  return {
    line_requests: [
      {
        harness,
        sid: 's1',
        revision: 3,
        lines: { line_1: { at: 120, source_id: 'e1' }, line_2: { at: 150, source_id: 'e2' } },
      },
    ],
  };
}

export const GENERATED_SEEDS = 160;
export const GENERATED_FIRST_SEED = 5102;

export function generatedCases(): DriftCase[] {
  return Array.from({ length: GENERATED_SEEDS }, (_, index) =>
    generatedCase(GENERATED_FIRST_SEED + index),
  );
}

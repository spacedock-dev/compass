import {
  CI_BUCKET_WORDS,
  CI_BUCKETS,
  CI_CANCELLED,
  CI_CAUTION,
  CI_ENTRY_RESULT,
  CI_ENTRY_SOURCE,
  CI_ENTRY_SOURCE_GITLAB,
  CI_ENTRY_WORDS,
  CI_ENTRY_WORDS_GITLAB,
  CI_FAILING,
  CI_HEAD_MOVED,
  CI_HEAD_MOVED_GITLAB,
  CI_HEAD_UNKNOWN,
  CI_NONE_DONE,
  CI_NO_CHECKS,
  CI_REQUIRED_ONLY,
  CI_RUNNING,
  CI_SETTLES,
  ciNotCounted,
  ciProvider,
  ciReadFailed,
  ciReadFrom,
  ciReadReason,
  ciRequestName,
} from './sentences';
import type { WorkEntry } from '../intent/work';
import type { CiRead } from './shape';

/* What a press read of the pull request's CI checks, from the stored record alone: where the facts came from
   (GitHub or GitLab, through the reader's own gh or glab), when, and what they settle. The sentences are Compass's, from closed
   tokens and counts, so nothing the CLI printed reaches the page. The rules repeat the producer's
   (`ci_read.green` and `ci_read.facts`) and the vocabulary fixture holds the tokens equal; the verdict a line
   rests on is the producer's and is never re-derived from this note. */
export type CiState = 'failed' | 'settles' | 'unsettled';

export function ciReadNote(ci: CiRead, clockText: string): { state: CiState; lines: string[] } {
  if (ci.error) {
    const provider = ciProvider(ci.repository);
    return {
      state: 'failed',
      lines: [ciReadFailed(ciReadReason(ci.error, provider), provider)],
    };
  }
  const counts = CI_BUCKETS.filter((bucket) => (ci.counts[bucket] ?? 0) > 0).map(
    (bucket) => `${String(ci.counts[bucket])} ${CI_BUCKET_WORDS[bucket] ?? bucket}`,
  );
  const lines = [
    ciReadFrom(
      clockText,
      ciRequestName(ci.repository, ci.number),
      counts.length ? counts.join(', ') : CI_NO_CHECKS,
      ciProvider(ci.repository),
    ),
  ];
  const pass = ci.counts['pass'] ?? 0;
  const green =
    pass > 0 &&
    !(ci.counts['fail'] ?? 0) &&
    !(ci.counts['pending'] ?? 0) &&
    !(ci.counts['cancel'] ?? 0);
  let state: CiState = 'unsettled';
  if (!ci.head_matches) {
    const moved = ciProvider(ci.repository) === 'GitLab' ? CI_HEAD_MOVED_GITLAB : CI_HEAD_MOVED;
    lines.push(ci.session_head ? moved : CI_HEAD_UNKNOWN);
  } else if (ci.counts['fail']) {
    lines.push(CI_FAILING);
    state = 'settles';
  } else if (ci.counts['pending']) lines.push(CI_RUNNING);
  else if (ci.counts['cancel']) lines.push(CI_CANCELLED);
  else if (!pass) lines.push(CI_NONE_DONE);
  else if (green) {
    lines.push(CI_SETTLES);
    state = 'settles';
  }
  if (ci.required_only) {
    lines.push(CI_REQUIRED_ONLY);
    if ((ci.not_counted ?? 0) > 0) lines.push(ciNotCounted(ci.not_counted ?? 0));
  }
  if (ci.caution) lines.push(CI_CAUTION);
  return { state, lines };
}

/* Whether every check that counts passed: at least one pass, and none failed, pending or cancelled
   (`ci_read.green`). The counts are over the checks that count, not only the listed ones. */
const green = (ci: CiRead): boolean =>
  (ci.counts['pass'] ?? 0) > 0 &&
  !(ci.counts['fail'] ?? 0) &&
  !(ci.counts['pending'] ?? 0) &&
  !(ci.counts['cancel'] ?? 0);

/* The entries a stored read stands for, as the producer numbered them in the prompt (`ci_read.facts`): the
   same ids, words and `ciCounts`, so a citation of one resolves on this page and a line resting on a pass
   that does not count is refused here as it was there. They join the citations a reading is read against and
   never the activity list: what GitHub said at the press is no event of the session. */
export function ciEntries(ci: CiRead | null, harness: string, sid: string): WorkEntry[] {
  if (!ci || ci.error || !ci.checks.length) return [];
  const whole = green(ci);
  const gitlab = ciProvider(ci.repository) === 'GitLab';
  const words = gitlab ? CI_ENTRY_WORDS_GITLAB : CI_ENTRY_WORDS;
  const notes = [
    ...(ci.head_matches
      ? []
      : [`the ${gitlab ? 'merge' : 'pull'} request head is not this session's commit`]),
    ...(ci.caution ? ['this session changed the CI configuration'] : []),
  ];
  return ci.checks.map((check, index) => ({
    id: `ci:${String(ci.number)}:${String(index)}`,
    type: 'ci_check',
    by: gitlab ? 'gitlab' : 'github',
    summary: `${JSON.stringify(check.name)} ${words[check.bucket] ?? ''}${
      notes.length ? `; ${notes.join('; ')}` : ''
    }`,
    at: ci.read_at,
    resultAt: null,
    sourceSession: { harness, sid },
    workerKind: '',
    actorClaim: '',
    modelDerived: false,
    subject: 'ci',
    checkId: '',
    copied: false,
    work: true,
    result: CI_ENTRY_RESULT[check.bucket] ?? '',
    resultSource: '',
    resultReason: '',
    earlierFailed: false,
    beforeLastChange: false,
    changedAfter: false,
    readIncomplete: false,
    ordinal: null,
    ordinalSub: null,
    source: gitlab ? CI_ENTRY_SOURCE_GITLAB : CI_ENTRY_SOURCE,
    ciCounts: ci.head_matches && ((check.bucket === 'pass' && whole) || check.bucket === 'fail'),
  }));
}

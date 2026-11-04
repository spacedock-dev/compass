import { longDiagnostic, type LongDiagnostic } from '../api/longDiagnostic';
import { nextNumber } from '../api/bootstrap';
import { isRecord, type Row } from '../observed';
import { LONG_OUTCOME } from './sentences';

export const sessionLongDiagnostic = (session: Row): LongDiagnostic | null =>
  longDiagnostic(session['annotation_long_diagnostic']);

/** Stored ordinary failure prose has no job binding and cannot label an older long outcome. */
export function longOutcomeSentence(diagnostic: LongDiagnostic): string {
  return LONG_OUTCOME[diagnostic.outcome];
}
export function olderThanLongAttempt(session: Row, assessment: Row): boolean {
  const diagnostic = sessionLongDiagnostic(session),
    binding = diagnostic?.binding;
  const at = nextNumber(assessment['read_at']);
  return Boolean(
    binding &&
      at !== null &&
      binding.job_started_at > at &&
      binding.revision === session['annotation_revision'] &&
      binding.revision_at === session['annotation_at'] &&
      binding.window_start === assessment['window_start'],
  );
}

/** A matching diagnostic is not itself proof that this row contains that job's new reading. */
export function hasBoundLongReading(session: Row, diagnostic: LongDiagnostic): boolean {
  const assessment = session['annotation_assessment'],
    binding = diagnostic.binding;
  return Boolean(
    isRecord(assessment) &&
      binding &&
      typeof assessment['read_at'] === 'number' &&
      assessment['read_at'] >= binding.job_started_at &&
      assessment['revision_read'] === binding.revision &&
      assessment['revision_read_at'] === binding.revision_at &&
      assessment['window_start'] === binding.window_start,
  );
}

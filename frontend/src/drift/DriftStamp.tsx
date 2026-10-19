import { nextNumber } from '../api/bootstrap';
import { useDrift } from './context';
import { lastRunLine } from './result';

/* The Drift card header's model and "Analysis last run HH:MM", drawn only where a stored reading this build
   can read stands: a refused or malformed one says so in its own section, and a last run nothing shows would
   point at nothing. */
export function DriftStamp() {
  const { model } = useDrift();
  const { annotate, raw, shape } = model;
  if (!annotate || !raw || !shape || shape.malformed) return null;
  const line = lastRunLine(shape.stamp, nextNumber(raw['read_at']));
  if (!line) return null;
  return (
    <p
      className="m-0 text-label text-[var(--ink-label)] [font-family:var(--mono)]"
      data-next-drift-stamp
    >
      {line}
    </p>
  );
}

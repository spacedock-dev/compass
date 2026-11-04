import { useDrift } from './context';
import { longOutcomeSentence, sessionLongDiagnostic } from './longOutcome';

/** Optional published metadata stays outside the legacy annotation projection. */
export function LatestLongOutcome() {
  const { model } = useDrift();
  const diagnostic = sessionLongDiagnostic(model.session);
  if (!diagnostic) return null;
  const { accounting } = diagnostic;
  const prefix = accounting.state === 'minimum' ? 'at least ' : '';
  const number = (value: number) => value.toLocaleString('en-US');
  return (
    <div data-next-long-outcome="">
      <p className="next-cockpit-reading-why">
        Latest long analysis: {longOutcomeSentence(diagnostic)}
      </p>
      <p className="next-cockpit-reading-job-note">
        {accounting.totals === null
          ? 'Reserved call accounting is unknown.'
          : `Calls reserved: ${prefix}${number(accounting.totals.calls)}. Assembled input reserved: ${prefix}${number(accounting.totals.prompt_bytes)} bytes. Reply space reserved: ${prefix}${number(accounting.totals.reply_bytes)} bytes.`}
      </p>
    </div>
  );
}

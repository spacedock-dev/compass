import { longCoverage } from '../api/longCoverage';
import type { LongStopReason } from '../api/longDiagnostic';

const REASONS: Readonly<Record<LongStopReason, string>> = {
  'resource-limit': 'A resource limit stopped the analysis.',
  'source-changed': 'The source changed during the analysis.',
  'source-gap': 'Source gaps prevented the analysis from covering its saved work.',
  'evidence-gap': 'Some evidence could not be assigned to the analysis.',
  'evidence-pass-failed': 'An evidence pass failed.',
  'final-context-limited': 'Some work could not fit the final comparison.',
  'final-call-failed': 'The final comparison failed.',
  'call-refused': 'An analysis call was refused.',
  'context-changed': 'The analysis context changed.',
  'permission-changed': 'Permission to continue changed.',
  cancelled: 'The analysis was cancelled.',
  shutdown: 'Compass shut down during the analysis.',
  'job-deadline': 'The whole-job deadline stopped the analysis.',
  'accounting-unresolved': 'Recorded call accounting could not be confirmed.',
  'cleanup-unresolved': 'Process cleanup could not be confirmed.',
  unknown: 'Stop or limit reason: unknown.',
};
const number = (value: number | null | undefined) =>
  value == null ? 'unknown' : value.toLocaleString('en-US');

/** Saved measurements only; not current progress, provider usage or all-work coverage proof. */
export function LongCoverage({ value }: { readonly value: unknown }) {
  const measured = longCoverage(value);
  if (!measured) return null;
  const { source, maps, limits } = measured;
  const used = source?.usage;
  return (
    <div data-next-long-coverage="">
      <p className="next-cockpit-reading-why">{REASONS[measured.stop_reason ?? 'unknown']}</p>
      <p className="next-cockpit-reading-job-note">
        {source
          ? `Frozen source extent: ${number(source.frozen_bytes)} bytes. Source files verified: ${number(source.verified_streams)} of ${number(source.frozen_streams)}. Native source verification: ${source.source_verified === null ? 'unknown' : source.source_verified ? 'confirmed' : 'not confirmed'}. Source file details omitted: ${number(source.streams_omitted)}.`
          : 'Source coverage measurements are unknown.'}
      </p>
      {source ? (
        <p className="next-cockpit-reading-job-note">
          {`Source gap records: ${number(source.gap_records)}; additional records omitted: ${number(source.gaps_omitted)}. Inventory gap records: ${number(source.inventory_gap_records)}; additional records omitted: ${number(source.inventory_gaps_omitted)}. `}
          {source.unexpanded_extent_unknown
            ? 'Unexpanded source extent is unknown.'
            : 'No unexpanded source extent reported.'}
        </p>
      ) : null}
      <p className="next-cockpit-reading-job-note">
        {maps
          ? `Evidence passes planned: ${number(maps.planned_passes)}. Evidence ranges: ${number(maps.planned_primary_ranges)} planned; ${number(maps.usable_primary_ranges)} usable; ${number(maps.failed_primary_ranges)} failed; ${number(maps.unassigned_primary_ranges)} unassigned.`
          : 'Evidence range measurements are unknown.'}
      </p>
      <p className="next-cockpit-reading-job-note">
        {`Native source reads: ${number(used?.io_bytes)} / ${number(limits.source_bytes)} bytes (includes verification). Source pages: ${number(used?.pages)} / ${number(limits.source_pages)}.`}
      </p>
      <p className="next-cockpit-reading-job-note">
        {`Preparation measured: ${number(used?.prepare_ms)} / ${number(limits.prepare_ms)} ms (model waits excluded).`}{' '}
        Measured at the saved snapshot of source and analysis preparation.
      </p>
      <p className="next-cockpit-reading-job-note">
        {`Retained object graph: ${number(used?.retained_graph_peak_bytes)} / ${number(limits.retained_bytes)} bytes; ${number(used?.retained_graph_peak_units)} / ${number(limits.retained_units)} objects (not process RSS).`}
      </p>
      <p className="next-cockpit-reading-job-note">
        These counts do not establish that all saved work was assessed.
      </p>
    </div>
  );
}

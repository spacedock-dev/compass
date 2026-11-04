import { longJobProgress, type LongProgress as Progress } from '../api/longProgress';
import type { Row } from '../observed';

const number = (value: number) => value.toLocaleString('en-US');
function stage(progress: Progress): string {
  switch (progress.stage) {
    case 'source':
      return 'Collecting source';
    case 'evidence':
      return progress.evidence.current === null
        ? 'Reading evidence'
        : `Evidence pass ${String(progress.evidence.current)} of ${String(progress.evidence.planned)}`;
    case 'reconciliation':
      return 'Final comparison';
    case 'publication':
      return 'Saving outcome';
  }
}

/** No effect or live region: polling supplies snapshots; announcements have a separate owner. */
export function LongProgress({ job }: { readonly job: Row }) {
  const progress = longJobProgress(job);
  if (progress === null)
    return (
      <p className="next-cockpit-reading-job-note" data-next-long-progress="">
        Long analysis progress is unavailable.
      </p>
    );
  const { source, evidence, accounting } = progress;
  const prefix = accounting.state === 'minimum' ? 'at least ' : '';
  return (
    <div data-next-long-progress="">
      <p className="next-cockpit-reading-job-note">
        <strong>{stage(progress)}</strong>
      </p>
      <p className="next-cockpit-reading-job-note">
        {source.streams_verified === null
          ? 'Source files verified: unknown.'
          : `Source files verified: ${number(source.streams_verified)}${source.streams_total === null ? ' (total unknown)' : ` of ${number(source.streams_total)}`}.`}
        {source.bytes_read === null
          ? ' Source bytes read: unknown.'
          : ` Source bytes read: ${number(source.bytes_read)} (includes verification).`}
      </p>
      <p className="next-cockpit-reading-job-note">
        {evidence.planned === null
          ? 'Evidence pass count: unknown.'
          : `Evidence passes finished: ${String(evidence.ended)} of ${String(evidence.planned)}.`}
      </p>
      <p className="next-cockpit-reading-job-note">
        {accounting.totals === null
          ? 'Reserved call accounting is unknown.'
          : `Calls reserved: ${prefix}${number(accounting.totals.calls)}. Assembled input reserved: ${prefix}${number(accounting.totals.prompt_bytes)} bytes. Reply space reserved: ${prefix}${number(accounting.totals.reply_bytes)} bytes.`}
      </p>
      <p className="next-cockpit-reading-job-note">
        Reservations describe input and reply limits. Finished passes may not yield a usable result.
      </p>
    </div>
  );
}

import type { EvidenceRow } from './level';
import { Why } from './Why';

/* The cited entries' own rows: which entry, what it is and when, then what it says, who recorded it and the
   full recorded time, with the source one click away. The scope names the list a row belongs to, so one entry
   cited in two places keeps two independent disclosures. `sources` are the finding's record-type tags, said
   under Source with the entry's own; `quoted` leaves out words a departure's What already quotes. */
export function EvidenceList({
  rows,
  scope,
  sources = [],
  quoted = false,
}: {
  readonly rows: readonly EvidenceRow[];
  readonly scope: string;
  readonly sources?: readonly string[];
  readonly quoted?: boolean;
}) {
  if (!rows.length) return null;
  return (
    <ul className="next-cockpit-assessment-evidence">
      {rows.map((row) => (
        <li key={row.id}>
          <p className="next-cockpit-assessment-entry">{row.shown.head}</p>
          {!quoted && row.shown.summary ? (
            <p className="next-cockpit-reading-evidence">{row.shown.summary}</p>
          ) : null}
          <span className="next-cockpit-reading-evidence">{row.who}</span>
          <span className="next-cockpit-reading-evidence">{`${row.eventLabel} ${row.shown.at}`}</span>
          {row.shown.result ? (
            <span className="next-cockpit-reading-evidence">{row.shown.result}</span>
          ) : null}
          <Why name={`assessment-source:${scope}:${row.id}`} summary="Source">
            {sources.map((line, index) => (
              <p key={index} className="next-cockpit-reading-evidence">
                {line}
              </p>
            ))}
            <p className="next-cockpit-reading-evidence">{row.source}</p>
          </Why>
        </li>
      ))}
    </ul>
  );
}

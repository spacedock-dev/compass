import type { EvidenceRow } from './level';
import { CitedText } from './CitedText';
import { Why } from './Why';

/* The cited entries' own rows: which entry, what it is and when, then what it says, who recorded it and the
   full recorded time, with the source one click away. The scope names the list a row belongs to, so one entry
   cited in two places keeps two independent disclosures. Only the live level's signals draw it now: a claim
   row and a departure card show each cited entry's own words in line, with no fold (owner, 2026-10-23). */
export function EvidenceList({
  rows,
  scope,
}: {
  readonly rows: readonly EvidenceRow[];
  readonly scope: string;
}) {
  if (!rows.length) return null;
  return (
    <ul className="next-cockpit-assessment-evidence">
      {rows.map((row) => (
        <li key={row.id}>
          <p className="next-cockpit-assessment-entry">
            <CitedText text={row.shown.head} />
          </p>
          {row.shown.summary ? (
            <p className="next-cockpit-reading-evidence">{row.shown.summary}</p>
          ) : null}
          <span className="next-cockpit-reading-evidence">{row.who}</span>
          <span className="next-cockpit-reading-evidence">{`${row.eventLabel} ${row.shown.at}`}</span>
          {row.shown.result ? (
            <span className="next-cockpit-reading-evidence">{row.shown.result}</span>
          ) : null}
          <Why name={`assessment-source:${scope}:${row.id}`} summary="Source">
            <p className="next-cockpit-reading-evidence">{row.source}</p>
          </Why>
        </li>
      ))}
    </ul>
  );
}

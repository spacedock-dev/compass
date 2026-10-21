import { RaiseControl, useControls } from '../controls';
import type { Row } from '../observed';
import { LANE_OFF_RECORD, laneOffWhy, unaskedDepartures, type DepartureRow } from './detail';

/* The pieces of the session page that sit beside the Intent panel's reading and are measured evidence in
   their own right: what became of a departure raised to the reader and the way back into the session beside
   it. The Intent step composes them into its
   panel; this step draws them in the panel's slot until that panel exists, so a raise on record is never
   hidden by the panel being absent. Each takes the session row and nothing else it could get wrong. */

/* Terminal raise remains beside each departure when the board can identify its terminal.
   Resume commands live on Attention, the waiting panel and the project rail (DEC-27). */
export function DepartureReentry({ session }: { readonly session: Row }) {
  const controls = useControls();
  const sid = String(session['sid'] || '');
  const raisable =
    session['focusable'] === true &&
    Boolean(sid.trim()) &&
    Boolean(String(session['harness'] == null ? '' : session['harness']).trim()) &&
    controls.focus !== null;
  if (!raisable) return null;
  return (
    <div className="next-departure-reentry" data-next-departure-reentry>
      {raisable ? (
        <RaiseControl harness={String(session['harness']).trim()} sid={sid.trim()} focusable />
      ) : null}
    </div>
  );
}

function DepartureRowView({ row, session }: { readonly row: DepartureRow; readonly session: Row }) {
  return (
    <div className="next-session-departure">
      <div className="next-session-departure-head">
        <span className="next-session-departure-name">{row.constraint}</span>
        {row.at ? <span className="next-session-departure-at">{row.at}</span> : null}
      </div>
      {row.clause ? <span className="next-session-departure-clause">{row.clause}</span> : null}
      <p className="next-session-departure-reading">{row.reading}</p>
      <p className="next-session-departure-base">{row.base}</p>
      {row.stale ? <p className="next-session-departure-stale">{row.stale}</p> : null}
      {row.followUp ? <p className="next-session-departure-next">{row.followUp}</p> : null}
      <DepartureReentry session={session} />
    </div>
  );
}

/* The rows and the absence sentence, in one wording for every surface that shows them. The heading counts,
   and each row says when and against which revision: a raise that did not say which words it read and where
   its evidence stopped cannot be checked by the person it was raised to. Nothing for a session with no
   departure and no sentence about why. */
export function UnaskedDepartureBody({ session }: { readonly session: Row }) {
  const body = unaskedDepartures(session);
  if (!body) return null;
  return (
    <>
      {body.rows.length ? <p className="next-session-departures-count">{body.heading}</p> : null}
      {body.rows.map((row, index) => (
        <DepartureRowView key={index} row={row} session={session} />
      ))}
      {body.why ? <p className="next-session-departures-why">{body.why}</p> : null}
      {body.absence ? <p className="next-session-delivery-why">{body.absence}</p> : null}
    </>
  );
}

/* The departures raised to the reader and the way back beside them, drawn under the label the legacy page
   gives them until the Intent step's panel composes them itself. */
export function DepartureEvidence({
  session,
  laneOn,
  offReason,
}: {
  readonly session: Row;
  readonly laneOn: boolean;
  readonly offReason: unknown;
}) {
  const body = unaskedDepartures(session);
  if (!body) return null;
  return (
    <div className="next-cockpit-departure-part">
      <span className="next-cockpit-departure-label">FROM THE CHECKS RUN WHILE YOU WERE AWAY</span>
      {/* With the lane off the rows are still on the wire, so they are printed with the limit that qualifies them:
          without it the label alone would read as checks that ran while the reader was away. */}
      {laneOn ? null : (
        <>
          <p className="next-cockpit-reading-why" data-absence="run-config">
            {laneOffWhy(offReason)}
          </p>
          <p className="next-cockpit-reading-why" data-absence="run-config">
            {LANE_OFF_RECORD}
          </p>
        </>
      )}
      <UnaskedDepartureBody session={session} />
    </div>
  );
}

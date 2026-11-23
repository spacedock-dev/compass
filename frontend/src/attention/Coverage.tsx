import { useControls } from '../controls';
import type { Observed } from '../observed';
import { FOCUS_OFF_LINE } from '../sessions/detail';
import { AttentionLink } from './AttentionLink';
import type { AttentionModel } from './model';
import type { BoardReports } from './reports';

const plural = (count: number, one: string, many: string): string => (count === 1 ? one : many);

/* How far the raise reaches across the queue, said once. The alternative was a per-row "no terminal", which
   would print on the majority of rows forever: the bit is false for a session outside tmux, one predating
   this server run, and every Linux and Windows session. It sits with the rest of what the board cannot see
   rather than beside the rows it is not about. */
function TerminalCoverage({ model }: { readonly model: AttentionModel }) {
  const controls = useControls();
  const rows = model.needs.filter((subject) => subject.session);
  if (!rows.length) return null;
  if (!controls.focus) return <p>{FOCUS_OFF_LINE}</p>;
  const reached = rows.filter((subject) => subject.session?.['focusable'] === true).length;
  return (
    <p>{`Terminal raise: ${String(reached)} of ${String(rows.length)} ${plural(rows.length, 'waiting row carries', 'waiting rows carry')} a terminal Compass can reach.`}</p>
  );
}

/* What the board could and could not see, per harness and as a whole. The detail is the reader's to open
   and stays as they left it across every revision. */
export function CoverageBlock({
  model,
  observed,
}: {
  readonly model: AttentionModel;
  readonly observed: Observed;
}) {
  const coverage = observed.coverage;
  const previous = model.coverage;
  return (
    <div className="next-attention-coverage">
      <h3>Coverage by agent</h3>
      <p>{coverage.gates}</p>
      <div className="next-attention-coverage-details">
        <ul>
          {coverage.rows.map((row) => (
            <li key={row.key} data-next-coverage-harness={row.key}>
              <strong data-authored>{row.label}</strong>
              <span className="next-attention-squares" aria-hidden="true">
                <span className="next-attention-square" data-known={String(row.blockKnown)} />
                <span className="next-attention-square" data-known={String(row.rateKnown)} />
              </span>
              <span>{`${row.blockText} · ${row.rateText}`}</span>
            </li>
          ))}
        </ul>
        <div className="next-attention-caveats">
          {coverage.caveats.map((text) => (
            <p key={text}>{text}</p>
          ))}
          {previous.exactRequestsReported && previous.exactRequestCount === 0 ? (
            <p>No exact requests published.</p>
          ) : null}
          {previous.gates.failed ? (
            <p>{`Harness sources: ${String(previous.gates.failed)} failed.`}</p>
          ) : null}
          {previous.observedStops > 0 ? (
            <p>{`Stops observed on ${String(previous.observedStops)} ${plural(previous.observedStops, 'session', 'sessions')}; fleet coverage not reported.`}</p>
          ) : null}
          <p>
            {previous.observedEnds > 0
              ? `Ends observed on ${String(previous.observedEnds)} ${plural(previous.observedEnds, 'session', 'sessions')}; `
              : 'No session ends observed; '}
            a session with no observed end is not known to be running.
          </p>
          <TerminalCoverage model={model} />
        </div>
      </div>
    </div>
  );
}

const CAVEATS = (
  <>
    <p>A shape match does not prove the action succeeded.</p>
    <p>
      Claude Code and Codex after-tool hooks only. Reports may repeat or arrive out of order. This
      run keeps up to 1,000 reports, 20 per session, for at most 24 hours; restarting clears them.
    </p>
  </>
);

/* The board's command-shape reports, newest first, each linking to the session that ran the command when
   exactly one session has that pair. Off, or empty, it says which. */
export function CommandReportsSection({ reports }: { readonly reports: BoardReports }) {
  const count = reports.rows.length;
  return (
    <section className="next-attention-section" data-next-command-reports>
      <div className="next-attention-section-heading">
        <h2>Command-shape reports</h2>
        {count ? (
          <p>{`${String(count)} report${count === 1 ? '' : 's'} shown · newest first`}</p>
        ) : null}
      </div>
      {count ? (
        <ol>
          {reports.rows.map((report) => (
            <li key={report.key} className="next-attention-risk-identity">
              <h3 data-authored>
                {report.route ? (
                  <AttentionLink
                    route={report.route}
                    focusKey={`attention:report:${report.key}`}
                    fallback="attention:title"
                  >
                    {report.text}
                  </AttentionLink>
                ) : (
                  report.text
                )}
              </h3>
              <p className="next-attention-risk-source" data-authored>
                {report.source}
              </p>
            </li>
          ))}
        </ol>
      ) : (
        <p>{reports.absent}</p>
      )}
      {CAVEATS}
    </section>
  );
}

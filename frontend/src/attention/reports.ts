import { nextNumber } from '../api/bootstrap';
import { payloadSessionRows, records, type Row } from '../observed';
import { asPayload } from '../observed/values';
import type { RouteInput } from '../router/grammar';
import { formatTimestamp } from '../shell/format';

/* The board's command-shape reports: commands a Claude Code or Codex after-tool hook saw run, matched
   against a shape the run was told to watch for. Attention keeps the whole section, because here the
   reports are the subject; a session's own page tiers them. Off, or with nothing received, it says which,
   because "no reports" under a run that was not collecting them would read as a clean bill. */
export const REPORTS_OFF = 'Command-shape reports are disabled for this run.';
export const REPORTS_NONE =
  'No matching reports received; missing hooks and unmatched commands can look the same.';

/* The most one run publishes per session is twenty, and the board shows no more than that in all. */
export const REPORTS_SHOWN = 20;

export interface BoardReport {
  /** The report's text and which copy of it this is, so a run that publishes one twice keeps two rows. */
  readonly key: string;
  readonly text: string;
  readonly source: string;
  /** The session the report names, when exactly one row of the board has that pair. */
  readonly route: RouteInput | null;
}

export interface BoardReports {
  readonly state: 'off' | 'on';
  readonly absent: string;
  readonly rows: readonly BoardReport[];
}

export function boardReports(input: unknown): BoardReports {
  const payload = asPayload(input);
  const off = payload['irreversible_enabled'] !== true;
  const reports = off ? [] : records(payload['command_reports']).slice(0, REPORTS_SHOWN);
  const sessions = payloadSessionRows(payload);
  const copies = new Map<string, number>();
  return {
    state: off ? 'off' : 'on',
    absent: off ? REPORTS_OFF : REPORTS_NONE,
    rows: reports.map((report: Row) => {
      const owner = sessions.find(
        (source) => source['harness'] === report['harness'] && source['sid'] === report['sid'],
      );
      // A stamp that is no date prints nothing: the page this ports throws on one, which would blank the
      // whole Attention view for one malformed report.
      const stamp = nextNumber(report['timestamp']);
      const when = formatTimestamp(stamp, payload['generated']);
      const origin = `${String(report['harness'])} · ${String(report['sid'])} · ${String(report['tool_name'])}`;
      const identity = `${origin}\u0000${String(stamp)}`;
      const copy = copies.get(identity) ?? 0;
      copies.set(identity, copy + 1);
      return {
        key: `${identity}\u0000${String(copy)}`,
        text: `Command shape reported: ${String(report['label'])}`,
        source: when ? `${origin} · ${when}` : origin,
        route: owner
          ? {
              view: 'session',
              project: owner['project'] == null ? null : String(owner['project']),
              harness: String(owner['harness'] || ''),
              session: String(owner['sid'] || ''),
            }
          : null,
      };
    }),
  };
}

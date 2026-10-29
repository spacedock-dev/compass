import { Alert } from '../ui/alert';
import { Card } from '../ui/card';
import './intent.css';
import { Fragment, useEffect, useMemo } from 'react';
import { payloadSessions } from '../api/bootstrap';
import type { Row } from '../observed';
import { asPayload, sessionKey } from '../observed/values';
import { selectObserved } from '../observed/select';
import { RouteAnchor } from '../sessions/RouteAnchor';
import { useDisplayed, useShell } from '../shell/context';
import { intentLogFor, useIntentLogState } from './logContext';
import { intentLogView, type LogRow } from './logModel';

/* The Intent log: every session the board lists, and every retained annotation record, with the words
   each holds and where they came from. Read-only: nothing here writes, posts or starts a reading. A row
   links to its session by the exact harness and sid and by the session's own project label, which
   controls the link only, so a session with no label still has a page and is never filed as departed. */

/* The observed row that names a session is the one with its exact pair AND its own project label: two
   sessions of one sid in two projects are two titles. */
function titleKey(session: Row): string {
  return `${sessionKey(session)}|${String(session['project'] == null ? '' : session['project'])}`;
}

function RowView({
  row,
  titles,
}: {
  readonly row: LogRow;
  readonly titles: ReadonlyMap<string, string>;
}) {
  const { session } = row;
  return (
    <Card variant="intent-row" className="next-intent-row">
      <span className="next-intent-key">
        {session ? (
          <RouteAnchor
            route={{
              view: 'session',
              project: String(session['project'] == null ? '' : session['project']),
              harness: String(session['harness'] || ''),
              session: String(session['sid'] || ''),
            }}
            extra={{ 'data-next-focus': `intent:${row.key}` }}
          >
            {titles.get(titleKey(session)) ?? ''}
          </RouteAnchor>
        ) : (
          <span className="next-intent-gone">{row.key}</span>
        )}
      </span>
      {row.cells.map((cell, index) => (
        <span
          // The cells are a fixed sequence for one row, so the position is their identity.
          key={index}
          className={
            cell.kind === 'words'
              ? 'next-intent-words'
              : cell.kind === 'why'
                ? 'next-intent-why'
                : cell.kind === 'gone'
                  ? 'next-intent-gone'
                  : 'next-intent-revision'
          }
        >
          {cell.text}
        </span>
      ))}
    </Card>
  );
}

export function IntentLog() {
  const shell = useShell();
  const log = intentLogFor(shell);
  const logged = useIntentLogState(log);
  const data = useDisplayed((snapshot) => snapshot.data);
  const model = useDisplayed(selectObserved);
  const payload = asPayload(data);
  const board: readonly Row[] = useMemo(
    () => (data ? (payloadSessions(data).rows as unknown as Row[]) : []),
    [data],
  );
  /* Only arrival, a changed source, or a failed load due for a retry fetches the words. Unrelated board
     revisions reuse the current log: this runs when the log's own state or the board changes and asks
     for nothing unless the log is unread or failed, and `load` refuses until a failed load is due. */
  const wanted = logged.state === 'unread' || logged.state === 'error';
  // biome-ignore lint/correctness/useExhaustiveDependencies: the log's own state and the board are the triggers, not values the body reads.
  useEffect(() => {
    if (wanted) log.load();
  }, [log, wanted, logged, data]);
  const view = useMemo(
    () => intentLogView({ payload, board, rows: logged.rows, load: logged.state }),
    [payload, board, logged.rows, logged.state],
  );
  const titles = useMemo(
    () =>
      new Map(
        model.sessions.map((row) => [
          `${sessionKey({ harness: row.harness, sid: row.sid })}|${row.project}`,
          row.titleText,
        ]),
      ),
    [model],
  );
  return (
    <section className="next-intent" data-next-view-body="intent">
      <h1>Intent log</h1>
      <Alert as="p" variant="intent-note" announce={false} className="next-intent-note">
        {view.counts}
      </Alert>
      {view.notice ? (
        <Alert as="p" variant="intent-note" announce={false} className="next-intent-note">
          {view.notice}
        </Alert>
      ) : null}
      {view.limits ? (
        <Alert as="p" variant="intent-note" announce={false} className="next-intent-note">
          {view.limits}
        </Alert>
      ) : null}
      {view.groups.map((group) => (
        <Fragment key={group.title}>
          <h2>{group.title}</h2>
          {group.rows.map((row) => (
            <RowView key={row.key} row={row} titles={titles} />
          ))}
        </Fragment>
      ))}
      <Alert as="p" variant="intent-note" announce={false} className="next-intent-note">
        {view.closing}
      </Alert>
    </section>
  );
}

import { useEffect, useId, useMemo, useState } from 'react';
import { payloadSessions } from '../api/bootstrap';
import { Disclosure, useControls } from '../controls';
import { DraftInput } from '../controls/DraftField';
import { useControlledDisclosureState } from '../controls/useDisclosureState';
import { GLOSSARY, SHOWN } from '../language/glossary';
import type { Row } from '../observed';
import { selectObserved } from '../observed/select';
import { asPayload, sessionKey } from '../observed/values';
import { RouteAnchor } from '../sessions/RouteAnchor';
import { useDisplayed, useShell } from '../shell/context';
import { Button } from '../ui/button';
import { Icon } from '../ui/icons';
import { intentLogFor, useIntentLogState } from './logContext';
import { GOAL_HISTORY_LIMITS, intentLogView, type Group, type LogRow } from './logModel';
import './intent.css';

const SEARCH_KEY = 'goal-history-search';
const FIRST_ROWS = 3;

function RowView({ row, title }: { readonly row: LogRow; readonly title: string }) {
  const session = row.session;
  const route = session
    ? {
        view: 'session' as const,
        project: String(session['project'] ?? ''),
        harness: String(session['harness'] ?? ''),
        session: String(session['sid'] ?? ''),
      }
    : null;
  const supplemental = row.outcomes.length > 0;
  return (
    <li className="next-intent-row">
      <div className="min-w-0 flex-1">
        <h3 className="m-0 text-value font-bold">
          {route ? (
            <RouteAnchor
              route={route}
              className="inline-flex items-center font-semibold text-primary"
              extra={{ 'data-authored': '', 'data-next-focus': `intent:${row.key}` }}
              focusKey={`intent:${row.key}`}
              fallback={SEARCH_KEY}
            >
              {title}
            </RouteAnchor>
          ) : title ? (
            <span data-authored>{title}</span>
          ) : row.goal ? (
            <span data-next-goal-history-words data-authored>
              {row.goal}
            </span>
          ) : (
            'Older session'
          )}
        </h3>
        {row.goal && (route || title) ? (
          <p className="m-0 text-body" data-next-goal-history-words data-authored>
            {row.goal}
          </p>
        ) : null}
        {!route && !title ? (
          <p className="m-0 text-label text-muted-foreground">Session title unavailable.</p>
        ) : null}
        {row.absence ? <p className="m-0 text-body text-muted-foreground">{row.absence}</p> : null}
        {row.source ? (
          <p className="m-0 text-label text-muted-foreground" data-next-goal-history-source>
            {row.source}
            {session?.['project'] ? (
              <span data-authored>{` · ${String(session['project'])}`}</span>
            ) : null}
          </p>
        ) : null}
        {row.additionalGoals.map(({ goal, source, time }, index) => (
          <div key={index}>
            <p className="m-0 text-body" data-next-goal-history-words data-authored>
              {goal}
            </p>
            <p className="m-0 text-label text-muted-foreground">
              {source} · {time}
            </p>
          </div>
        ))}
        {row.caveats.map((text) => (
          <p className="m-0 text-label text-muted-foreground" key={text}>
            {text}
          </p>
        ))}
        {supplemental ? (
          <Disclosure
            disclosureKey={`goal-history-outcome:${row.key}`}
            summary={GLOSSARY.doneLooksLike.shown}
          >
            <ul className="pl-5">
              {row.outcomes.map(({ k, text }) => (
                <li key={k} data-authored>
                  {text}
                </li>
              ))}
            </ul>
          </Disclosure>
        ) : null}
      </div>
      {row.time ? <span className="text-label text-muted-foreground">{row.time}</span> : null}
      {row.canAdd && route ? (
        <RouteAnchor
          route={route}
          className="inline-flex items-center rounded-control border border-[var(--line)] px-3 text-body font-semibold text-foreground no-underline"
        >
          Add a goal
        </RouteAnchor>
      ) : null}
    </li>
  );
}

function namedKey(session: Row): string {
  return `${sessionKey(session)}|${String(session['project'] ?? '')}`;
}

function GoalGroup({ group }: { readonly group: Group }) {
  const { disclosures } = useControls();
  const key = `goal-history:${group.id}`;
  const expanded = useControlledDisclosureState(disclosures, key);
  const listId = useId();
  const rows = group.rows;
  const remainder = rows.length - FIRST_ROWS;
  if (!rows.length) return null;
  return (
    <section className="next-intent-group" data-next-goal-group={group.id}>
      <h2 className="m-0 px-4 pt-4 text-value font-bold">{group.title}</h2>
      <ul id={listId} className="m-0 list-none p-0">
        {(expanded ? rows : rows.slice(0, FIRST_ROWS)).map((row) => (
          <RowView key={row.key} row={row} title={row.title} />
        ))}
      </ul>
      {remainder > 0 ? (
        <Button
          type="button"
          className="mx-4 mb-4"
          aria-expanded={expanded}
          aria-controls={listId}
          onClick={() => disclosures.set(key, !expanded)}
        >
          {expanded ? 'Show fewer' : `Show ${remainder} more`}
        </Button>
      ) : null}
    </section>
  );
}

export function IntentLog() {
  const shell = useShell();
  const log = intentLogFor(shell);
  const logged = useIntentLogState(log);
  const data = useDisplayed((snapshot) => snapshot.data);
  const observed = useDisplayed(selectObserved);
  const [search, setSearch] = useState('');
  const wanted = logged.state === 'unread' || logged.state === 'error';
  // biome-ignore lint/correctness/useExhaustiveDependencies: a board redraw is an opportunity for a due retry.
  useEffect(() => {
    if (wanted) log.load();
  }, [log, wanted, logged, data]);
  const view = useMemo(
    () =>
      intentLogView({
        payload: asPayload(data),
        board: data ? (payloadSessions(data).rows as unknown as Row[]) : [],
        rows: logged.rows,
        load: logged.state,
      }),
    [data, logged],
  );
  const titles = useMemo(
    () => new Map(observed.sessions.map((row) => [namedKey(row), row.titleText])),
    [observed],
  );
  const query = search.trim().toLocaleLowerCase();
  const groups = view.groups.map((group) => ({
    ...group,
    rows: group.rows.flatMap((row) => {
      const title = row.session ? (titles.get(namedKey(row.session)) ?? row.title) : row.title;
      return [row.goal, row.title, title, ...row.additionalGoals.map(({ goal }) => goal)].some(
        (text) => text.toLocaleLowerCase().includes(query),
      )
        ? [{ ...row, title }]
        : [];
    }),
  }));
  const hasMatch = groups.some(({ rows }) => rows.length > 0);
  return (
    <section className="next-intent" data-next-view-body="intent">
      <header className="flex flex-wrap items-center justify-between gap-4">
        <h1 className="m-0 text-hero font-bold">{SHOWN.intent}</h1>
        <div className="relative min-w-0 basis-80">
          <Icon
            name="search"
            className="pointer-events-none absolute start-3 top-4 text-muted-foreground"
          />
          <DraftInput
            type="search"
            memoryKey={SEARCH_KEY}
            focusKey={SEARCH_KEY}
            aria-label="Search goals"
            placeholder="Search goals"
            autoComplete="off"
            onInput={(event) => setSearch(event.currentTarget.value)}
            className="min-h-[48px] ps-9"
          />
        </div>
      </header>
      {!data || view.notice ? (
        <p className="m-0 text-muted-foreground">{data ? view.notice : SHOWN.waitingForBoard}</p>
      ) : null}
      {data &&
      query &&
      !hasMatch &&
      (!view.notice || view.groups.some(({ rows }) => rows.length > 0)) ? (
        <p role="status">No goals or session titles match your search.</p>
      ) : null}
      {data && !query && !hasMatch && !view.notice ? <p>No goals or sessions to show.</p> : null}
      {groups.map((group) => (
        <GoalGroup key={group.id} group={group} />
      ))}
      <Disclosure
        disclosureKey="goal-history:retention"
        summary="How long goals are kept"
        className="next-intent-group px-4"
        searchable={false}
      >
        {GOAL_HISTORY_LIMITS.map((text) => (
          <p key={text}>{text}</p>
        ))}
      </Disclosure>
    </section>
  );
}

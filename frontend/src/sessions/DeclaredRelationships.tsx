import type { Row, ObservedSession } from '../observed';
import { rowState } from './rows';
import { declaredRelations, groupLabel } from './declared';
import { RouteAnchor } from './RouteAnchor';

export function RelationshipLabels({
  source,
  relations,
  focusScope,
  fallback = 'session-title',
}: {
  readonly focusScope: string;
  readonly fallback?: string;
  readonly source: Row | undefined;
  readonly relations: ReturnType<typeof declaredRelations>;
}) {
  return (
    <>
      {groupLabel(source) ? (
        <span className="mt-1 block text-label text-muted-foreground [overflow-wrap:anywhere]">
          {groupLabel(source)}
        </span>
      ) : null}
      {relations.parentText ? (
        <span className="mt-1 block text-label text-muted-foreground">
          {relations.parent ? (
            <RouteAnchor
              className="relative z-[1]"
              route={relations.parent.route}
              focusKey={`${focusScope}:parent`}
              fallback={fallback}
            >
              {relations.parentText}
            </RouteAnchor>
          ) : (
            relations.parentText
          )}
        </span>
      ) : null}
    </>
  );
}

export function WaitingChild({
  relations,
  focusScope,
  fallback = 'session-title',
}: {
  readonly focusScope: string;
  readonly fallback?: string;
  readonly relations: ReturnType<typeof declaredRelations>;
}) {
  return relations.waiting ? (
    <RouteAnchor
      className="relative z-[1]"
      route={relations.waiting.route}
      focusKey={`${focusScope}:waiting`}
      fallback={fallback}
    >
      {relations.waitingText}
    </RouteAnchor>
  ) : (
    <>{relations.waitingText}</>
  );
}

export function LinkedChildren({
  relations,
  sessions,
}: {
  readonly sessions: readonly ObservedSession[];
  readonly relations: ReturnType<typeof declaredRelations>;
}) {
  if (!relations.children.length) return null;
  const states = new Map(
    sessions.map((session) => [`${session.harness}:${session.sid}`, rowState(session)]),
  );
  return (
    <section aria-label="Linked children" className="my-3 text-body">
      <h2 className="text-label font-semibold">Linked children</h2>
      <ul>
        {relations.children.map((child) => (
          <li key={child.key}>
            <RouteAnchor
              route={child.route}
              focusKey={`linked-child:${child.key}`}
              fallback="session-title"
            >
              {child.title}
            </RouteAnchor>
            {' · '}
            {states.get(child.key) ?? 'State not published'}
          </li>
        ))}
      </ul>
    </section>
  );
}

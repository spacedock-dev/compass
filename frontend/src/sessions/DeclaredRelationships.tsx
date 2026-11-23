import { trimmed, type Row, type ObservedSession } from '../observed';
import type { SessionLink } from '../observed/relationships';
import { rowState } from './rows';
import { declaredRelations, groupLabelParts } from './declared';
import { RouteAnchor } from './RouteAnchor';

function RelationshipTitle({ target }: { readonly target: SessionLink }) {
  return (
    <span data-authored={Boolean(trimmed(target.source['title'])) || undefined}>
      {target.title}
    </span>
  );
}

export function RelationshipLabels({
  source,
  relations,
  focusScope,
  waitingIsState = false,
  fallback = 'session-title',
}: {
  readonly focusScope: string;
  readonly waitingIsState?: boolean;
  readonly fallback?: string;
  readonly source: Row | undefined;
  readonly relations: ReturnType<typeof declaredRelations>;
}) {
  const group = groupLabelParts(source);
  return (
    <>
      {group ? (
        <span className="mt-1 block text-label text-muted-foreground [overflow-wrap:anywhere]">
          {group.prefix}
          <span data-authored>{group.name}</span>
          {group.suffix}
        </span>
      ) : null}
      {relations.parentText ? (
        <span className="mt-1 block text-label text-muted-foreground">
          {relations.parent ? (
            <RouteAnchor
              className="relative z-[1]"
              route={relations.parent.route}
              label={relations.parentText}
              focusKey={`${focusScope}:parent`}
              fallback={fallback}
            >
              {'Child of '}
              <RelationshipTitle target={relations.parent} />
            </RouteAnchor>
          ) : (
            relations.parentText
          )}
        </span>
      ) : null}
      {relations.waitingText ? (
        <span
          className="mt-1 block text-label text-muted-foreground"
          data-next-row-state={waitingIsState ? 'Waiting on child' : undefined}
        >
          <WaitingChild relations={relations} focusScope={focusScope} fallback={fallback} />
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
      label={relations.waitingText}
      focusKey={`${focusScope}:waiting`}
      fallback={fallback}
    >
      {'Waiting on child "'}
      <RelationshipTitle target={relations.waiting} />
      {'"'}
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
              <RelationshipTitle target={child} />
            </RouteAnchor>
            {' · '}
            {states.get(child.key) ?? 'State not published'}
          </li>
        ))}
      </ul>
    </section>
  );
}

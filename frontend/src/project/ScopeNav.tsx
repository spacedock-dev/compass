import { Icon } from '../ui/icons';
import { Disclosure, disclosureKey } from '../controls';
import { useFocusKey } from '../controls/useFocusKey';
import { useShell } from '../shell/context';
import { ScopeCue } from '../timeline/ScopeCue';
import { scopeLabel, sessKey } from './group';
import type { ProjectModel } from './model';
import { ProjectAnchor } from './parts';
import { hoistedHarness, scopeLinks, viewingSession, type ScopeLink } from './scope';

/* The project's scopes as links: the project as a whole, and each of its sessions. The root and one exact
   focused session are different scopes, so they draw different cues, on the wide page's rail and in the
   compact page's disclosure alike; both read the one list. Choosing a scope keeps the tab the reader is
   on. A focus the board no longer holds is not drawn as a link at all: the page says it is outside the
   payload window instead (the shell's stale-focus view). Ported from `nextCockpitScopeLinks`. */

function Link({
  link,
  model,
  surface,
}: {
  readonly link: ScopeLink;
  readonly model: ProjectModel;
  readonly surface: 'tree' | 'switcher';
}) {
  const { controls } = useShell();
  const { route } = model;
  const selected = model.focus ? sessKey(model.focus) : 'project';
  const ref = useFocusKey<HTMLAnchorElement>(
    controls.focusLane,
    `cockpit-scope:${surface}:${link.key}`,
  );
  const target = {
    view: 'project',
    project: route.project,
    focus: link.key === 'project' ? null : link.key,
    tab: route.tab ?? 'now',
  } as const;
  const { meta } = link;
  return (
    <ProjectAnchor
      route={target}
      linkRef={ref}
      extra={{
        'data-next-cockpit-scope': link.key,
        'data-scope-kind': link.scope.kind,
        'data-scope-owner': link.scope.owner || 'unknown',
        ...(selected === link.key ? { 'aria-current': 'page' } : {}),
        ...(link.isWorking ? { 'data-next-working': 'true' } : {}),
      }}
    >
      {link.scope.kind === 'session' ? null : (
        <ScopeCue scope={{ kind: link.scope.kind, owner: link.scope.owner }} />
      )}
      <span className="next-cockpit-scope-line">
        {link.scope.kind === 'session' ? (
          <>
            <span className="next-cockpit-scope-mark" aria-hidden="true">
              <i className="next-scope-marker next-scope-marker--round" />
            </span>
            <span className="next-visually-hidden">SESSION</span>
          </>
        ) : null}
        <span
          className="next-cockpit-scope-title"
          title={link.title}
          {...(link.withheld ? { 'data-next-withheld': '' } : {})}
        >
          {link.title}
        </span>
      </span>
      {meta ? (
        <span className="next-cockpit-scope-meta">
          {[
            meta.harness ? <span key="harness">{meta.harness}</span> : null,
            meta.label ? (
              <span
                key="state"
                className={
                  link.isWorking
                    ? 'next-cockpit-scope-state next-cockpit-scope-state--working'
                    : 'next-cockpit-scope-state'
                }
              >
                {link.isWorking ? (
                  <span className={link.isLive ? 'next-live inline-flex' : 'inline-flex'}>
                    <Icon name="working" className="next-status-icon shrink-0" />
                  </span>
                ) : null}
                {meta.label}
              </span>
            ) : null,
            meta.age ? <span key="age">{meta.age}</span> : null,
            meta.sid ? <span key="sid">{meta.sid}</span> : null,
          ]
            .filter(Boolean)
            .flatMap((part, index) => (index === 0 ? [part] : [' · ', part]))}
        </span>
      ) : (
        <span className="next-cockpit-scope-meta">{link.count}</span>
      )}
      {link.limit ? <span className="next-project-session-limit">{link.limit}</span> : null}
    </ProjectAnchor>
  );
}

function Heading({ model }: { readonly model: ProjectModel }) {
  const hoisted = hoistedHarness(model.group, model.harnesses);
  return (
    <span className="next-cockpit-scope-heading">{`SCOPE${hoisted ? ` · ${hoisted}` : ''}`}</span>
  );
}

export function ScopeTree({ model }: { readonly model: ProjectModel }) {
  const links = scopeLinks(model.group, model.harnesses, model.generated);
  return (
    <nav className="next-cockpit-scope-tree" aria-label="Project scope">
      <Heading model={model} />
      {links.map((link, index) => (
        // The same pair twice is a malformed board, and the list still needs two keys.
        <Link key={`${link.key}#${String(index)}`} link={link} model={model} surface="tree" />
      ))}
    </nav>
  );
}

export function ScopeSwitcher({ model }: { readonly model: ProjectModel }) {
  const links = scopeLinks(model.group, model.harnesses, model.generated);
  const focused = model.focus ? viewingSession(model.focus, model.group, model.harnesses) : null;
  const summary = focused?.label ?? `Viewing project · ${scopeLabel(model.group)}`;
  return (
    <Disclosure
      disclosureKey={disclosureKey({
        project: model.route.project,
        scope: model.route.focus ?? '',
        name: 'scope',
      })}
      className="next-cockpit-scope-switcher"
      focusKey="cockpit-disclosure:scope"
      summary={
        <>
          <span>
            {summary}
            {focused?.state ? (
              <span data-next-project-focus-status>{` · ${focused.state}`}</span>
            ) : null}
          </span>
          <strong>Change scope</strong>
        </>
      }
    >
      <nav className="next-cockpit-scope-options" aria-label="Change project scope">
        <Heading model={model} />
        {links.map((link, index) => (
          <Link key={`${link.key}#${String(index)}`} link={link} model={model} surface="switcher" />
        ))}
      </nav>
    </Disclosure>
  );
}

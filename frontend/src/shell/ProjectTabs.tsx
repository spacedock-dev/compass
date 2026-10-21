import { Tabs, TabsList, TabsTrigger } from '../ui/tabs';
import { useState, type ReactNode } from 'react';
import { useFocusKey } from '../controls/useFocusKey';
import { cockpitTabs, type ProjectRoute, type ProjectTab } from '../router/grammar';
import { useNavigate, useShell } from './context';

const label = (tab: string): string => (tab ? (tab[0] ?? '').toUpperCase() + tab.slice(1) : 'Work');

/* Every mounted strip takes its own prefix, so two project views on one page never share a tab or panel id.
   A counter rather than `useId`: `useId` is unique only within one React root, and two views mounted into
   separate roots would otherwise generate the same ids. */
let mountedStrips = 0;

function Tab({
  prefix,
  tab,
  selected,
  cue,
}: {
  readonly prefix: string;
  readonly tab: ProjectTab;
  readonly selected: boolean;
  readonly cue: ReactNode;
}) {
  const { controls } = useShell();
  const ref = useFocusKey<HTMLButtonElement>(controls.focusLane, `cockpit-tab:${tab}`);
  return (
    <TabsTrigger
      value={tab}
      ref={ref}
      type="button"
      role="tab"
      id={`${prefix}-tab-${tab}`}
      data-next-cockpit-action="tab"
      data-arg={tab}
      // Only the tab whose panel is drawn names it: an unselected tab would point at an element that is not there.
      aria-controls={selected ? `${prefix}-panel-${tab}` : undefined}
      aria-selected={selected}
      tabIndex={selected ? 0 : -1}
    >
      {label(tab)}
      {cue}
    </TabsTrigger>
  );
}

/* The project's tab strip and the one panel that is current. The route holds the selected tab (Now is
   the default and is not printed), and the arrow keys wrap over the list the strip drew, because a wrap
   over a list the nav did not render would move focus to a tab that is not on the reader's screen. The
   panel's body belongs to the views that fill it. */
export function ProjectTabs({
  route,
  cue,
  children,
}: {
  readonly route: ProjectRoute;
  /** What a tab's own count says, drawn inside its button: the project views supply it, a bare strip has none. */
  readonly cue?: (tab: ProjectTab) => ReactNode;
  readonly children: (tab: ProjectTab) => ReactNode;
}) {
  const navigate = useNavigate();
  const { controls } = useShell();
  const [prefix] = useState(() => {
    mountedStrips += 1;
    return `next-cockpit-${String(mountedStrips)}`;
  });
  const tabs = cockpitTabs(route.focus);
  const selected = route.tab && tabs.includes(route.tab) ? route.tab : 'now';
  const open = (tab: ProjectTab) =>
    navigate({ view: 'project', project: route.project, focus: route.focus ?? null, tab });

  return (
    <Tabs value={selected} onValueChange={(value) => open(value as ProjectTab)}>
      <TabsList
        activateOnFocus
        render={<nav />}
        className="next-cockpit-tabs"
        role="tablist"
        aria-label="Project cockpit views"
        onKeyDown={(event) => {
          if (event.key !== 'Home' && event.key !== 'End') return;
          if (event.altKey || event.ctrlKey || event.metaKey) return;
          const target = event.key === 'Home' ? tabs[0] : tabs[tabs.length - 1];
          if (!target) return;
          // Back can change selection without moving focus; Base UI skips an already-highlighted boundary.
          event.preventDefault();
          event.preventBaseUIHandler();
          open(target);
          controls.focusLane.focus(`cockpit-tab:${target}`);
        }}
      >
        {tabs.map((tab) => (
          <Tab
            key={tab}
            prefix={prefix}
            tab={tab}
            selected={tab === selected}
            cue={cue ? cue(tab) : null}
          />
        ))}
      </TabsList>
      <div
        role="tabpanel"
        id={`${prefix}-panel-${selected}`}
        aria-labelledby={`${prefix}-tab-${selected}`}
      >
        {children(selected)}
      </div>
    </Tabs>
  );
}

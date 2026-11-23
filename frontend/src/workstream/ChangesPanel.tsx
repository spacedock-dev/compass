import { Icon } from '../ui/icons';
import { Button } from '../ui/button';
import { useFocusKey } from '../controls/useFocusKey';
import { fragmentForRoute } from '../router/grammar';
import { useShell } from '../shell/context';
import { useCollapsed } from './collapse';
import { useProjectChanges } from './changes';

/* What changed in this project's sessions, as this tab and the history store observed it: "OBSERVED STATE
   CHANGES". The caption names how far back the evidence reaches and how many of the changes ran without
   the reader, and a project with no change in that reach says so rather than showing a count of nothing.
   The panel is collapsible, one flag for every project, and the reader's choice outlives a reload. Ported
   from `nextProjectChanges`. */

export function ChangesPanel({ project }: { readonly project: string }) {
  const { runtime, controls } = useShell();
  const { collapsed, toggle } = useCollapsed(runtime.storage.workstream);
  const changes = useProjectChanges(project);
  const focusKey = `${fragmentForRoute({ view: 'project', project, tab: null, focus: null }).slice(3)}:changes`;
  const toggleRef = useFocusKey<HTMLButtonElement>(controls.focusLane, focusKey);
  const note = collapsed ? (changes.noteText.split(' · ')[0] ?? '') : changes.noteText;
  return (
    <section
      className="next-workstream"
      {...(collapsed ? { 'data-next-workstream-collapsed': '' } : {})}
    >
      <header className="next-workstream-header">
        <Button
          variant="native"
          ref={toggleRef}
          type="button"
          data-next-workstream-toggle=""
          aria-expanded={!collapsed}
          aria-controls="next-project-changes"
          onClick={toggle}
        >
          <span className="inline-flex items-center gap-1">
            <Icon name={collapsed ? 'caret-right' : 'caret-down'} />
            OBSERVED STATE CHANGES
          </span>
          <small>{note}</small>
        </Button>
      </header>
      {collapsed ? null : (
        <div id="next-project-changes">
          {changes.changes.length ? (
            <ol>
              {changes.changes.map((change, index) => (
                <li
                  key={index}
                  className="next-project-change"
                  data-next-workstream-event={change.kind}
                >
                  <time>{change.at}</time>
                  <span
                    className={`next-project-change-dot${change.filled ? ' next-project-change-dot--unattended' : ''}`}
                    role="img"
                    aria-label={change.filled ? 'unattended' : 'attended'}
                  />
                  <span>{change.label}</span>
                  <span className="next-project-change-harness">{change.harness}</span>
                </li>
              ))}
            </ol>
          ) : (
            <p className="next-workstream-empty">{changes.emptyText}</p>
          )}
        </div>
      )}
    </section>
  );
}

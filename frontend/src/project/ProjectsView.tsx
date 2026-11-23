import { type CSSProperties, type ReactNode, useMemo, useState } from 'react';
import { asPayload } from '../observed/values';
import { Disclosure } from '../controls';
import { TechnicalDetails } from '../controls/TechnicalDetails';
import { RouteLink } from '../shell/RouteLink';
import { stageData } from '../steering/stage';
import { useDisplayed } from '../shell/context';
import { Button } from '../ui/button';
import { Icon, SESSION_STATE_ICONS } from '../ui/icons';
import { Input } from '../ui/input';
import { StatusLegend } from '../ui/status-legend';
import { StatusTile } from '../ui/status-tile';
import { GLOSSARY, SESSION_ROW_WORDS, SHOWN } from '../language/glossary';
import { PROJECT_GROUPS, projectList, type ProjectListRow } from './projectList';

import './project.css';

const INITIAL_RECENT = 3;
type State = keyof typeof SESSION_STATE_ICONS;

const stateLimitsAuthored = (limit: string) => limit.startsWith('Waiting on child');

function ProjectRow({ row }: { readonly row: ProjectListRow }) {
  const hasState = Object.hasOwn(SESSION_STATE_ICONS, row.state);
  return (
    <li className="project-list-item" data-next-project={row.key}>
      <RouteLink
        route={row.key ? { view: 'project', project: row.key } : { view: 'sessions' }}
        className="project-list-row"
      >
        {hasState ? (
          <StatusTile state={row.state as State} focusable={false} />
        ) : (
          <span className="project-list-no-icon" />
        )}
        <span className="project-list-identity">
          <strong data-authored>{row.name}</strong>
          {row.headline ? (
            <span>
              {row.headlineIsEarlier ? 'Earlier instruction: ' : null}
              <span data-authored>{row.headline}</span>
            </span>
          ) : null}
          {row.limits.map((limit) => (
            <span key={limit} data-authored={stateLimitsAuthored(limit) || undefined}>
              {limit}
            </span>
          ))}
          {row.location ? <span>{row.location}</span> : null}
        </span>
        <span className="project-list-chips">
          {row.counts.map(({ word, count }) => {
            const flag = word === SESSION_ROW_WORDS.worthALook;
            return (
              <span
                key={word}
                role="img"
                aria-label={`${String(count)} ${word.toLowerCase()}`}
                className="project-list-chip"
                data-project-count={flag ? 'flag' : SESSION_STATE_ICONS[word]}
              >
                <Icon name={flag ? 'worth-a-look' : SESSION_STATE_ICONS[word]} size={14} />
                {count}
              </span>
            );
          })}
        </span>
        <span className="project-list-meta">
          <span>{row.sessions === 1 ? '1 session' : `${String(row.sessions)} sessions`}</span>
          {row.time ? <span className="project-list-time">{row.time}</span> : null}
        </span>
        <Icon name="caret-right" className="project-list-chevron" />
      </RouteLink>
    </li>
  );
}

export interface ProjectsViewProps {
  readonly conditions?: ReactNode;
}

export function ProjectsView({ conditions = null }: ProjectsViewProps) {
  const data = useDisplayed((snapshot) => snapshot.data);
  const rows = useMemo(() => projectList(asPayload(data)), [data]);
  const [query, setQuery] = useState('');
  const [expanded, setExpanded] = useState(false);
  const needle = rows.length > 6 ? query.trim().toLowerCase() : '';
  const matches = rows.filter((row) =>
    `${row.name} ${row.headline}`.toLowerCase().includes(needle),
  );
  const lines = matches.reduce(
    (max, row) =>
      Math.max(
        max,
        1 + Number(Boolean(row.headline)) + row.limits.length + Number(Boolean(row.location)),
      ),
    1,
  );
  return (
    <section className="next-projects projects-list" data-next-view-body="projects">
      <header>
        <h1 className="text-hero font-extrabold">{SHOWN.projects}</h1>
        <p>Sessions grouped by the folders their agents report.</p>
      </header>
      {rows.length === 1 ? (
        <div className="project-list-single">
          <p>The board shows one project label. You can see these sessions together on Sessions.</p>
          <RouteLink route={{ view: 'sessions' }}>Go to Sessions</RouteLink>
        </div>
      ) : null}
      {rows.length > 6 ? (
        <Input
          type="search"
          aria-label="Search projects"
          placeholder="Search projects"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
      ) : null}
      <div className="project-list-board" style={{ '--project-row-lines': lines } as CSSProperties}>
        <StatusLegend />
        {matches.length ? (
          PROJECT_GROUPS.map((group, index) => {
            const grouped = matches.filter((row) => row.group === group);
            const hidden = index === 1 ? Math.max(0, grouped.length - INITIAL_RECENT) : 0;
            const visible = hidden && !expanded ? grouped.slice(0, INITIAL_RECENT) : grouped;
            const id = index === 0 ? 'projects-active' : 'projects-recent';
            return grouped.length ? (
              <section key={group} aria-labelledby={id}>
                <h2 id={id}>
                  {group} · {grouped.length}
                </h2>
                <ul aria-labelledby={id}>
                  {visible.map((row) => (
                    <ProjectRow key={row.key} row={row} />
                  ))}
                </ul>
                {hidden ? (
                  <Button
                    emphasis="quiet"
                    type="button"
                    aria-expanded={expanded}
                    className="project-list-more"
                    onClick={() => setExpanded(!expanded)}
                  >
                    {expanded ? 'Show fewer' : `Show ${String(hidden)} more`}
                  </Button>
                ) : null}
              </section>
            ) : null;
          })
        ) : (
          <p className="project-list-empty">
            {rows.length ? 'No project matches.' : 'No projects in the current board.'}
          </p>
        )}
      </div>
      <Disclosure
        disclosureKey="projects:grouping"
        summary={GLOSSARY.howProjectGroupingWorks.plain}
        explanation
      >
        <p>
          Each project uses the folder label its agents report. Sessions without a label appear
          together under Unnamed folder.
        </p>
      </Disclosure>
      {conditions && stageData(data).enabled ? (
        <TechnicalDetails disclosureKey="projects:conditions" caption="Stage conditions">
          {conditions}
        </TechnicalDetails>
      ) : null}
    </section>
  );
}

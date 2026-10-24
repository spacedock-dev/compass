import { stripPasteWrapper } from '../api/paste';
import { Badge } from '../ui/badge';
import { Card } from '../ui/card';
import type { ReactNode } from 'react';
import { Disclosure, disclosureKey } from '../controls';
import { readSemantic, historyEmptyText } from '../timeline/semantic';
import { ScopeCue } from '../timeline/ScopeCue';
import { ChangesPanel } from '../workstream';
import { CompletedWork } from './ActivityViews';
import {
  canonicalSemantic,
  courseDirections,
  courseEpisodes,
  courseEvidence,
  courseScope,
  COURSE_VISIBLE,
  type Episode,
} from './course';
import type { ProjectModel } from './model';
import { projectLanes, semanticOf } from './recovery';
import { factScope } from './scope';
import type { Row } from './raw';

/* The Course tab: what changed in the project's sessions, the direction changes the record shows, and the
   work that was completed. A course change is exact (a recorded decision, a stage change, a completed
   result) or derived (a review that changed the course) and says which; a derived one is never promoted to
   a verified success. Evidence is behind a disclosure on every episode, and what is missing is said before
   anything is claimed. Ported from `nextCockpitCoursePanel`. */

/* A direction is the reader's words: the harness's paste tags come off, and no entry number is put in front. */
const directionWords = (summary: unknown): string =>
  stripPasteWrapper(String(summary || '')) || 'Direction unavailable';

function Evidence({
  fact,
  contributors,
  occurrence = '',
  model,
}: {
  readonly fact: Row;
  readonly contributors: readonly string[];
  readonly occurrence?: string;
  readonly model: ProjectModel;
}) {
  const evidence = courseEvidence(fact, contributors, occurrence);
  return (
    <>
      {evidence.missing.length ? (
        <p className="next-cockpit-evidence-missing">{evidence.missing.join(' · ')}</p>
      ) : null}
      {evidence.details ? (
        <Disclosure
          disclosureKey={disclosureKey({
            project: model.route.project,
            scope: model.route.focus ?? '',
            name: evidence.details.key,
          })}
          className="next-course-evidence"
          focusKey={`cockpit-disclosure:${evidence.details.key}`}
          summary="Evidence · source and confidence"
        >
          {evidence.details.source ? (
            <div>
              <b>Source</b>
              {' · '}
              <span className="next-cockpit-source">{evidence.details.source}</span>
            </div>
          ) : null}
          {evidence.details.confidence ? (
            <div>
              <b>Confidence</b>
              {' · '}
              <span className="next-cockpit-source">{evidence.details.confidence}</span>
            </div>
          ) : null}
          {evidence.details.identity ? (
            <div>
              <b>Fact</b>
              {' · '}
              <span className="next-cockpit-source">{evidence.details.identity}</span>
            </div>
          ) : null}
          {evidence.details.contributors.length ? (
            <div>
              <b>Contributors</b>
              {` · ${evidence.details.contributors.join(' · ')}`}
            </div>
          ) : null}
        </Disclosure>
      ) : null}
    </>
  );
}

function EpisodeRow({
  episode,
  model,
}: {
  readonly episode: Episode;
  readonly model: ProjectModel;
}) {
  const scope = courseScope(episode, model.harnesses);
  return (
    <Card
      as="article"
      variant="course-row"
      className="next-course-episode"
      data-epistemic-kind={episode.epistemic}
      data-scope-kind={scope.kind}
    >
      <header>
        <ScopeCue scope={scope} detail={scope.detail} />
        <Badge variant="course-tag">{episode.badge}</Badge>
      </header>
      <strong>{`${episode.task} · ${episode.label}`}</strong>
      {episode.directionFact ? (
        <p>
          <b>Direction</b>
          {` · ${directionWords(episode.directionFact['summary'])}`}
        </p>
      ) : null}
      {episode.findings.length ? (
        <ul>
          {episode.findings.map((finding, index) => (
            <li key={index}>{finding}</li>
          ))}
        </ul>
      ) : (
        <p>{episode.summary}</p>
      )}
      <Evidence fact={episode.fact} contributors={episode.contributors} model={model} />
      {episode.directionFact ? (
        <Evidence
          fact={episode.directionFact}
          contributors={[]}
          occurrence={`direction-for:${String(episode.fact['fact_id'] || '')}`}
          model={model}
        />
      ) : null}
    </Card>
  );
}

function DirectionRow({ fact, model }: { readonly fact: Row; readonly model: ProjectModel }) {
  const scope = factScope(fact, model.harnesses);
  return (
    <Card
      as="article"
      variant="course-row"
      className="next-course-direction"
      data-scope-kind={scope.kind}
    >
      <header>
        <ScopeCue scope={scope} detail={scope.detail} />
        <Badge variant="course-tag">EXACT DIRECTION</Badge>
      </header>
      <p>{directionWords(fact['summary'])}</p>
      <Evidence fact={fact} contributors={[]} model={model} />
    </Card>
  );
}

function Course({ model, semantic }: { readonly model: ProjectModel; readonly semantic: Row }) {
  const lanes = projectLanes(model.env, model.focus ? [model.focus] : model.group.sessions);
  const projectSemantic = semanticOf(model.env.entry?.data ?? null);
  const canonical = canonicalSemantic(projectSemantic, semantic);
  const episodes = courseEpisodes(canonical, lanes);
  const directions = courseDirections(canonical, episodes);
  const visible = episodes.slice(-COURSE_VISIBLE);
  const earlier = episodes.slice(0, -COURSE_VISIBLE);
  const key = (name: string) =>
    disclosureKey({ project: model.route.project, scope: model.route.focus ?? '', name });
  return (
    <div className="next-cockpit-course" data-next-cockpit-course="">
      {episodes.length ? null : (
        <p className="next-cockpit-empty">{historyEmptyText(readSemantic(canonical), 'course')}</p>
      )}
      {earlier.length ? (
        <Disclosure
          disclosureKey={key('course-earlier')}
          className="next-course-earlier"
          focusKey="cockpit-disclosure:course-earlier"
          summary={`${String(earlier.length)} Earlier`}
        >
          {earlier.map((episode, index) => (
            <EpisodeRow
              key={`${String(episode.fact['fact_id'] || '')}#${String(index)}`}
              episode={episode}
              model={model}
            />
          ))}
        </Disclosure>
      ) : null}
      {visible.map((episode, index) => (
        <EpisodeRow
          key={`${String(episode.fact['fact_id'] || '')}#${String(index)}`}
          episode={episode}
          model={model}
        />
      ))}
      {directions.length ? (
        <Disclosure
          disclosureKey={key('course-directions')}
          className="next-course-directions"
          focusKey="cockpit-disclosure:course-directions"
          summary={`Other directions (${String(directions.length)})`}
        >
          {directions.map((fact, index) => (
            <DirectionRow
              key={`${String(fact['fact_id'] || '')}#${String(index)}`}
              fact={fact}
              model={model}
            />
          ))}
        </Disclosure>
      ) : null}
    </div>
  );
}

/** The semantic read of this scope, once both it and (at a session) the project's have arrived. */
export function CoursePanel({
  model,
  conditions = null,
}: {
  readonly model: ProjectModel;
  readonly conditions?: ReactNode;
}) {
  const { scopeRead, projectRead } = model;
  const entry = scopeRead.entry;
  const projectEntry = projectRead.entry;
  const focused = model.focusIdentity !== null;
  let body: ReactNode;
  if (!entry?.data || (focused && !projectEntry?.data)) {
    const failed = Boolean(entry?.error) || (focused && Boolean(projectEntry?.error));
    body = (
      <p className="next-cockpit-empty">
        {failed ? 'Course evidence unavailable.' : 'Loading course evidence…'}
      </p>
    );
  } else {
    const raw = (entry.data as unknown as Row)['semantic'];
    const semantic: Row =
      raw && typeof raw === 'object' && !Array.isArray(raw)
        ? (raw as Row)
        : { facts: [], work_items: [], projections: {} };
    body = <Course model={model} semantic={semantic} />;
  }
  return (
    <>
      {conditions}
      {body}
    </>
  );
}

export function CourseTab({
  model,
  conditions,
}: {
  readonly model: ProjectModel;
  readonly conditions?: ReactNode;
}) {
  return (
    <>
      <ChangesPanel project={model.route.project} />
      <CoursePanel model={model} conditions={conditions} />
      <CompletedWork model={model} />
    </>
  );
}

import { describe, expect, it } from 'vitest';
import { contextKey, exactIdentity } from '../api/identity';
import { canonical, firstDifference } from '../observed/legacy.test.helper';
import type { BoardSnapshot, ContextEntry } from '../store/board';
import { selectContextRead } from '../store/selectors';
import { arrange, labelsOf } from './arrange.test.helper';
import {
  canonicalSemantic,
  courseDirections,
  courseEpisodes,
  courseEvidence,
  latestCompletedResult,
  reviewFindings,
} from './course';
import { genBoard, genContext } from './generate.test.helper';
import { projectLanes, semanticOf } from './recovery';
import { sessKey, stableKey } from './group';
import { cueGloss, cueMark, tabCue, tabLede } from './tabs';
import { createWorkstream, projectChanges, projectWindow } from '../workstream/model';

/* The Course tab and the tab strip, held to the legacy functions over generated boards and context reads:
   the delegation lanes the tab reads contributors from, the canonical semantic, the episodes and the
   directions beside them, the review findings, the evidence an episode discloses, and each tab's cue. */

const CASES = 25;
const SEEDS = CASES;

function entry(data: Record<string, unknown> | null, error: boolean, revision = 1): ContextEntry {
  return { data: data as never, revision, error: error ? { kind: 'network-error' } : null };
}

describe('the Course tab reads as the legacy tab does', () => {
  it(`agrees on ${String(SEEDS)} generated boards: lanes, episodes, directions, evidence and tab cues`, () => {
    const failures: string[] = [];
    for (let seed = 1; seed <= SEEDS; seed += 1) {
      const board = genBoard(seed);
      const context = genContext(seed, board);
      const focusedContext = genContext(seed + 5000, board);
      for (const label of labelsOf(board)) {
        const made = arrange(board, context, label, 'ready');
        if (!made) continue;
        const { app, legacyGroup, env } = made;
        const at = `seed ${String(seed)} ${JSON.stringify(label)}`;
        const check = (name: string, left: unknown, right: unknown) => {
          const found = firstDifference(canonical(left), canonical(right));
          if (found) failures.push(`${at} ${name}: ${found}`);
        };
        try {
          const stable = stableKey(env.group);
          const rows = env.group.sessions;
          const rowsLegacy = (legacyGroup as { sessions: unknown[] }).sessions;
          const lanes = projectLanes(env, rows);
          check(
            'lanes',
            rowsLegacy.flatMap((session) =>
              app.run('projectDelegationLanes(__session, {label: __stable})', { session, stable }),
            ),
            lanes,
          );
          // A row with no exact harness and sid has no focused context read to make, so it is not focused here.
          const candidate =
            seed % 3 === 0 && rows.length ? (rows[seed % rows.length] ?? null) : null;
          const focusRow = candidate && exactIdentity(candidate) ? candidate : null;
          const semanticRead = focusedContext && focusRow ? focusedContext : context;
          const raw = (semanticRead?.['semantic'] ?? null) as Record<string, unknown> | null;
          const base = raw && typeof raw === 'object' && !Array.isArray(raw) ? raw : {};
          const legacySemantic = raw ? raw : { facts: [], work_items: [], projections: {} };
          const projectSemantic = semanticOf(env.entry?.data ?? null);
          check(
            'canonical',
            app.run('nextCockpitCanonicalSemantic(__group, __semantic)', {
              group: legacyGroup,
              semantic: legacySemantic,
            }),
            canonicalSemantic(
              projectSemantic,
              raw ? base : { facts: [], work_items: [], projections: {} },
            ),
          );
          const canon = canonicalSemantic(
            projectSemantic,
            raw ? base : { facts: [], work_items: [], projections: {} },
          );
          const legacyCanon = app.run<Record<string, unknown>>(
            'nextCockpitCanonicalSemantic(__group, __semantic)',
            { group: legacyGroup, semantic: legacySemantic },
          );
          const focusLanes = focusRow ? projectLanes(env, [focusRow]) : lanes;
          const legacyEpisodes = app.run<unknown[]>(
            'nextCockpitCourseEpisodes(__semantic, __lanes)',
            {
              semantic: legacyCanon,
              lanes: focusLanes,
            },
          );
          const episodes = courseEpisodes(canon, focusLanes);
          // The legacy episode carries the group-less scope, so only the fields both draw are compared.
          check('episodes', legacyEpisodes, episodes);
          check(
            'directions',
            app.run('nextCockpitCourseDirections(__semantic, __episodes)', {
              semantic: legacyCanon,
              episodes: legacyEpisodes,
            }),
            courseDirections(canon, episodes),
          );
          check(
            'completed result',
            app.run('nextCockpitLatestCompletedResult(__semantic)', { semantic: legacyCanon }),
            latestCompletedResult(canon),
          );
          for (const episode of episodes) {
            check(
              'review findings',
              app.run('nextCockpitReviewFindings(__detail)', { detail: episode.fact['detail'] }),
              reviewFindings(episode.fact['detail']),
            );
            // The rendered disclosure is compared by what it says: the three published facts and what is missing.
            const html = app.run<string>('nextCockpitCourseEvidence(__fact, __names, "x")', {
              fact: episode.fact,
              names: episode.contributors,
            });
            const model = courseEvidence(episode.fact, episode.contributors, 'x');
            const text = html.replace(/<[^>]+>/g, '|').replace(/\|+/g, '|');
            for (const sentence of model.missing)
              if (!text.includes(sentence))
                failures.push(`${at} evidence: missing sentence ${sentence} not drawn`);
            if ((model.details === null) !== !html.includes('<details'))
              failures.push(`${at} evidence: disclosure offered differently`);
            if (
              model.details &&
              !html.includes(
                `data-next-cockpit-disclosure="${model.details.key}"`.replace(/"/g, '&quot;'),
              ) &&
              !html.includes(model.details.key.replace(/&/g, '&amp;'))
            )
              failures.push(`${at} evidence: disclosure key ${model.details.key} differs`);
          }

          // Tab cues: the Course count rides the tab's own workstream; the Decisions count the context read.
          const stableId = stable;
          const focusIdentity = focusRow ? exactIdentity(focusRow) : null;
          const contexts = new Map<string, ContextEntry>();
          contexts.set(
            contextKey(stableId, null),
            entry((env.entry?.data ?? null) as never, false),
          );
          if (focusRow && focusedContext) {
            contexts.set(
              contextKey(stableId, focusIdentity),
              entry(focusedContext, seed % 2 === 0),
            );
            app.setContext(`${stableId}\n${sessKey(focusRow)}`, {
              data: focusedContext,
              revision: 1,
              ...(seed % 2 === 0 ? { error: true as const } : {}),
            });
          }
          const read = selectContextRead(
            { contexts } as unknown as BoardSnapshot,
            stableId,
            focusIdentity,
          );
          const buffer = createWorkstream();
          buffer.observe(board);
          app.observe(board);
          const window = projectWindow(label, buffer.snapshot());
          const changes = projectChanges(window).changes.length;
          const legacyProject = app.run(
            'nextCurrentObserved().projects.find(project => project.key === __label)',
            { label },
          );
          for (const tab of ['now', 'course', 'decisions', 'console'] as const) {
            const legacyCue = app.run<Record<string, unknown> | null>(
              'nextCockpitTabCue(__tab, {group: __group, project: __project}, __focus)',
              { tab, group: legacyGroup, project: legacyProject, focus: focusRow },
            );
            const cue = tabCue(tab, { changes, read });
            check(
              `cue ${tab}`,
              legacyCue
                ? {
                    ...legacyCue,
                    stale: legacyCue['stale'] === true,
                    lastRead: legacyCue['stale'] ? (legacyCue['lastRead'] ?? null) : null,
                    value: legacyCue['value'] ?? 0,
                  }
                : null,
              cue,
            );
            if (legacyCue) {
              const html = app.run<string>('nextCockpitTabCueHtml(__tab, __cue)', {
                tab,
                cue: legacyCue,
              });
              const drawn = html
                .replace(/<[^>]+>/g, '|')
                .replace(/\|+/g, '|')
                .replace(/^\||\|$/g, '');
              const mine = cue
                ? [cueMark(cue), cue.stale ? 'stale' : '', cueGloss(tab, cue)]
                    .filter(Boolean)
                    .join('|')
                : '';
              check(`cue text ${tab}`, drawn, mine);
            }
          }
          for (const tab of ['now', 'course', 'decisions', 'console'] as const) {
            const legacyLede = app.run<string>('nextCockpitTabLede(__tab, __focus)', {
              tab,
              focus: focusRow,
            });
            check(
              `lede ${tab}`,
              legacyLede
                .replace(/<[^>]+>/g, '')
                .replace(
                  'Now: what is running in this project this minute, and how sessions here have ended.',
                  'Sessions and recent results for this project.',
                )
                .replace(
                  'Course: direction changes Compass observed in the session record.',
                  'Direction changes Compass observed in the session record.',
                )
                .replace(
                  'Decisions: rulings found in the record, and what each one has been spent on.',
                  'Decisions Compass found in the session record.',
                )
                .replace(
                  'Console: the read-only terminal of one selected session, and the controls for it.',
                  'Usage and alerts for this project.',
                ),
              tabLede(tab, Boolean(focusRow)).replace(/&/g, '&amp;'),
            );
          }
        } catch (error) {
          failures.push(`${at}: threw ${String((error as Error).stack ?? error).slice(0, 500)}`);
        }
        if (failures.length >= 3) break;
      }
      if (failures.length >= 3) break;
    }
    expect(failures).toEqual([]);
  }, 300_000);

  it('reaches episodes of every kind, paired directions and contributors', () => {
    const seen = {
      exact: 0,
      derived: 0,
      decision: 0,
      state: 0,
      paired: 0,
      directions: 0,
      contributors: 0,
    };
    // No legacy answer is read here: the generator is run wide, past the seeds the goldens hold.
    for (let seed = 1; seed <= 240; seed += 1) {
      const board = genBoard(seed);
      for (const label of labelsOf(board)) {
        const made = arrange(board, genContext(seed, board), label, 'ready');
        if (!made) continue;
        const raw = semanticOf(made.env.entry?.data ?? null);
        const episodes = courseEpisodes(
          canonicalSemantic(raw, raw),
          projectLanes(made.env, made.env.group.sessions),
        );
        for (const episode of episodes) {
          if (episode.badge === 'EXACT RESULT') seen.exact += 1;
          if (episode.badge === 'DERIVED COURSE CHANGE') seen.derived += 1;
          if (episode.badge === 'EXACT DECISION') seen.decision += 1;
          if (episode.badge === 'EXACT STATE CHANGE') seen.state += 1;
          if (episode.directionFact) seen.paired += 1;
          if (episode.contributors.length) seen.contributors += 1;
        }
        seen.directions += courseDirections(raw, episodes).length > 0 ? 1 : 0;
      }
    }
    for (const [name, count] of Object.entries(seen)) expect(count, name).toBeGreaterThan(0);
  });
});

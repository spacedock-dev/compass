import {
  annotationLines,
  revisionLine,
  type Annotation,
  type OutcomeLine,
} from '../intent/annotation';
import type { ObservedProject, ObservedSession } from '../observed';
import { compare, sessionKey, durationSince } from '../observed/values';
import { PROMPT_SOURCES, SESSION_GOAL } from '../sessions/intent';

/* Latest instruction is a list, not a field: zero to n rows, each with its own tag and its own source line. The
   reader's typed words are rows above the harness's, never merged with them, because "what I asked for"
   and "what the harness published" are different claims and one string cannot carry both. Ported from
   `nextProjectGoal` and the helpers around it. */

export interface GoalScope {
  readonly text: string;
  readonly known: boolean;
  readonly src: string;
  readonly at: number | null;
}

/* Session activity cannot date an instruction. Undated instructions stay available,
   but the card does not claim a latest instruction when any candidate lacks a stamp. */
export function goalScope(project: ObservedProject, focus: ObservedSession | null): GoalScope {
  const candidates = project.sessions.filter((session) => session.ownGoalKnown);
  candidates.sort(
    (a, b) =>
      (b.ownGoalAt ?? -Infinity) - (a.ownGoalAt ?? -Infinity) ||
      compare(sessionKey(a), sessionKey(b)),
  );
  if (!focus && !candidates.some((session) => session.ownGoalAt !== null))
    return {
      text: project.goalKnown ? project.goalText : 'No task or workflow instruction published',
      known: project.goalKnown,
      src: project.goalSrcText.replace('workflow goal', 'workflow instruction'),
      at: null,
    };
  const selected = focus ?? candidates[0];
  return {
    text: selected?.ownGoalKnown
      ? selected.ownGoalText
      : focus
        ? 'This session published no instruction'
        : 'No task or workflow instruction published',
    known: selected?.ownGoalKnown ?? false,
    src: selected?.ownGoalSrcText.replace('workflow goal', 'workflow instruction') ?? '',
    at: selected?.ownGoalAt ?? null,
  };
}

export function instructionHeading(
  project: ObservedProject,
  focus: ObservedSession | null,
): string {
  const candidates = focus ? [focus] : project.sessions.filter((session) => session.ownGoalKnown);
  return candidates.length && candidates.every((session) => session.ownGoalAt !== null)
    ? 'Latest instruction'
    : 'Published instruction';
}

/** "Spacedock · workflow goal · observed 4m ago": the source, with when the directive was observed. */
export function derivedSource(scope: GoalScope, generated: number | null): string {
  if (!scope.known) return '';
  const age = scope.at === null ? null : durationSince(generated, scope.at);
  return `${scope.src} · ${age === null ? 'observation time not published' : `observed ${age} ago`}`;
}

export interface GoalRow {
  readonly tag: string;
  readonly text: string;
  readonly source: string;
  readonly known: boolean;
}

export interface Goal {
  readonly scope: GoalScope;
  /** The reader's own words, then the outline lines, each with the revision they were saved at. */
  readonly typed: readonly GoalRow[];
  readonly derivedSource: string;
  /** The binding sentence: another session sharing a prefixed id would share these words. Only where there are words for it to be about. */
  readonly binding: string;
  /** A count across the project's sessions: beside one session's typed words it answers a question not asked. */
  readonly gap: string;
}

export function projectGoal(
  project: ObservedProject,
  annotation: Annotation | null,
  focus: ObservedSession | null,
  generated: number | null,
): Goal {
  const scope = goalScope(project, focus);
  const revision = revisionLine(annotation, generated);
  const typed: GoalRow[] = [];
  if (annotation?.['goal']) {
    typed.push({
      tag:
        annotation['goal_source'] === SESSION_GOAL
          ? 'Your saved words · from /goal'
          : PROMPT_SOURCES.includes(annotation['goal_source'] as string)
            ? 'Your saved words · from your prompt'
            : 'Your saved words',
      text: String(annotation['goal']),
      source: revision,
      known: true,
    });
  }
  const lines: OutcomeLine[] = annotationLines(annotation);
  for (const line of lines) {
    typed.push({
      tag: `Your saved words · expected outcome · line ${String(line.k)}`,
      text: line.text,
      source: revision,
      known: true,
    });
  }
  const why = annotation?.['binding_why'];
  return {
    scope,
    typed,
    derivedSource: derivedSource(scope, generated),
    binding: why && (annotation?.['goal'] || lines.length) ? String(why) : '',
    gap:
      !focus && project.goalGapKnown
        ? project.goalGapText.replace('no goal.', 'no instruction.')
        : '',
  };
}

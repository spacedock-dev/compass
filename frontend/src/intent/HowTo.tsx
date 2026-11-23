import { compatSessKey } from '../api/identity';
import { Disclosure, disclosureKey } from '../controls';
import { readingRoute, routeRefusal } from '../drift/route';
import {
  ANNOTATIONS_OFF,
  CLAUDE_READER_LIMIT,
  STEER_HARNESSES,
  WORK_HARNESSES,
} from '../drift/sentences';
import { EXPLANATIONS } from '../language/glossary';
import { nextNumber } from '../api/bootstrap';
import { endedAt } from '../observed';
import { datedClock } from '../observed/values';
import { REVISION_DEFINITION } from '../drift/sentences';
import { harnessLabels } from '../sessions/rows';
import { annotateOn, annotationLines, revisionLine } from './annotation';
import { usePanel } from './useIntent';
import { ENDED_CAVEAT, INTENT_MEASURED } from './sentences';

export function GoalExplanation() {
  const { input, payload, session, project } = usePanel();
  const scope = compatSessKey(session);
  const harness = String(session['harness'] || '');
  const labels = harnessLabels(payload);
  const label = (key: string) =>
    labels.get(key) || ({ claude: 'Claude Code', codex: 'Codex', pi: 'Pi' }[key] ?? key);
  /* "Claude Code, Codex and Pi": a list of three read as one with a serial "and". */
  const listed = (keys: readonly string[]) => {
    const words = keys.map(label);
    return words.length > 1
      ? `${words.slice(0, -1).join(', ')} and ${String(words.at(-1))}`
      : words.join('');
  };
  const route = readingRoute(payload, session);
  const reader = route?.['provider']
    ? String(route['label'] || route['provider'])
    : routeRefusal(payload, session);
  const steer = STEER_HARNESSES.includes(harness)
    ? 'available here'
    : `${STEER_HARNESSES.map(label).join(' and ')} only`;
  const availability = annotateOn(payload)
    ? `Reader here: ${reader}${reader.endsWith('.') ? '' : '.'} Steer back: ${steer}.`
    : ANNOTATIONS_OFF;
  const annotation = input.annotation;
  const generated = nextNumber(payload['generated']);
  const revision = revisionLine(annotation, generated);
  const start = nextNumber(annotation?.['window_start']);
  const hasWords = Boolean(annotation?.['goal'] || annotationLines(annotation).length);
  return (
    <Disclosure
      disclosureKey={disclosureKey({
        project,
        scope,
        name: 'intent-howto',
      })}
      summary={EXPLANATIONS.goals}
      explanation
      focusKey={`intent-howto:${scope}`}
    >
      <div
        id="goal-explanation"
        className="grid max-w-[var(--measure)] gap-2 text-body text-muted-foreground"
      >
        <p>
          1. Give the goal and, if useful, describe what done looks like. Compass uses /goal until
          edited, or drafts from your first prompt.
        </p>
        <p>2. A progress check uses AI and counts against a daily cap.</p>
        <p>3. To steer back, copy a correction.</p>
        <p
          data-next-intent-howto-limit
        >{`Compass can read recorded work from ${listed(WORK_HARNESSES)}. Progress levels appear only for ${listed(WORK_HARNESSES.filter((key) => key !== 'codex'))} sessions. ${availability} Compass never writes into sessions.`}</p>
        <p data-next-intent-howto-no-line>
          With no outcome line, Compass reads your goal's end state. A goal too vague to read is
          refused.
        </p>
        <p data-next-intent-howto-settle>
          The latest unpiped run settles when it fails or passes with no later write. Writes outside
          folder limits also depart.
        </p>
        <p data-next-intent-howto-accuracy>{CLAUDE_READER_LIMIT}</p>
      </div>
      <div className="mt-2 grid max-w-[var(--measure)] gap-2 text-body text-muted-foreground">
        <p data-next-intent-measured>{INTENT_MEASURED}</p>
        {endedAt(session) !== null ? <p data-next-ended-goal>{ENDED_CAVEAT}</p> : null}
        {hasWords && annotation?.['binding_why'] ? (
          <p>{String(annotation['binding_why'])}</p>
        ) : null}
        {start !== null && start > 0 ? (
          <p data-next-goal-reading-start>
            {`Reads from ${datedClock(start, generated ?? undefined)}. `}
            Editing the goal or adding a line keeps this start. Read from my latest message moves
            it.
          </p>
        ) : null}
        {revision ? <p>{`${revision}. ${REVISION_DEFINITION} Session: ${scope}.`}</p> : null}
      </div>
    </Disclosure>
  );
}

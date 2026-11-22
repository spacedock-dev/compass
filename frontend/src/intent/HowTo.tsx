import { compatSessKey } from '../api/identity';
import { Disclosure, disclosureKey } from '../controls';
import { readingRoute, routeRefusal } from '../drift/route';
import { CLAUDE_READER_LIMIT, STEER_HARNESSES, WORK_HARNESSES } from '../drift/sentences';
import { EXPLANATIONS } from '../language/glossary';
import { harnessLabels } from '../sessions/rows';
import { usePanel } from './useIntent';

export function GoalExplanation() {
  const { payload, session, project } = usePanel();
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
          1. Give the goal. Expected outcome is optional. A session's /goal is used until you edit
          it; else Compass drafts from your first prompt.
        </p>
        <p>2. A progress check asks once to allow reading and counts against a daily cap.</p>
        <p>
          3. Read where the work left your goal. On Claude Code, copy a correction to steer back.
        </p>
        <p
          data-next-intent-howto-limit
        >{`Progress levels: ${listed(WORK_HARNESSES)} only. Reader here: ${reader}${reader.endsWith('.') ? '' : '.'} Steer back: ${steer}. Compass never writes into sessions.`}</p>
        <p data-next-intent-howto-no-line>
          With no outcome line, Compass reads your goal's end state; a goal too vague to read is
          refused.
        </p>
        <p data-next-intent-howto-settle>
          Readings settle a command's latest unpiped run, failed or passed with nothing written
          after it. A recorded write breaking a folder limit also departs.
        </p>
        <p data-next-intent-howto-accuracy>{CLAUDE_READER_LIMIT}</p>
      </div>
    </Disclosure>
  );
}

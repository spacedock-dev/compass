import { Button } from '../ui/button';
import type { GraphMode } from '../storage';

const CHOICES: readonly { readonly mode: GraphMode; readonly label: string }[] = [
  { mode: 'active', label: 'Current work' },
  { mode: 'all', label: 'All events' },
  { mode: 'decisions', label: 'Decisions' },
];

/* A press changes the view, not the session, so it is a pressed-state
   toggle and not a navigation. The buttons are the same nodes on every redraw, which is what keeps a
   keyboard reader's place on the one they pressed. */
export function ActivityFilter({
  mode,
  onChoose,
}: {
  readonly mode: GraphMode;
  readonly onChoose: (mode: GraphMode) => void;
}) {
  return (
    <div className="pc-graph-filter" role="group" aria-label="Work activity filter">
      {CHOICES.map((choice) => (
        <Button
          variant="native"
          key={choice.mode}
          type="button"
          className={mode === choice.mode ? 'pc-graph-choice selected' : 'pc-graph-choice'}
          aria-pressed={mode === choice.mode}
          data-graph-mode-choice={choice.mode}
          onClick={() => onChoose(choice.mode)}
        >
          {choice.label}
        </Button>
      ))}
    </div>
  );
}

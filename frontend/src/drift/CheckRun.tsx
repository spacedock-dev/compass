import type { ComponentProps, ReactNode } from 'react';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '../ui/collapsible';
import { Icon } from '../ui/icons';
import { LAST_TURN_MARK, RESULT_MARKS, type CheckRunModel } from './workList';

export function CheckRun({
  run,
  turn = null,
  open,
  onOpenChange,
  children,
}: {
  readonly run: CheckRunModel;
  /** The last turn's range when this run holds the turn's newest row and no row of the turn is drawn outside it,
      so the label the turn is said by is not shut inside a closed run. */
  readonly turn?: string | null;
  readonly open: boolean;
  readonly onOpenChange: NonNullable<ComponentProps<typeof Collapsible>['onOpenChange']>;
  readonly children: ReactNode;
}) {
  return (
    <Collapsible open={open} onOpenChange={onOpenChange} data-check-run={run.last.entry.id}>
      <CollapsibleTrigger
        chevron={
          <Icon
            name="expand"
            className="shrink-0 transition-transform duration-[var(--disclose-dur)] group-data-[panel-open]:rotate-90 motion-reduce:transition-none"
          />
        }
        className="group flex w-full flex-wrap items-center gap-x-2 gap-y-1 rounded-control border-0 bg-transparent px-2 py-1 text-left text-label text-muted-foreground [font-family:var(--mono)] hover:bg-[var(--raise)]"
      >
        <Icon name="checks" />
        <span>{run.label}</span>
        {(['passed', 'unrecorded'] as const)
          .filter((state) => run.counts[state])
          .map((state) => (
            <span key={state} className="inline-flex items-center gap-1">
              <Icon name={state} />
              {String(run.counts[state])} {RESULT_MARKS[state].short.toLowerCase()}
            </span>
          ))}
        <span>{run.range}</span>
        {turn !== null ? (
          <span className="next-cockpit-work-turn tracking-[.07em]" data-check-run-turn>
            {turn ? `${LAST_TURN_MARK.short}: ${turn}` : LAST_TURN_MARK.short}
          </span>
        ) : null}
        <span className="ml-auto">{run.at}</span>
      </CollapsibleTrigger>
      <CollapsibleContent keepMounted hiddenUntilFound>
        <div className="next-cockpit-work-rows" role="list">
          {children}
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}

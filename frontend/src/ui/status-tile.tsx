import { cn } from '../lib/utils';
import { Icon, SESSION_STATE_ICONS } from './icons';
import { Tooltip, TooltipContent, TooltipTrigger } from './tooltip';

const TINTS = {
  Working: 'bg-[var(--status-working-bg)] text-[var(--status-working-ink)]',
  'Waiting on you': 'bg-[var(--status-waiting-bg)] text-[var(--status-waiting-ink)]',
  Quiet: 'bg-[var(--status-quiet-bg)] text-[var(--status-quiet-ink)]',
  Ended: 'bg-[var(--status-ended-bg)] text-[var(--status-ended-ink)]',
} as const;

export function StatusTile({
  state,
  live = false,
}: {
  readonly state: keyof typeof SESSION_STATE_ICONS;
  readonly live?: boolean;
}) {
  return (
    <Tooltip>
      <TooltipTrigger
        render={<span />}
        role="img"
        tabIndex={0}
        aria-label={state}
        data-next-row-state={state}
        className="relative z-[1] -m-0.5 inline-flex size-11 shrink-0 items-center justify-center [font-family:var(--sans)] normal-case outline-offset-2 focus-visible:outline-2 focus-visible:outline-solid focus-visible:outline-ring"
      >
        <span className={cn('grid size-10 place-items-center rounded-status-tile', TINTS[state])}>
          <Icon
            name={SESSION_STATE_ICONS[state]}
            className={cn('next-status-icon', live && 'motion-safe:animate-status-tile-pulse')}
            size={20}
          />
        </span>
      </TooltipTrigger>
      <TooltipContent>{state}</TooltipContent>
    </Tooltip>
  );
}

import { cn } from '../lib/utils';
import { Icon, SESSION_TILE_ICONS } from './icons';
import { Tooltip, TooltipContent, TooltipTrigger } from './tooltip';

const TINTS = {
  Working: 'bg-[var(--status-working-bg)] text-[var(--status-working-ink)]',
  'Waiting on you': 'bg-[var(--status-waiting-bg)] text-[var(--status-waiting-ink)]',
  Quiet: 'bg-[var(--status-quiet-bg)] text-[var(--status-quiet-ink)]',
  Ended: 'bg-[var(--status-ended-bg)] text-[var(--status-ended-ink)]',
  /* Neutral: the page ground and quiet ink, lighter than Quiet's pair, so not knowing never reads as Quiet. */
  'State not known': 'bg-[var(--bg)] text-[var(--ink2)]',
} as const;

export function StatusTile({
  state,
  live = false,
  focusable = true,
  rowState = state,
}: {
  readonly state: keyof typeof SESSION_TILE_ICONS;
  readonly live?: boolean;
  readonly focusable?: boolean;
  /** The row's own state word, which readers of `data-next-row-state` take as the row's state. A row whose
   * word is carried by a text line instead (State not published, Waiting on child) passes null. */
  readonly rowState?: string | null;
}) {
  return (
    <Tooltip>
      <TooltipTrigger
        render={<span />}
        role="img"
        tabIndex={focusable ? 0 : undefined}
        aria-label={state}
        data-next-row-state={rowState ?? undefined}
        data-next-row-tile={state}
        className="relative z-[1] -m-0.5 inline-flex size-11 shrink-0 items-center justify-center [font-family:var(--sans)] normal-case outline-offset-2 focus-visible:outline-2 focus-visible:outline-solid focus-visible:outline-ring"
      >
        <span className={cn('grid size-10 place-items-center rounded-status-tile', TINTS[state])}>
          <Icon
            name={SESSION_TILE_ICONS[state]}
            className={cn('next-status-icon', live && 'motion-safe:animate-status-tile-pulse')}
            size={20}
          />
        </span>
      </TooltipTrigger>
      <TooltipContent>{state}</TooltipContent>
    </Tooltip>
  );
}

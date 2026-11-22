import type { ReactNode } from 'react';
import { Badge } from '../ui/badge';
import { Tooltip, TooltipContent, TooltipTrigger } from '../ui/tooltip';
import { ActivityMarks } from './ActivityMarks';
import { COMPASS_ANSWER } from './sentences';
import { LAST_TURN_MARK, type WorkRow } from './workList';

/* `turnRange` is given by the list: null on every row of the last turn but its newest, which says the turn once,
   with the numbers it spans. Left out, as a lone head is drawn, a turn row says it itself. */
export function ActivityHead({
  row,
  turnRange,
  source,
  summary,
}: {
  readonly row: WorkRow;
  readonly turnRange?: string | null;
  /** The row's Source disclosure, drawn before its time. */
  readonly source?: ReactNode;
  readonly summary?: ReactNode;
}) {
  const turn = row.turn && turnRange !== null;
  const turnWords = turnRange ? `${LAST_TURN_MARK.words}, ${turnRange}` : LAST_TURN_MARK.words;
  return (
    <div
      className={`next-cockpit-work-head ${summary ? 'grid grid-cols-1 gap-x-3 min-[760px]:grid-cols-[minmax(6rem,1fr)_minmax(0,4fr)_auto]' : ''}`}
    >
      <span className="flex flex-wrap gap-x-2">
        <span className="next-cockpit-work-actor">{row.head.actor}</span>
        <span className="next-cockpit-work-type">{row.head.type}</span>
      </span>
      {summary}
      <span
        className="ml-auto flex min-w-0 flex-wrap items-center justify-end gap-x-2 gap-y-1 text-label [font-family:var(--mono)]"
        data-activity-head-right
      >
        {'check' in row.head && row.head.check ? (
          <ActivityMarks marks={row.head.check.marks} />
        ) : null}
        {row.flags.includes('later') ? (
          <Badge
            variant="work-flag"
            className="next-cockpit-work-flag"
            data-next-entry-flag="later"
          >
            A later direction you gave
          </Badge>
        ) : null}
        {row.flags.includes('cited') ? (
          <Badge
            variant="work-flag"
            className="next-cockpit-work-flag"
            data-next-entry-flag="cited"
          >
            Cited
          </Badge>
        ) : null}
        {row.flags.includes('compass') ? (
          <Badge
            variant="work-flag"
            className="next-cockpit-work-flag"
            data-next-entry-flag="compass"
          >
            {COMPASS_ANSWER}
          </Badge>
        ) : null}
        {turn ? (
          <Tooltip>
            <TooltipTrigger
              render={<span />}
              role="img"
              aria-label={turnWords}
              className="next-cockpit-work-turn text-muted-foreground tracking-[.07em]"
            >
              {turnRange ? `${LAST_TURN_MARK.short}: ${turnRange}` : LAST_TURN_MARK.short}
            </TooltipTrigger>
            <TooltipContent>{turnWords}</TooltipContent>
          </Tooltip>
        ) : null}
        {source}
        <span className="next-cockpit-work-at">{row.at}</span>
      </span>
    </div>
  );
}

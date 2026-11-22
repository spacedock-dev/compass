import type { AttentionSelection } from '../attention/select';
import { SESSION_LIST_WORDS, SESSION_ROW_WORDS } from '../language/glossary';
import { SESSION_TEXT_ORIGIN, sessionKey, type ObservedSession } from '../observed';
import { SummaryFilterCard, SummaryRouteCard } from '../ui/card';
import { Icon } from '../ui/icons';
import { joinNames } from './filters';

const NEEDS_YOU = { view: 'attention', project: null, session: null } as const;
const CARD = 'gap-4 p-4 [&>*:last-child]:mt-auto min-[761px]:min-h-52 min-[761px]:p-6';

function CardContents({
  label,
  count,
  tone,
  previews,
}: {
  readonly label: string;
  readonly count: number;
  readonly tone: 'waiting' | 'working' | 'worth';
  readonly previews: readonly (readonly [ObservedSession, string?, boolean?])[];
}) {
  return (
    <>
      <span className="flex w-full flex-wrap items-center justify-between gap-x-2">
        <span
          className={`inline-flex min-w-0 items-center gap-1.5 rounded-pill px-2.5 py-0.5 text-label font-semibold ${
            tone === 'working'
              ? 'bg-[var(--status-working-bg)] text-[var(--status-working-ink)]'
              : 'bg-[var(--status-waiting-bg)] text-[var(--status-waiting-ink)]'
          }`}
        >
          {tone === 'worth' ? <Icon name="worth-a-look" /> : null}
          {label}
        </span>{' '}
        <strong className="text-hero leading-none font-extrabold tabular-nums">{count}</strong>
      </span>
      {previews.length ? (
        <span className="grid min-w-0 gap-1">
          {previews.map(([row, detail, authored]) => (
            <span key={sessionKey(row)} className="grid min-w-0">
              <span
                className="line-clamp-2 font-semibold"
                data-authored={row.titleKnown || undefined}
              >
                {row.titleText}
              </span>
              {detail ? (
                <span
                  className="line-clamp-2 text-muted-foreground"
                  data-authored={authored || undefined}
                >
                  {detail}
                </span>
              ) : null}
            </span>
          ))}
        </span>
      ) : null}{' '}
    </>
  );
}

export function SessionsGlance({
  selection,
  hour,
  incompleteSources,
  listId,
  working,
  showWorking,
}: {
  readonly selection: AttentionSelection;
  readonly hour: number;
  readonly incompleteSources: boolean;
  readonly listId: string;
  readonly working: boolean;
  readonly showWorking: () => void;
}) {
  const { counts, quiet, ended, waitingOnYou, worthALook } = selection;
  const greeting = hour < 12 ? 'Good morning' : hour < 18 ? 'Good afternoon' : 'Good evening';
  if (!counts) {
    return (
      <header className="next-operations-header">
        <h1>{greeting}</h1>
        <p>Session counts are unavailable because the sources could not be read.</p>
      </header>
    );
  }
  const states = [
    `${counts.waitingOnYou} ${SESSION_ROW_WORDS.waitingOnYou.toLowerCase()}`,
    `${counts.working} ${SESSION_ROW_WORDS.working.toLowerCase()}`,
    `${quiet.length} ${SESSION_ROW_WORDS.quiet.toLowerCase()}`,
    `${ended.length} ${SESSION_ROW_WORDS.ended.toLowerCase()}`,
  ];
  if (selection.limitedStateCount)
    states.push(`${selection.limitedStateCount} with limited state evidence`);
  const coverage = incompleteSources
    ? 'among the sessions Compass could read, with some sources unavailable'
    : 'on this board';
  const summary = `You have ${joinNames(states)} ${coverage}.`;
  return (
    <>
      <header className="next-operations-header grid gap-2">
        <h1 className="m-0 text-head font-extrabold min-[621px]:text-hero">{greeting}</h1>
        <p
          id="sessions-glance-summary"
          className="m-0 text-body text-muted-foreground min-[621px]:text-value"
        >
          {summary}
        </p>
      </header>
      <section
        aria-label={SESSION_LIST_WORDS.atAGlance}
        aria-describedby="sessions-glance-summary"
        className="mt-6 grid grid-cols-1 gap-4 min-[761px]:grid-cols-3"
      >
        <SummaryRouteCard
          route={NEEDS_YOU}
          cue={SESSION_LIST_WORDS.openInNeedsYou}
          className={CARD}
        >
          <CardContents
            label={SESSION_ROW_WORDS.waitingOnYou}
            tone="waiting"
            count={counts.waitingOnYou}
            previews={waitingOnYou
              .slice(0, 2)
              .map((row) => [row, row.blockNote, row[SESSION_TEXT_ORIGIN].blockNote])}
          />
        </SummaryRouteCard>
        <SummaryFilterCard
          controls={listId}
          pressed={working}
          onClick={showWorking}
          className={CARD}
        >
          <CardContents
            label={SESSION_LIST_WORDS.workingNow}
            tone="working"
            count={counts.working}
            previews={selection.working.slice(0, 2).map((row) => [row])}
          />
        </SummaryFilterCard>
        <SummaryRouteCard
          route={NEEDS_YOU}
          cue={SESSION_LIST_WORDS.openInNeedsYou}
          className={CARD}
        >
          <CardContents
            label={SESSION_ROW_WORDS.worthALook}
            tone="worth"
            count={counts.worthALook}
            previews={[...worthALook].slice(0, 2)}
          />
        </SummaryRouteCard>
      </section>
    </>
  );
}

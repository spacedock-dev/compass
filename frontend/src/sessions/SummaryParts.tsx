import type { ReactNode } from 'react';
import { jobActive, type Shown, type SummaryBullet } from '../api/summary';
import { useDrift } from '../drift/context';
import { ModelNotice } from '../drift/ModelNotice';
import { Why } from '../drift/Why';
import { ActionButton } from '../intent/ActionButton';
import { useShell } from '../shell/context';
import {
  FRESHNESS_UNKNOWN,
  LEDE_LAST,
  PLACE_LINES,
  SUMMARY_ADDS,
  SUMMARY_HOLDS,
  SUMMARY_LABEL,
  SUMMARY_NOT_CLAUDE,
  SUMMARY_OFF,
  SUMMARY_RELEVANCE,
  SUMMARY_STARTING,
  SUMMARY_WORKING_KEEP,
  WITHHELD_TITLE,
  blockName,
  gapSentence,
  outOfDateLine,
  partsKept,
  phaseId,
  progressLine,
  readSize,
  reasonSentence,
  saidText,
  summaryNotes,
  withheldSentence,
} from './summary';
import { cancelSummary, deleteSummary, setSummaries, startSummary } from './summaryActions';
import { useSummaryMarks, type DepartureMark } from './summaryMarks';
import type { SummaryState } from './summaryState';

/* The summary half of the What the session has done card: its notice, its controls and the summary itself,
   drawn in the regions the card leaves for them. Every string a model wrote is drawn as text. */

function Line({
  children,
  ...rest
}: {
  readonly children: ReactNode;
  readonly [k: string]: unknown;
}) {
  return (
    <p className="next-cockpit-define" {...rest}>
      {children}
    </p>
  );
}

function Turn({ state, on }: { readonly state: SummaryState; readonly on: boolean }) {
  const shell = useShell();
  const control = `summary-grant:${state.key}`;
  return (
    <ActionButton
      weight="secondary"
      label={on ? 'Turn summaries on' : 'Turn off summaries'}
      busyLabel={on ? 'Turning on…' : 'Turning off…'}
      pendingKey={control}
      focusKey={control}
      action={on ? 'summary-on' : 'summary-off'}
      onPress={() => {
        if (state.identity) void setSummaries(shell, state.identity, on);
      }}
    />
  );
}

function Press({
  state,
  action,
  label,
  primary = false,
}: {
  readonly state: SummaryState;
  readonly action: 'start' | 'update' | 'rerun';
  readonly label: string;
  readonly primary?: boolean;
}) {
  const shell = useShell();
  const control = `summary:${state.key}`;
  return (
    <ActionButton
      weight={primary ? 'primary' : 'secondary'}
      label={label}
      busyLabel="Starting…"
      pendingKey={control}
      focusKey={control}
      action={`summary-${action}`}
      onPress={() => {
        if (state.identity) void startSummary(shell, state.identity, action, 'press');
      }}
    />
  );
}

/* What is sent, one press away beside Summarize, with the off switch inside it. */
function Sent({ state }: { readonly state: SummaryState }) {
  if (!state.grant?.disclosure) return null;
  const receiver = state.grant.provider === 'claude' ? 'Claude Code' : state.grant.provider;
  return (
    <Why name="summary-sent" pop summary={`What is sent to ${receiver}`}>
      <p className="next-cockpit-reading-why">{state.grant.disclosure}</p>
      <Turn state={state} on={false} />
    </Why>
  );
}

/* The notice the first summary on this machine shows, and again when where it goes or what it sends changes:
   the same notice card a reading's notice uses, with Turn off summaries beside it. */
function Notice({ state }: { readonly state: SummaryState }) {
  const notice = state.held.notice ?? (jobActive(state.job) ? state.job?.notice : null) ?? null;
  if (!notice || !state.grant || state.grant.reason === 'summaries-off') return null;
  return (
    <div data-next-summary-notice>
      <ModelNotice
        notice={notice}
        provider="Claude Code"
        parts={state.grant.disclosure ? [state.grant.disclosure] : []}
      >
        <Turn state={state} on={false} />
      </ModelNotice>
    </div>
  );
}

/* What the reader can do about the summary now, above whatever the slot draws. */
export function SummaryControls({
  state,
  outline,
}: {
  readonly state: SummaryState;
  readonly outline: { readonly entries: number | null; readonly more: boolean };
}) {
  const shell = useShell();
  const { grant, stored, job, held } = state;
  const failed = held.failed ? <Line data-next-summary-failed>{held.failed}</Line> : null;
  if (!grant) return null;
  if (state.harness !== 'claude')
    return (
      <Line data-next-summary-state="unsupported">{SUMMARY_NOT_CLAUDE(state.harnessLabel)}</Line>
    );
  if (jobActive(job) && job) {
    const control = `summary-cancel:${state.key}`;
    return (
      <div className="flex flex-col gap-2" data-next-summary-state="working">
        <Notice state={state} />
        <p className="m-0 text-body text-foreground" data-next-summary-progress>
          {progressLine(job)}
        </p>
        <Line>{SUMMARY_WORKING_KEEP}</Line>
        {job.state === 'running' ? (
          <div className="flex flex-wrap items-center gap-2">
            <ActionButton
              weight="secondary"
              label="Cancel"
              busyLabel="Cancelling…"
              pendingKey={control}
              focusKey={control}
              action="summary-cancel"
              onPress={() => {
                if (state.identity) void cancelSummary(shell, state.identity);
              }}
            />
          </div>
        ) : null}
        {failed}
      </div>
    );
  }
  if (grant.reason === 'summaries-off') {
    return (
      <div className="flex flex-col gap-2" data-next-summary-state="off">
        <Line>{SUMMARY_OFF}</Line>
        <div className="flex flex-wrap items-center gap-2">
          <Turn state={state} on />
        </div>
        {failed}
      </div>
    );
  }
  const notice = <Notice state={state} />;
  if (grant.reason) {
    return (
      <div className="flex flex-col gap-2" data-next-summary-state="blocked">
        {notice}
        <Line data-next-summary-reason={grant.reason}>
          {reasonSentence(grant.reason, state.reasons)}
        </Line>
        {failed}
      </div>
    );
  }
  /* Why the last attempt ended, from this tab's own press or from the job the server last ran. */
  const refusal = held.refusal;
  const stop =
    job && !jobActive(job) && job.state !== 'complete' && job.reason
      ? `${reasonSentence(job.reason, state.reasons)} ${partsKept(job)}`.trim()
      : '';
  const why = refusal ? reasonSentence(refusal.reason, state.reasons) : stop;
  if (stored) {
    const outdated = outOfDateLine(stored, state.reasons);
    return (
      <div className="flex flex-col gap-2 empty:hidden" data-next-summary-state="ready">
        {notice}
        {outdated ? (
          <div className="flex flex-wrap items-center gap-x-3 gap-y-2" data-next-summary-outdated>
            <p className="m-0 text-body text-foreground">{outdated.sentence}</p>
            <Press
              state={state}
              action={outdated.action}
              label={outdated.action === 'update' ? 'Update summary' : 'Summarize again'}
            />
          </div>
        ) : null}
        {stored.outOfDate?.kind === 'unavailable' ? (
          <Line data-next-summary-fresh="unknown">{FRESHNESS_UNKNOWN}</Line>
        ) : null}
        {why ? (
          <Line data-next-summary-reason={refusal?.reason ?? job?.reason ?? ''}>{why}</Line>
        ) : null}
        {failed}
      </div>
    );
  }
  const opening = state.due;
  if (held.opening)
    return (
      <div className="flex flex-col gap-2" data-next-summary-state="starting">
        {notice}
        <Line>{SUMMARY_STARTING}</Line>
      </div>
    );
  return (
    <div className="flex flex-col gap-2" data-next-summary-state="none">
      {notice}
      {why ? (
        <Line data-next-summary-reason={refusal?.reason ?? job?.reason ?? ''}>{why}</Line>
      ) : null}
      {state.focused?.state === 'unavailable' ? (
        <Line data-next-summary-reason="store-unavailable">
          {reasonSentence('store-unavailable', state.reasons)}
        </Line>
      ) : (
        <>
          <Line>{SUMMARY_ADDS}</Line>
          {readSize(outline.entries, outline.more) ? (
            <Line data-next-summary-size>{readSize(outline.entries, outline.more)}</Line>
          ) : null}
          <div className="flex flex-wrap items-center gap-2">
            {opening ? null : <Press state={state} action="start" label="Summarize" primary />}
            <Sent state={state} />
          </div>
        </>
      )}
      {failed}
    </div>
  );
}

function ShownText({ value, cited }: { readonly value: Shown; readonly cited?: string }) {
  if ('withheld' in value)
    return (
      <span className="text-muted-foreground" data-next-summary-withheld={value.withheld}>
        {withheldSentence(value.withheld)}
      </span>
    );
  return (
    <span className="[overflow-wrap:anywhere]" {...(cited ? { 'data-next-summary-text': '' } : {})}>
      {value.text}
    </span>
  );
}

/* The words a chip's name gives for the bullet it supports. */
const spoken = (bullet: SummaryBullet): string =>
  'text' in bullet.text
    ? bullet.kind === 'said'
      ? saidText(bullet.text.text)
      : bullet.text.text
    : 'a withheld line';

function Cites({
  cites,
  purpose,
  chip,
}: {
  readonly cites: readonly string[];
  readonly purpose: string;
  readonly chip: (id: string, purpose: string) => ReactNode;
}) {
  if (!cites.length) return null;
  return (
    <span
      className="ml-1 inline-flex flex-wrap items-center gap-x-1 align-baseline"
      data-next-summary-cites
    >
      {cites.map((id) => (
        <span key={id}>{chip(id, purpose)}</span>
      ))}
    </span>
  );
}

function Bullet({
  bullet,
  chip,
}: {
  readonly bullet: SummaryBullet;
  readonly chip: (id: string, purpose: string) => ReactNode;
}) {
  const failed = bullet.kind === 'failed';
  const value: Shown =
    'text' in bullet.text && bullet.kind === 'said'
      ? { text: saidText(bullet.text.text), cut: bullet.text.cut }
      : bullet.text;
  return (
    <li
      className={`text-body [overflow-wrap:anywhere] ${failed ? 'text-destructive' : 'text-foreground'}`}
      data-next-summary-bullet={bullet.kind}
    >
      <ShownText value={value} cited="yes" />
      <Cites cites={bullet.cites} purpose={`cited for “${spoken(bullet)}”`} chip={chip} />
    </li>
  );
}

function Mark({ marks }: { readonly marks: readonly DepartureMark[] }) {
  const { model } = useDrift();
  if (!marks.length) return null;
  return (
    <p
      className="m-0 flex flex-wrap items-center gap-x-2 text-label text-[var(--clay)]"
      data-next-summary-holds
    >
      <span>{SUMMARY_HOLDS}</span>
      {marks.map((mark) => (
        <JumpButton
          key={mark.key}
          target={`departure-head:${model.key}:${mark.key}`}
          label={`Departure · ${mark.name}`}
          name={`Go to the departure card: ${mark.name}`}
        />
      ))}
    </p>
  );
}

/* A press that moves focus to another card on this page. It reads, so the sample keeps it live, as it keeps the
   jump from a cited entry back to its finding. */
export function JumpButton({
  target,
  label,
  name,
}: {
  readonly target: string;
  readonly label: string;
  readonly name: string;
}) {
  return (
    <button
      type="button"
      className="cursor-pointer border-0 bg-transparent p-0 text-label text-[var(--clay)] underline"
      aria-label={name}
      data-next-cockpit-action="finding-jump"
      data-next-summary-jump={target}
      onClick={() => {
        const node = document.getElementById(target);
        if (!node) return;
        node.focus({ preventScroll: true });
        node.scrollIntoView({
          behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches
            ? 'instant'
            : 'smooth',
          block: 'center',
        });
      }}
    >
      {label}
    </button>
  );
}

/* The summary itself: the lede, then each part's phases as headings with their bullets, a gap or a withheld
   string said where it stands. */
export function SummaryView({
  state,
  chip,
  startsAt,
}: {
  readonly state: SummaryState;
  readonly chip: (id: string, purpose: string) => ReactNode;
  /** Where the summary starts, as the activity list numbers it, or empty. */
  readonly startsAt: string;
}) {
  const shell = useShell();
  const marks = useSummaryMarks();
  const stored = state.stored;
  if (!stored) return null;
  const running = jobActive(state.job);
  const lede = stored.lede;
  const control = `summary-delete:${state.key}`;
  return (
    <section className="flex flex-col gap-3" aria-label="Summary" data-next-summary>
      <p
        className="m-0 font-[family-name:var(--mono)] text-label text-muted-foreground"
        data-next-summary-label
      >
        {SUMMARY_LABEL}
      </p>
      {summaryNotes(stored, startsAt).map((note) => (
        <Line key={note} data-next-summary-note>
          {note}
        </Line>
      ))}
      {lede ? (
        <p className="m-0 max-w-[45rem] text-body text-foreground" data-next-summary-lede>
          <ShownText value={lede} cited="yes" />
          <Cites
            cites={stored.ledeCites}
            purpose={`cited for the opening summary${'text' in lede ? ` “${lede.text}”` : ''}`}
            chip={chip}
          />
        </p>
      ) : (
        <Line data-next-summary-lede="none">
          {running
            ? LEDE_LAST
            : stored.ledeReason
              ? `No opening summary: ${reasonSentence(stored.ledeReason, state.reasons)}`
              : 'No opening summary.'}
        </Line>
      )}
      {stored.blocks.map((block, b) =>
        block.gap ? (
          <p
            key={`${block.first}:${String(b)}`}
            className="next-cockpit-define m-0 border-l-2 border-dashed border-[var(--rule)] pl-3"
            data-next-summary-gap={block.gap}
          >
            {`${gapSentence(block, running)} ${block.entries ? `(${String(block.entries)} ${block.entries === 1 ? 'entry' : 'entries'})` : ''}`.trim()}
          </p>
        ) : (
          <div
            key={`${block.first}:${String(b)}`}
            className="flex flex-col gap-3"
            data-next-summary-block={b}
          >
            {block.phases.map((phase, p) => {
              const place = `${String(b)}:${String(p)}`;
              const held = marks.phases.get(place) ?? [];
              return (
                <section
                  key={place}
                  className="flex flex-col gap-1"
                  data-next-summary-phase={place}
                  {...(held.length ? { 'data-next-summary-marked': '' } : {})}
                  aria-labelledby={phaseId(state.key, place)}
                >
                  <h3
                    id={phaseId(state.key, place)}
                    tabIndex={-1}
                    className="m-0 text-body font-semibold text-foreground"
                  >
                    {'text' in phase.title ? (
                      phase.title.text
                    ) : (
                      <span
                        className="font-normal text-muted-foreground"
                        data-next-summary-withheld={phase.title.withheld}
                      >
                        {WITHHELD_TITLE}
                      </span>
                    )}
                  </h3>
                  <Mark marks={held} />
                  <ul className="m-0 flex flex-col gap-1.5 pl-5">
                    {phase.bullets.map((bullet, n) => (
                      <Bullet key={String(n)} bullet={bullet} chip={chip} />
                    ))}
                  </ul>
                  {phase.bulletsCut ? (
                    <Line>{`${String(phase.bulletsCut)} more ${phase.bulletsCut === 1 ? 'line was' : 'lines were'} cut from this phase.`}</Line>
                  ) : null}
                </section>
              );
            })}
            {block.withheldPhases ? (
              <Line data-next-summary-withheld="phase">
                {`${String(block.withheldPhases)} ${block.withheldPhases === 1 ? 'phase was' : 'phases were'} withheld from ${blockName(stored, b)}: not in the shape a phase must take.`}
              </Line>
            ) : null}
            {block.phasesCut ? (
              <Line>{`${String(block.phasesCut)} more ${block.phasesCut === 1 ? 'phase was' : 'phases were'} cut from this part.`}</Line>
            ) : null}
          </div>
        ),
      )}
      <Line>{SUMMARY_RELEVANCE}</Line>
      {state.grant && !running ? (
        <div className="flex flex-wrap items-center gap-2">
          <ActionButton
            weight="quiet"
            tone="muted"
            label="Delete summary"
            busyLabel="Deleting…"
            pendingKey={control}
            focusKey={control}
            action="summary-delete"
            onPress={() => {
              if (state.identity) void deleteSummary(shell, state.identity);
            }}
          />
          <Sent state={state} />
        </div>
      ) : null}
    </section>
  );
}

/* On the departure card: where its evidence sits in What the session has done, linked to the phase that holds
   it, or the sentence saying where it falls outside every phase. Nothing while no summary stands or the reading
   is not the current account. */
export function DepartureSummaryLine({ row }: { readonly row: string }) {
  const { model } = useDrift();
  const marks = useSummaryMarks();
  const mark = marks.departures.get(row);
  if (!mark || !marks.summary) return null;
  const key = model.key;
  const titles = mark.placement.phases.map((place) => {
    const [b, p] = place.split(':').map(Number);
    const title = marks.summary?.blocks[b ?? 0]?.phases[p ?? 0]?.title;
    return {
      place,
      title: title && 'text' in title ? title.text : 'a phase whose title was withheld',
    };
  });
  return (
    <p
      className="m-0 flex flex-wrap items-center gap-x-2 text-label text-muted-foreground"
      data-next-departure-summary={mark.placement.where}
    >
      <span>In What the session has done:</span>
      {mark.placement.where === 'phase' ? (
        titles.map(({ place, title }) => (
          <JumpButton
            key={place}
            target={phaseId(key, place)}
            label={title}
            name={`Go to the summary phase that holds this evidence: ${title}`}
          />
        ))
      ) : (
        <span>{PLACE_LINES[mark.placement.where]}</span>
      )}
    </p>
  );
}

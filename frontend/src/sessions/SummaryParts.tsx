import type { ReactNode } from 'react';
import {
  jobActive,
  type Shown,
  type StoredSummary,
  type SummaryBullet,
  type SummaryGrant,
  type SummaryJob,
} from '../api/summary';
import { Disclosure, disclosureKey } from '../controls';
import { useDrift } from '../drift/context';
import { ModelNotice } from '../drift/ModelNotice';
import { Why } from '../drift/Why';
import { ActionButton } from '../intent/ActionButton';
import { SampleMark } from '../sample/SampleMark';
import { clock } from '../observed';
import { useShell } from '../shell/context';
import {
  FRESHNESS_UNKNOWN,
  LEDE_LAST,
  PLACE_LINES,
  REPLY_CUT,
  SUMMARY_HOLDS,
  SUMMARY_INCOMPLETE,
  SUMMARY_LABEL,
  SUMMARY_NOT_CLAUDE,
  SUMMARY_OFF,
  SUMMARY_RELEVANCE,
  SUMMARY_STARTING,
  SUMMARY_WORKING_KEEP,
  deleteArmed,
  summaryDeleted,
  withheldTitle,
  unlinkedSentence,
  blockName,
  bulletWords,
  gapSentence,
  hiddenRange,
  hiddenKey,
  hiddenSentence,
  outOfDateLine,
  partsKept,
  phaseId,
  progressLine,
  readSize,
  reasonSentence,
  summaryNotes,
  withheldSentence,
} from './summary';
import {
  cancelSummary,
  disarmDeleteSummary,
  pressDeleteSummary,
  setSummaries,
  startSummary,
} from './summaryActions';
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
  const paused = state.grant?.reason === 'model-calls-paused';
  const reasonId = `summary-paused:${state.key}`;
  return (
    <>
      <ActionButton
        weight="secondary"
        inert={paused}
        describedBy={reasonId}
        label={on ? 'Turn summaries on' : 'Turn off summaries'}
        busyLabel={on ? 'Turning on…' : 'Turning off…'}
        pendingKey={control}
        focusKey={control}
        action={on ? 'summary-on' : 'summary-off'}
        onPress={() => {
          if (!paused && state.identity) void setSummaries(shell, state.identity, on);
        }}
      />
      {paused ? <Line id={reasonId}>Model calls are paused</Line> : null}
    </>
  );
}

function Press({
  state,
  action,
  label,
  primary = false,
  focus = '',
}: {
  readonly state: SummaryState;
  readonly action: 'start' | 'update' | 'rerun';
  readonly label: string;
  readonly primary?: boolean;
  /** Tells two presses on one card apart for focus; they share the one start in flight. */
  readonly focus?: string;
}) {
  const shell = useShell();
  const control = `summary:${state.key}`;
  return (
    <ActionButton
      weight={primary ? 'primary' : 'secondary'}
      label={label}
      busyLabel="Starting…"
      pendingKey={control}
      focusKey={focus ? `${control}:${focus}` : control}
      action={`summary-${action}`}
      onPress={() => {
        if (state.identity) void startSummary(shell, state.identity, action, 'press');
      }}
    />
  );
}

/* Off is the grant's own `off`, not its reason: at the cap while off the server publishes `daily-cap`, because
   the cap outranks off in the reason. */
const summariesOff = (grant: SummaryGrant): boolean =>
  grant.off || grant.reason === 'summaries-off';

/* What is sent, one press away beside Summarize, with the off switch inside it, or the on switch while off. */
const receiverOf = (grant: SummaryGrant): string =>
  grant.provider === 'claude' ? 'Claude Code' : grant.provider;

function Sent({ state }: { readonly state: SummaryState }) {
  if (!state.grant?.disclosure) return null;
  const receiver = receiverOf(state.grant);
  return (
    <Why name="summary-sent" pop summary={`What is sent to ${receiver}`}>
      <p className="next-cockpit-reading-why">{state.grant.disclosure}</p>
      <Turn state={state} on={summariesOff(state.grant)} />
    </Why>
  );
}

/* Pause model calls clears every notice on the server, the summary's included, so a notice this tab still
   holds is stale while paused and is not drawn beside an inert Turn off summaries. */
function noticeOf(state: SummaryState): Readonly<Record<string, unknown>> | null {
  const notice = state.held.notice ?? (jobActive(state.job) ? state.job?.notice : null) ?? null;
  return notice &&
    state.grant &&
    !summariesOff(state.grant) &&
    state.grant.reason !== 'model-calls-paused'
    ? notice
    : null;
}

/* The off switch one press from the card wherever the notice, which carries its own, is not drawn. */
function OffSwitch({ state }: { readonly state: SummaryState }) {
  if (!state.grant || summariesOff(state.grant) || noticeOf(state)) return null;
  return <Turn state={state} on={false} />;
}

/* The notice the first summary on this machine shows, and again when where it goes or what it sends changes:
   the same notice card a reading's notice uses, with Turn off summaries beside it. */
function Notice({ state }: { readonly state: SummaryState }) {
  const notice = noticeOf(state);
  if (!notice || !state.grant) return null;
  return (
    <div data-next-summary-notice>
      <ModelNotice
        notice={notice}
        name="Summary request notice"
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
  const { model } = useDrift();
  const { grant, stored, job, held } = state;
  const failed = held.failed ? <Line data-next-summary-failed>{held.failed}</Line> : null;
  if (!grant) return null;
  if (state.harness !== 'claude')
    return (
      <Line data-next-summary-state="unsupported">
        {SUMMARY_NOT_CLAUDE(state.harnessLabel, outline.entries !== null)}
      </Line>
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
        <div className="flex flex-wrap items-center gap-2 empty:hidden">
          {job.state === 'running' ? (
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
          ) : null}
          <OffSwitch state={state} />
        </div>
        {failed}
      </div>
    );
  }
  if (summariesOff(grant)) {
    const also = grant.reason && grant.reason !== 'summaries-off' ? grant.reason : '';
    return (
      <div className="flex flex-col gap-2" data-next-summary-state="off">
        <Line>{SUMMARY_OFF}</Line>
        {also ? (
          <Line data-next-summary-reason={also}>{reasonSentence(also, state.reasons)}</Line>
        ) : null}
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
        <div className="flex flex-wrap items-center gap-2 empty:hidden">
          <OffSwitch state={state} />
        </div>
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
    const again = outdated?.action !== 'rerun' && incomplete(stored, job);
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
        {again ? (
          <div className="flex flex-wrap items-center gap-x-3 gap-y-2" data-next-summary-incomplete>
            <p className="m-0 text-body text-foreground">{SUMMARY_INCOMPLETE}</p>
            <Press state={state} action="rerun" label="Summarize again" focus="incomplete" />
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
  /* The header's count and this one are read from the numbered list the rows render from, so one session never
     says 13, 20 and 22 in three places; the outline's own total stands in only until that list is read. */
  const size = readSize(model.entryCount ?? outline.entries, outline.more, state.plan);
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
      {held.deletedAt > 0 ? (
        <Line data-next-summary-deleted>{summaryDeleted(clock(held.deletedAt / 1000))}</Line>
      ) : null}
      {why ? (
        <Line data-next-summary-reason={refusal?.reason ?? job?.reason ?? ''}>{why}</Line>
      ) : null}
      {state.focused?.state === 'unavailable' ? (
        <Line data-next-summary-reason="store-unavailable">
          {reasonSentence('store-unavailable', state.reasons)}
        </Line>
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
            {opening ? null : <Press state={state} action="start" label="Summarize" primary />}
            {size ? <Line data-next-summary-size>{size}</Line> : null}
            <Sent state={state} />
          </div>
        </>
      )}
      {failed}
    </div>
  );
}

/* A summary that stopped partway compares as unchanged against its own snapshot, so freshness offers nothing;
   Summarize again is what covers the rest. A gap no rerun would fill, a session longer than one summary reads
   or a summary at its largest saved size, does not offer it. */
const RERUN_FILLS_NOTHING = new Set(['before_window', 'bytes']);
const STOPPED_JOBS = new Set(['partial', 'cancelled', 'interrupted']);
function incomplete(stored: StoredSummary, job: SummaryJob | null): boolean {
  return (
    stored.ledeReason === 'stopped' ||
    stored.blocks.some((block) => block.gap !== null && !RERUN_FILLS_NOTHING.has(block.gap)) ||
    (job !== null && !jobActive(job) && STOPPED_JOBS.has(job.state))
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
  'text' in bullet.text ? bulletWords(bullet.kind, bullet.text.text) : 'a hidden line';

const counted = (n: number, one: string, many: string) => `${String(n)} ${n === 1 ? one : many}`;

/* A chip for each citation the reader can follow. A message id is the record's own, so a chip on the agent's or
   the person's words reads older record pages for it. Record pages hold no checks or files, so a line that may
   cite one gets a chip only once the page holds an entry under that id, and its press reads nothing; an earlier
   run or write has no entry of its own (docs/design-session-summary.md#source-and-outline-contract), so the
   rest are counted, not dropped. */
function Cites({
  cites,
  cut = 0,
  purpose,
  reads,
  chip,
}: {
  readonly cites: readonly string[];
  readonly cut?: number;
  readonly purpose: string;
  /** True when every id is a message id; a set names the ids known to be messages. */
  readonly reads: boolean | ReadonlySet<string>;
  readonly chip: (id: string, purpose: string) => ReactNode;
}) {
  const { model } = useDrift();
  const linked =
    reads === true
      ? cites
      : cites.filter((id) => model.byId.has(id) || (reads instanceof Set && reads.has(id)));
  const unlinked = cites.length - linked.length;
  if (!cites.length && !cut) return null;
  return (
    <span className="[overflow-wrap:anywhere]" data-next-summary-cites>
      {linked.map((id) => (
        <span key={id} className="ml-1.5">
          {chip(id, purpose)}
        </span>
      ))}
      {unlinked ? (
        <span className="text-label text-muted-foreground" data-next-summary-unlinked={unlinked}>
          {unlinkedSentence(unlinked)}
        </span>
      ) : null}
      {cut ? (
        <span className="text-label text-muted-foreground" data-next-summary-cites-cut={cut}>
          {`${counted(cut, 'more citation was', 'more citations were')} cut`}
        </span>
      ) : null}
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
    'text' in bullet.text
      ? { text: bulletWords(bullet.kind, bullet.text.text), cut: bullet.text.cut }
      : bullet.text;
  return (
    <li
      className={`text-body [overflow-wrap:anywhere] ${failed ? 'text-destructive' : 'text-foreground'}`}
      data-next-summary-bullet={bullet.kind}
    >
      <ShownText value={value} cited="yes" />
      <Cites
        cites={bullet.cites}
        cut={bullet.citesCut}
        purpose={`cited for “${spoken(bullet)}”`}
        reads={bullet.kind === 'said' || bullet.kind === 'asked'}
        chip={chip}
      />
    </li>
  );
}

/* A phase's bullets in order, each withheld run of them gathered into one. */
function runs(
  bullets: readonly SummaryBullet[],
): { readonly at: number; readonly hidden: boolean; readonly bullets: SummaryBullet[] }[] {
  const out: { at: number; hidden: boolean; bullets: SummaryBullet[] }[] = [];
  bullets.forEach((bullet, at) => {
    const hidden = !('text' in bullet.text);
    const last = out.at(-1);
    if (hidden && last?.hidden) last.bullets.push(bullet);
    else out.push({ at, hidden, bullets: [bullet] });
  });
  return out;
}

const reasonOf = (bullet: SummaryBullet): string =>
  'withheld' in bullet.text ? bullet.text.withheld : '';

/* A run of withheld lines, said once and muted: how many, why, and the entries they cite, with each line's own
   reason and citations one press away. No result label leads it: a withheld failed line once read "Failed as the
   tool reported: Withheld: ...", a result put on words nobody can see. */
function Hidden({
  bullets,
  name,
  chip,
}: {
  readonly bullets: readonly SummaryBullet[];
  readonly name: string;
  readonly chip: (id: string, purpose: string) => ReactNode;
}) {
  const { model } = useDrift();
  const reasons = bullets.map(reasonOf);
  const range = hiddenRange(
    bullets.flatMap((bullet) => bullet.cites),
    model.labels,
  );
  return (
    <li
      className="text-body text-muted-foreground [overflow-wrap:anywhere]"
      data-next-summary-hidden={bullets.length}
    >
      <span data-next-summary-hidden-line>{hiddenSentence(reasons, range)}</span>
      <Why name={name} summary={bullets.length === 1 ? 'Why it was hidden' : 'Why each was hidden'}>
        <ol className="m-0 flex flex-col gap-1 pl-5">
          {bullets.map((bullet, n) => (
            <li
              key={String(n)}
              className="text-label text-muted-foreground"
              data-next-summary-withheld={reasonOf(bullet)}
            >
              {withheldSentence(reasonOf(bullet))}
              <Cites
                cites={bullet.cites}
                cut={bullet.citesCut}
                purpose="cited for a hidden line"
                reads={bullet.kind === 'said' || bullet.kind === 'asked'}
                chip={chip}
              />
            </li>
          ))}
        </ol>
      </Why>
    </li>
  );
}

const PILL =
  'inline-flex min-h-0 min-w-0 items-center rounded-full px-2.5 py-0.5 text-label font-semibold [font-family:var(--mono)]';

/* What a phase holds that a reader should know before opening it, drawn on its heading and right-aligned: the
   departures its entries are evidence for, each a pill that goes to the card, and a count of its failed lines.
   They sit outside the accordion's trigger so they stay in view while the lines are folded away. */
function Mark({
  marks,
  failures,
  tour,
}: {
  readonly marks: readonly DepartureMark[];
  readonly failures: number;
  readonly tour: boolean;
}) {
  const { model } = useDrift();
  if (!marks.length && !failures) return null;
  return (
    <>
      {marks.length ? (
        <span className="contents" data-next-summary-holds>
          <span className="sr-only">{SUMMARY_HOLDS}</span>
          {tour ? <SampleMark id="phase" /> : null}
          {marks.map((mark) => (
            <JumpButton
              key={mark.key}
              target={`departure-head:${model.key}:${mark.key}`}
              label={`Departure · ${mark.name}`}
              /* WCAG 2.5.3: the accessible name begins with the visible label. */
              name={`Departure · ${mark.name}, go to the card`}
              className={`${PILL} cursor-pointer border-0 bg-[var(--clay)] text-[color:var(--bg)] no-underline hover:brightness-110`}
            />
          ))}
        </span>
      ) : null}
      {failures ? (
        <span
          className={`${PILL} border border-solid border-[var(--clay)] text-[var(--clay)]`}
          data-next-summary-failures={failures}
        >
          {`${String(failures)} ${failures === 1 ? 'failure' : 'failures'}`}
        </span>
      ) : null}
    </>
  );
}

/* A press that moves focus to another card on this page. It reads, so the sample keeps it live, as it keeps the
   jump from a cited entry back to its finding. */
export function JumpButton({
  target,
  label,
  name,
  className = 'cursor-pointer border-0 bg-transparent p-0 text-label text-[var(--clay)] underline',
}: {
  readonly target: string;
  readonly label: string;
  readonly name: string;
  readonly className?: string;
}) {
  return (
    <button
      type="button"
      className={className}
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

/* Delete summary, quieter than the reading's own controls and in two presses. The first arms it and says what
   goes and what stays with the sentence the second press acts on; Keep summary and Escape take the offer back. */
const DELETE_ARMED_ID = 'next-summary-delete-armed';

function DeleteSummary({ state }: { readonly state: SummaryState }) {
  const shell = useShell();
  const control = `summary-delete:${state.key}`;
  const armed = state.held.deleteArmedAt > 0;
  const sentence = state.grant ? deleteArmed(receiverOf(state.grant)) : '';
  return (
    <div
      className="flex flex-wrap items-center gap-2"
      onKeyDown={(event) => {
        if (event.key !== 'Escape' || !state.identity) return;
        if (disarmDeleteSummary(shell, state.identity)) {
          event.preventDefault();
          event.stopPropagation();
        }
      }}
    >
      <ActionButton
        weight={armed ? 'secondary' : 'quiet'}
        tone="muted"
        strongBorder={armed}
        label={armed ? 'Confirm delete' : 'Delete summary'}
        busyLabel="Deleting…"
        pendingKey={control}
        focusKey={control}
        action="summary-delete"
        describes={armed ? DELETE_ARMED_ID : ''}
        onPress={(detail) => {
          if (state.identity) pressDeleteSummary(shell, state.identity, detail, sentence);
        }}
      />
      {armed ? (
        <>
          <ActionButton
            weight="quiet"
            tone="muted"
            label="Keep summary"
            focusKey={`${control}:keep`}
            action="summary-delete-keep"
            onPress={() => {
              if (state.identity) disarmDeleteSummary(shell, state.identity);
            }}
          />
          <Line id={DELETE_ARMED_ID} data-next-summary-delete-armed>
            {sentence}
          </Line>
        </>
      ) : null}
    </div>
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
  const { model } = useDrift();
  const marks = useSummaryMarks();
  const stored = state.stored;
  if (!stored) return null;
  const running = jobActive(state.job);
  const lede = stored.lede;
  /* The lede may cite a check or a file, which no record page holds, so it reads older pages only for ids a
     `said` or `asked` bullet also cites: those are message ids, as the bullets' own chips already treat them. */
  const messageIds = new Set(
    stored.blocks.flatMap((block) =>
      block.phases.flatMap((phase) =>
        phase.bullets.flatMap((bullet) =>
          bullet.kind === 'said' || bullet.kind === 'asked' ? bullet.cites : [],
        ),
      ),
    ),
  );
  /* The sample's tour notes the first phase that holds a departure, once. */
  const toured = stored.blocks.flatMap((block, b) =>
    block.gap
      ? []
      : block.phases
          .map((_phase, p) => `${String(b)}:${String(p)}`)
          .filter((place) => (marks.phases.get(place) ?? []).length > 0),
  )[0];
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
            reads={messageIds}
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
            className="flex flex-col gap-1"
            data-next-summary-block={b}
          >
            {block.phases.map((phase, p) => {
              const place = `${String(b)}:${String(p)}`;
              const held = marks.phases.get(place) ?? [];
              return (
                <section
                  key={place}
                  className="flex flex-col gap-0"
                  data-next-summary-phase={place}
                  {...(held.length ? { 'data-next-summary-marked': '' } : {})}
                  aria-labelledby={phaseId(state.key, place)}
                >
                  <Disclosure
                    disclosureKey={disclosureKey({
                      project: model.project,
                      scope: model.key,
                      name: `summary-phase:${place}`,
                    })}
                    className="next-summary-phase [&_[data-slot=accordion-trigger]]:min-h-[34px] [&_[data-slot=accordion-trigger]]:font-semibold [&_[data-slot=accordion-trigger]]:text-foreground"
                    headerProps={{
                      render: <h3 className="m-0 text-body font-semibold text-foreground" />,
                      id: phaseId(state.key, place),
                      tabIndex: -1,
                    }}
                    summary={
                      'text' in phase.title ? (
                        phase.title.text
                      ) : (
                        <span
                          className="font-normal text-muted-foreground"
                          data-next-summary-withheld={phase.title.withheld}
                        >
                          {withheldTitle(phase.title.withheld)}
                        </span>
                      )
                    }
                    aside={
                      <Mark
                        marks={held}
                        failures={phase.bullets.filter((line) => line.kind === 'failed').length}
                        tour={place === toured}
                      />
                    }
                  >
                    <ul className="m-0 flex flex-col gap-1.5 pl-5">
                      {runs(phase.bullets).map((run) =>
                        run.hidden ? (
                          <Hidden
                            key={String(run.at)}
                            bullets={run.bullets}
                            name={`summary-hidden:${place}:${hiddenKey(run.bullets, run.at)}`}
                            chip={chip}
                          />
                        ) : (
                          <Bullet
                            key={String(run.at)}
                            bullet={run.bullets[0] as SummaryBullet}
                            chip={chip}
                          />
                        ),
                      )}
                    </ul>
                    {phase.bulletsCut ? (
                      <Line>{`${String(phase.bulletsCut)} more ${phase.bulletsCut === 1 ? 'line was' : 'lines were'} cut from this phase.`}</Line>
                    ) : null}
                  </Disclosure>
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
            {block.replyCut ? <Line data-next-summary-reply-cut>{REPLY_CUT}</Line> : null}
          </div>
        ),
      )}
      <Line>{SUMMARY_RELEVANCE}</Line>
      {state.grant && !running ? (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
          <Sent state={state} />
          <DeleteSummary state={state} />
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

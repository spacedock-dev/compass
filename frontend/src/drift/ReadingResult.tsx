import { SampleBeside } from '../sample/SampleMark';
import { Button } from '../ui/button';
import { useLayoutEffect, useRef, type ReactNode } from 'react';
import { nextNumber } from '../api/bootstrap';
import { contextKey } from '../api/identity';
import { useDisplayed } from '../shell/context';
import { useFocusKey } from '../controls';
import { ActionButton } from '../intent/ActionButton';
import { entryWindow, olderEntriesRemain, type WorkEntry } from '../intent/work';
import { markNotAccurate } from './actions';
import { SESSION_GOAL } from '../sessions/intent';
import { DepartureSummaryLine } from '../sessions/SummaryParts';
import { useDrift } from './context';
import { EvidenceList } from './Evidence';
import { evidenceRows } from './level';
import {
  arrivedLine,
  cantTellReason,
  citedKind,
  departureTitle,
  departureWhat,
  claimHeading,
  claimReason,
  claimsDrawn,
  constraintName,
  coverageLimits,
  driftAnswer,
  earlyLine,
  goalSourceLine,
  LIVE_HIDDEN,
  resultState,
  resultStatus,
  resultWhere,
  resultWork,
  stampModel,
  verdictLine,
  verdictShape,
  type Answer,
} from './result';
import { fmtDur } from './route';
import { clock } from '../observed';
import {
  CLAIM_LEAD,
  CLAIMS,
  clearedLine,
  CLAUSE_UNRETAINED,
  DEPARTURE,
  NOT_REACHED,
  LEVEL_SCALE,
  READ_INTENT,
  READ_MODEL,
  READ_NEVER,
  READ_NOT_READ,
  READ_SESSION,
  READ_SUMMARY,
  GOAL_UNCLEAR_VERDICT,
  RESULT_CANT_TELL,
  RESULT_DEPARTS,
  RESULT_MARK_UNSAVED,
  RESULT_NOT_ACCURATE,
  RESULT_NOT_ACCURATE_HINT,
  RESULT_NOTHING_FOUND,
  readIdle,
  readScopeLine,
  SCOPE_TEXT_IDLE,
  unloadedCites,
} from './sentences';
import { datedClock } from '../observed/values';
import { ReadingCount, WhatIsSent, type SteerSlot } from './ReadingControl';
import { isOutcomeLine, type Criterion, type Shape } from './shape';
import { CitationLink } from './CitationLink';
import { CitedText } from './CitedText';
import { SteerSection } from './SteerBack';
import { Why } from './Why';

/* Accent on a reading would read as "met", a claim about intent from partial evidence. The result keeps
   secondary ink and no colour under any verdict; clay marks a departure and nothing else. */

const LABEL =
  'm-0 text-label font-semibold uppercase tracking-[.07em] text-[var(--ink-label)] [font-family:var(--mono)]';
const LABEL_CLAY =
  'm-0 text-label font-semibold uppercase tracking-[.07em] text-[var(--clay)] [font-family:var(--mono)]';
const QUIET = 'm-0 max-w-[var(--measure)] text-body leading-[1.5] text-muted-foreground';
const NO_DETAIL = 'No explanation was retained for this assessment.';

/* The constraint as a cited entry's accessible name says it, every outcome line numbered: the name has to tell
   two chips with the same number apart. */
function jumpName(key: string): string {
  if (key === 'goal' || key === CLAIMS) return constraintName(key, 1);
  return `Expected outcome line ${key === 'output' ? '1' : key.slice(5)}`;
}

/* The cited entries of one finding, each as its number in the activity list and the kind of entry Compass
   names, or on a departure card what it says, attributed ('Agent said: "…"'), so the line the departure is
   about is in view and reads as the agent's words, never as the result's. A number opens
   Full activity at that entry; an entry the page does not hold yet keeps the press that reads older pages for
   it. The shape demotes a departure with no held citation, so a departure always reaches at least one
   number. */
function CitedEntries({
  row,
  quote = false,
}: {
  readonly row: Criterion;
  /** A departure's What: each entry's own words, attributed. Elsewhere the kind alone, so a line read as
   * consistent never stands beside the agent's "Done". */
  readonly quote?: boolean;
}) {
  const { model, chooseFinding, jumpMissing } = useDrift();
  const record = useDisplayed((snapshot) =>
    snapshot.records.get(contextKey(model.projectKey, model.identity)),
  );
  /* One number per entry: the shape keeps a repeated cite, as the legacy producer it is held to did, and the
     evidence rows and the unloaded count already read a repeat as one citation. */
  const held = [...new Set(row.citedIds)]
    .map((id) => model.byId.get(id))
    .filter((entry): entry is WorkEntry => Boolean(entry));
  const older =
    row.unloaded > 0 && olderEntriesRemain(record, entryWindow(model.session, model.payload));
  /* The press reads by the record's cursor alone, with no window shortcut, so a retained reading that cites an
     entry from before the current window keeps its way there. The sentence above stays window-bound. */
  const loadable = row.unloaded > 0 && record?.status === 'loaded' && !record.reachedStart;
  const named = row.clause ? `${jumpName(row.key)}: ${row.clause}` : jumpName(row.key);
  const link = (entry: WorkEntry) => {
    const id = String(entry.id || '');
    const where = resultWhere(entry, model.numbers) || 'Entry';
    return (
      <CitationLink
        key={id}
        id={id}
        className="ml-1.5"
        data-next-cockpit-action="finding-jump"
        data-next-finding={row.key}
        data-next-cite={id}
        aria-label={`Show ${where} in Full activity for ${named}`}
        onJump={(origin) => chooseFinding(row.key, origin, id)}
      >
        {where.startsWith('#') ? `[${where.slice(1)}]` : `[${where}]`}
      </CitationLink>
    );
  };
  /* A departure's What is one sentence about what happened, with each cited entry's number after it. */
  const chips = held.length ? (
    quote ? (
      <p
        className="m-0 text-body leading-[1.5] text-foreground [overflow-wrap:anywhere]"
        data-next-cited-entries={row.key}
      >
        {departureWhat(held)}
        {held.map(link)}
      </p>
    ) : (
      <ul className="m-0 flex list-none flex-col gap-2 p-0" data-next-cited-entries={row.key}>
        {held.map((entry) => (
          <li
            key={String(entry.id || '')}
            className="m-0 min-w-0 text-body leading-[1.5] text-foreground [overflow-wrap:anywhere]"
          >
            {citedKind(entry)}
            {link(entry)}
          </li>
        ))}
      </ul>
    )
  ) : null;
  /* Kept while its "could not be loaded" sentence stands, so the way back from that sentence has a place to
     land. */
  const load =
    !held.length && (loadable || jumpMissing?.press.key === row.key) ? (
      <Button
        type="button"
        variant="bare"
        data-next-cockpit-action="finding-jump"
        data-next-finding={row.key}
        data-next-cite=""
        aria-label={`Load the cited entries in Full activity for ${named}`}
        onClick={(event) => chooseFinding(row.key, event.currentTarget)}
      >
        Load the cited entries
      </Button>
    ) : null;
  return (
    <>
      {chips ? (
        <SampleBeside id={row.key === 'goal' ? 'departure' : ''}>{chips}</SampleBeside>
      ) : null}
      {load}
      {older ? (
        <p className={QUIET} data-next-unloaded>
          {unloadedCites(row.unloaded)}
        </p>
      ) : null}
    </>
  );
}

/* The shape labels a line in capitals ("GOAL FROM YOUR PROMPT"); Evidence heads with it in a sentence's case. */
function sentenceCase(label: string): string {
  const lower = label.toLowerCase();
  return `${lower.charAt(0).toUpperCase()}${lower.slice(1)}`;
}

/* The line's label, its full status, its why, the limit and each cited entry's own record, one click away
   under "Evidence", as before the cards: moved, never dropped. The record-type tag ("agent_message ·
   timestamped …") is the source's, so it sits under Source rather than beside the heading it ran into
   (usability review, 2026-10-20). The why stays here because the reason for Can't tell stays inside Evidence
   (owner, 2026-10-14). */
function EvidenceMore({
  row,
  status,
  rows,
  quoted = false,
  reasoned = false,
}: {
  readonly row: Criterion;
  readonly status: string;
  readonly rows: boolean;
  /** What already quotes each cited entry's words, so its record here leaves them out. */
  readonly quoted?: boolean;
  /** The row's own reason is drawn above, so neither it nor the generic status is said again here. */
  readonly reasoned?: boolean;
}) {
  const { model } = useDrift();
  const full = reasoned ? status : resultStatus(row, model.numbers, model.byId);
  const listed = rows ? evidenceRows(row.citedIds, model.numbers, model.byId) : [];
  return (
    <Why name={`result-evidence:${row.key}`} summary="Evidence">
      <p
        className="m-0 text-body font-semibold leading-[1.45] text-foreground"
        data-next-evidence-head
      >
        {sentenceCase(row.label)}
      </p>
      {full === status ? null : (
        <span className="next-cockpit-reading-evidence">
          <CitedText text={full} />
        </span>
      )}
      {row.why && !reasoned ? <p className="next-cockpit-reading-why">{row.why}</p> : null}
      {row.result === NOT_REACHED && row.detail ? (
        <p className="next-cockpit-reading-detail">{row.detail}</p>
      ) : null}
      {row.limit && !(reasoned && !row.why) ? (
        <span className="next-cockpit-reading-limit">{`limit · ${row.limit}`}</span>
      ) : null}
      {listed.length ? (
        <EvidenceList
          rows={listed}
          scope={row.key}
          sources={row.limit ? [] : row.evidence}
          quoted={quoted}
        />
      ) : !row.limit && row.evidence.length ? (
        <Why name={`result-source:${row.key}`} summary="Source">
          {row.evidence.map((line, index) => (
            <p key={index} className="next-cockpit-reading-evidence">
              {line}
            </p>
          ))}
        </Why>
      ) : null}
    </Why>
  );
}

/* One departure from the reader's intent, as its own card: which constraint, the constraint's own words as the
   headline: what happened, derived from the cited entry because no model writes one ([DEC-28](../../../docs/design-session-summary.md#the-ruling) answer 7), What
   as the cited entries, and Why as the reading's stored `detail`, the one string a model wrote. */
function DepartureCard({ row, outcomes }: { readonly row: Criterion; readonly outcomes: number }) {
  const { model } = useDrift();
  const detail = String(row.detail || '').trim();
  const head = `departure-head:${model.key}:${row.key}`;
  const title = departureTitle(
    [...new Set(row.citedIds)]
      .map((id) => model.byId.get(id))
      .filter((entry): entry is WorkEntry => Boolean(entry)),
    constraintName(row.key, outcomes),
  );
  return (
    <article
      className="flex items-start gap-3 rounded-[10px] bg-[var(--raise)] px-[18px] py-4 max-[480px]:gap-2 max-[480px]:px-3"
      aria-labelledby={head}
      data-next-departure={row.key}
      data-next-result-state={resultState(row)}
      {...(row.key === 'goal' ? { 'data-next-result-goal': '' } : {})}
    >
      <span className="next-cockpit-result-glyph" aria-hidden="true" />
      <div className="flex min-w-0 flex-1 flex-col gap-2.5">
        <div className="flex flex-col gap-0.5">
          <p className={LABEL_CLAY} data-next-departure-label>
            {`Departure · ${constraintName(row.key, outcomes)}`}
          </p>
          <h4
            id={head}
            tabIndex={-1}
            className={`m-0 text-body font-semibold leading-[1.45] [overflow-wrap:anywhere] ${title || row.clauseKnown ? 'text-foreground' : 'text-muted-foreground'}`}
          >
            {title || (row.clauseKnown && row.clause ? row.clause : CLAUSE_UNRETAINED)}
          </h4>
        </div>
        <div className="flex max-w-[45rem] flex-col gap-1" data-next-departure-what>
          <p className={LABEL}>What</p>
          <CitedEntries row={row} quote />
        </div>
        <div className="flex max-w-[45rem] flex-col gap-0.5" data-next-departure-why>
          <p className={LABEL}>Why Compass reads this as drift</p>
          <p className="next-cockpit-reading-detail m-0 text-foreground not-italic">
            {detail || NO_DETAIL}
          </p>
        </div>
        {row.coverage ? (
          <p className={QUIET}>
            <CitedText text={row.coverage} />
          </p>
        ) : null}
        <DepartureSummaryLine row={row.key} />
        {/* "Departs; evidence #5" says again what the label and What say, so it is said once, in Evidence. */}
        <EvidenceMore row={row} status="" rows quoted />
      </div>
    </article>
  );
}

/* One remaining line, quiet: a glyph by state (a cross for departs, a neutral filled dot for consistent, never
   a check and never green, a dashed circle for can't tell), the ruled status in the words `resultStatus` and
   `claimStatus` use, the line's own words and its cited entries. A contradicted claim keeps its explanation, or
   the sentence saying none was retained, and each cited entry's record under Evidence, as before the cards. */
function QuietRow({
  row,
  outcomes,
  tag,
}: {
  readonly row: Criterion;
  readonly outcomes: number;
  readonly tag: 'li' | 'div';
}) {
  const { model } = useDrift();
  const state = resultState(row);
  const claims = row.key === CLAIMS;
  /* The design's two forms: `Can't tell · <line>` with the reason under it, and `What the agent claimed ·
     "<claim>" is not shown by the record`. Each says its own reason in view, not behind Evidence. */
  const cantTell = state === 'cant-tell';
  const reason = cantTell
    ? cantTellReason(row, model.numbers)
    : claimReason(row, model.numbers, model.entries, model.shape?.windowStart ?? null);
  const claim = claimHeading(row, model.numbers);
  const status = claim
    ? CLAIM_LEAD
    : cantTell && !claims
      ? RESULT_CANT_TELL
      : resultStatus(row, model.numbers, model.byId, true);
  const claimDeparts = claims && row.result === DEPARTURE;
  const detail = claimDeparts ? String(row.detail || '').trim() : '';
  const Tag = tag;
  return (
    <Tag
      className="next-cockpit-reading-row"
      data-next-result-state={resultState(row)}
      data-next-result-row={row.key}
      {...(tag === 'li'
        ? {}
        : claims
          ? { 'data-next-result-claims': '' }
          : { 'data-next-result-goal': '' })}
    >
      <span className="next-cockpit-result-glyph" aria-hidden="true" />
      <span className="next-cockpit-result-body">
        <span className="m-0 text-body font-semibold leading-[1.45] text-foreground [overflow-wrap:anywhere]">
          <em className="next-cockpit-reading-result">
            <CitedText text={status} />
          </em>
          {claim ? (
            <>
              {' · '}
              <span className="next-cockpit-reading-clause font-normal" data-next-claim>
                {`“${claim.claim}”`}
              </span>{' '}
              <span className="font-normal">
                <CitedText text={claim.tail} />
              </span>
            </>
          ) : claims ? null : (
            <>
              {' · '}
              <span
                className={`next-cockpit-reading-clause${row.clauseKnown ? '' : '-absent'} font-normal`}
              >
                {row.clauseKnown && row.clause
                  ? `“${row.clause}”`
                  : `${constraintName(row.key, outcomes)}: ${CLAUSE_UNRETAINED}`}
              </span>
            </>
          )}
        </span>
        {reason ? (
          <span className="next-cockpit-reading-why" data-next-reason>
            <CitedText text={reason} />
          </span>
        ) : null}
        {claimDeparts ? (
          <span className="next-cockpit-reading-detail">{detail || NO_DETAIL}</span>
        ) : null}
        {row.coverage ? (
          <span className="next-cockpit-reading-why">
            <CitedText text={row.coverage} />
          </span>
        ) : null}
        <CitedEntries row={row} />
        <EvidenceMore
          row={row}
          status={status}
          rows={claimDeparts}
          reasoned={cantTell || Boolean(claim)}
        />
      </span>
    </Tag>
  );
}

/* The answer. Under a departure it is "Departs from your intent" with the count of departures, which renders
   only here; the cards below carry each one. `midFlight` leads the answer with "So far:", so a reading of a
   running session never looks like a reading of how it ended. */
function ResultAnswer({
  answer,
  midFlight,
  focusKey,
}: {
  readonly answer: Answer;
  readonly midFlight: boolean;
  readonly focusKey: string | null;
}) {
  const { ctx, model } = useDrift();
  // The completed result replaces the job title in the same focus lane as the original Analyze press.
  const headingRef = useFocusKey<HTMLHeadingElement>(ctx.shell.controls.focusLane, focusKey);
  const headingProps = {
    ref: headingRef,
    tabIndex: -1,
    'data-next-result-heading': true,
    'data-next-focus': focusKey ?? undefined,
  };
  const ring =
    'focus-visible:outline-2 focus-visible:outline-solid focus-visible:outline-[var(--accent)] focus-visible:outline-offset-1';
  const lead = midFlight ? (
    <>
      <span className="next-cockpit-result-scope">So far:</span>{' '}
    </>
  ) : null;
  let body: ReactNode;
  if (answer.kind === 'departs') {
    const count = `${String(answer.count)} departure${answer.count === 1 ? '' : 's'}`;
    body = (
      <h3 {...headingProps} className={`next-cockpit-result-headline ${ring} text-value`}>
        {lead}
        <span>{RESULT_DEPARTS}</span>
        <span className="next-cockpit-result-count rounded-full bg-[var(--clay)] px-2.5 py-px text-label font-semibold text-[color:var(--bg)] [font-family:var(--mono)]">
          {count}
        </span>
      </h3>
    );
  } else if (answer.kind === 'failed-check') {
    const where = resultWhere(answer.failed, model.numbers, true);
    body = (
      <h3 {...headingProps} className={`next-cockpit-result-line ${ring}`}>
        {lead}
        {where ? `A check failed at ${where}.` : 'A check failed.'}
      </h3>
    );
  } else if (answer.kind === 'not-reached') {
    body = (
      <h3 {...headingProps} className={`next-cockpit-result-line ${ring}`}>
        {lead}
        Not reached at this stop.
      </h3>
    );
  } else if (answer.kind === 'goal-unclear') {
    body = (
      <h3 {...headingProps} className={`next-cockpit-result-line ${ring}`}>
        {GOAL_UNCLEAR_VERDICT}
      </h3>
    );
  } else {
    body = (
      <h3 {...headingProps} className={`next-cockpit-result-line ${ring}`}>
        {lead}
        {answer.kind === 'cant-tell' ? RESULT_CANT_TELL : RESULT_NOTHING_FOUND}
      </h3>
    );
  }
  return <div className="next-cockpit-result-answer">{body}</div>;
}

/* Where the work went, one click away under What the analysis read: the design's Drift card has no such block
   between the answer and its footer, and a list of folders with citations was what pushed Mark as inaccurate
   and Steer back down the card. Moved, never dropped. */
function WorkSection() {
  const { model } = useDrift();
  const { shape } = model;
  if (!shape) return null;
  const work = resultWork(model.entries, model.numbers, model.source.scan, shape.windowStart);
  if (!work) return null;
  return (
    <ReadSection name="work" title="Where the work went">
      <ul className="m-0 flex list-none flex-col gap-0.5 p-0">
        {work.groups.map((group) => (
          <li key={group.folder} className="next-cockpit-result-folder">
            <span className="next-cockpit-result-path">
              {group.folder || 'The working directory'}
            </span>
            <span>{`${String(group.files)} file${group.files === 1 ? '' : 's'}`}</span>
            <span>
              <CitedText text={group.references} />
            </span>
          </li>
        ))}
      </ul>
      {/* Behind its count, so the list's own rows are what stands in view. */}
      {work.more ? (
        <Why name="result-work-more" summary={`${String(work.more)} more`}>
          <p className="next-cockpit-reading-why">
            {`${String(work.more)} more written ${work.more === 1 ? 'file is' : 'files are'} counted and not listed.`}
          </p>
        </Why>
      ) : work.unavailable ? (
        <p className="next-cockpit-reading-why">The total written in this window is unavailable.</p>
      ) : null}
    </ReadSection>
  );
}

/* Not accurate: a token on this reading, posted with the reading's time so a newer one is never marked by a
   tab drawn before it. Pressed again it takes the mark back. It is never sent anywhere else and never counted.
   The mark derives from the payload: a store that did not take the press draws unmarked and says so, rather
   than showing a mark nothing holds. Both states say, beside the control, what the mark does, because what it
   changes (the level and Steer back) is drawn far above it. The press holds the control where the reader
   pressed it: the level and Steer back leave the column above, and the page would otherwise jump. */
const HOLD_MS = 10_000;

function ResultFoot() {
  const { ctx, model } = useDrift();
  const readAt = nextNumber(model.raw?.['read_at']);
  const marked = model.annotation?.['not_accurate'] === true;
  const foot = useRef<HTMLDivElement>(null);
  const held = useRef<{ top: number; from: boolean; at: number } | null>(null);
  useLayoutEffect(() => {
    const hold = held.current;
    const node = foot.current;
    if (!hold || !node || hold.from === marked) return;
    held.current = null;
    if (Date.now() - hold.at > HOLD_MS) return;
    const moved = node.getBoundingClientRect().top - hold.top;
    if (moved) window.scrollBy(0, moved);
  }, [marked]);
  /* A refusal sets no level and offers no Steer back, so there is nothing for the mark to stop; the Undo of
     one already made stays. */
  const refused =
    model.shape !== null &&
    driftAnswer(model.shape, model.entries, model.source.scan).kind === 'goal-unclear';
  if (readAt === null || !model.annotate || (refused && !marked)) return null;
  const unsaved = ctx.drift.notAccurate.has(model.key);
  const hintId = `not-accurate-why:${model.key}`;
  const control = (
    <ActionButton
      weight="quiet"
      label={RESULT_NOT_ACCURATE}
      busyLabel="Saving…"
      pendingKey={`not-accurate:${model.key}`}
      action="not-accurate"
      arg={String(readAt)}
      focusKey={`not-accurate:${model.key}`}
      describes={hintId}
      onPress={() => {
        if (!model.identity) return;
        const top = foot.current?.getBoundingClientRect().top;
        held.current = top === undefined ? null : { top, from: marked, at: Date.now() };
        void markNotAccurate(ctx, model.identity, readAt, marked);
      }}
    />
  );
  /* A quiet footer line: the control, and what it does as its description rather than a second line of the
     card. Marked, the state says so beside the way back. */
  return (
    <div
      ref={foot}
      className="next-cockpit-result-foot"
      data-next-result-mark={marked ? 'marked' : 'unmarked'}
    >
      {marked ? null : (
        <>
          {control}
          <span id={hintId} className="next-visually-hidden">
            {RESULT_NOT_ACCURATE_HINT}
          </span>
        </>
      )}
      {unsaved && !marked ? (
        <p className="next-cockpit-reading-why" role="status">
          {RESULT_MARK_UNSAVED}
        </p>
      ) : null}
    </div>
  );
}

/* The cutoff is composed by the producer as sentences; one item per sentence reads faster than the run. */
function readSentences(text: string): string[] {
  return text
    .split(/(?<=\.)\s+(?=[A-Z0-9])/)
    .map((sentence) => sentence.trim())
    .filter(Boolean);
}

function ReadSection({
  name,
  title,
  meta,
  children,
}: {
  readonly name: string;
  readonly title: string;
  readonly meta?: string;
  readonly children: ReactNode;
}) {
  return (
    <section className="flex flex-col gap-[4px]" data-next-read-section={name}>
      <h4 className="m-0 text-label font-semibold uppercase tracking-[.07em] text-[var(--ink-label)] [font-family:var(--mono)]">
        {title}
      </h4>
      {meta ? <p className="next-cockpit-reading-stamp m-0">{meta}</p> : null}
      {children}
    </section>
  );
}

const READ_LIST =
  'm-0 flex list-disc flex-col gap-[4px] pl-[18px] text-body leading-[1.5] text-muted-foreground [font-family:var(--sans)]';

/* The shape labels each line it read in capitals ("TYPED GOAL", "EXPECTED OUTCOME · LINE 2"); this says the
   same thing in a sentence's case, numbering an outcome line only when there is more than one. */
function intentLabel(label: string, lines: number): string {
  if (label.includes('GOAL')) return 'Goal';
  const n = /LINE (\d+)$/.exec(label)?.[1];
  return n && lines > 1 ? `Expected outcome ${n}` : 'Expected outcome';
}

/* A reading of an idle Claude Code session whose last turn has no recorded finish says so where its answer is,
   with the reader's local time of the last entry it read, so it is never taken for a verdict on how the turn
   ended (owner, 2026-10-20). Known by its stored sentence, since its scope is the running session's. */
function idleLine(shape: Shape, raw: Readonly<Record<string, unknown>>): string {
  if (shape.scope !== 'mid-flight' || shape.scopeText !== SCOPE_TEXT_IDLE) return '';
  const through = nextNumber(raw['evidence_through']);
  return readIdle(through !== null && through > 0 ? datedClock(through) : '');
}

/* What it read, one click away: the model, the intent it read against (which revision, when and where it came
   from), how much of the session it read, and what it never reads. Revision and times are about the reading,
   never about the work. */
function Baseline({
  shape,
  raw,
  arrived,
}: {
  readonly shape: Shape;
  readonly raw: Readonly<Record<string, unknown>>;
  readonly arrived: string;
}) {
  const { model } = useDrift();
  const cap = nextNumber(model.payload['annotate_cap']);
  /* With no time it said "time not recorded"; adopted words were saved rather than typed, so their missing
     time is the save's. */
  const meta =
    shape.revisionRead === null
      ? ''
      : [
          shape.revisionReadAt !== null
            ? `${shape.promptSource ? 'saved' : 'typed'} ${fmtDur(Math.max(0, model.generated - shape.revisionReadAt))} ago`
            : `${shape.promptSource ? 'save time' : 'time'} not recorded`,
          raw['goal_source'] === SESSION_GOAL
            ? 'from /goal'
            : shape.promptSource
              ? 'drafted from your prompt'
              : '',
          /* Both times where they differ: typed words read work from the reader's latest message before the
             save. Adopted words already name their prompt. */
          !shape.promptSource &&
          shape.windowStart !== null &&
          shape.revisionReadAt !== null &&
          shape.windowStart < shape.revisionReadAt
            ? `reads work from your message ${fmtDur(Math.max(0, model.generated - shape.windowStart))} ago`
            : '',
        ]
          .filter(Boolean)
          .join(' · ');
  const lines = shape.readClauses.filter(([label]) => intentLabel(label, 0) !== 'Goal').length;
  /* The entry range the level read and the level's own reason ("Departure evidence: #5.") are about what
     the analysis read, so they are said here and not between the meter and the answer (usability review,
     2026-10-20). */
  const level = model.analysis;
  const session = [
    idleLine(shape, raw) || readScopeLine(shape.scope, shape.scopeText),
    ...readSentences(shape.cutoff),
    level?.range ? `Entries read: ${level.range}.` : '',
    level?.reasons?.first ?? '',
    goalSourceLine(shape),
    arrived,
  ].filter(Boolean);
  return (
    <Why name="reading-baseline" summary={READ_SUMMARY}>
      <div className="flex flex-col gap-[12px]" data-next-read>
        {/* The model alone: the stamp's "read at HH:MM" is the card header's "Analysis last run", said once. */}
        {stampModel(shape.stamp) ? (
          <ReadSection name="model" title={READ_MODEL}>
            <p className="next-cockpit-reading-stamp m-0">{stampModel(shape.stamp)}</p>
          </ReadSection>
        ) : null}
        {shape.readClauses.length ? (
          <ReadSection name="intent" title={READ_INTENT} meta={meta}>
            <ul className={READ_LIST}>
              {shape.readClauses.map(([label, clause]) => {
                const name = intentLabel(label, lines);
                const cut =
                  name === 'Goal' && shape.promptSource && cap !== null && clause.length >= cap;
                return (
                  <li key={label}>
                    <span className="font-semibold text-foreground">{name}</span>{' '}
                    {clause ? (
                      <span className="text-foreground">{`“${clause}”`}</span>
                    ) : (
                      <span className="next-cockpit-reading-clause-absent">
                        {CLAUSE_UNRETAINED}
                      </span>
                    )}
                    {cut ? (
                      <span>
                        {shape.coverage?.goal_source === 'whole'
                          ? ` Shown cut at ${String(cap)} characters; the analysis read the whole prompt, up to 1,000 characters.`
                          : ` Cut at ${String(cap)} characters.`}
                      </span>
                    ) : null}
                  </li>
                );
              })}
            </ul>
          </ReadSection>
        ) : null}
        {session.length ? (
          <ReadSection name="session" title={READ_SESSION}>
            <ul className={READ_LIST}>
              {session.map((line) => (
                <li key={line}>
                  <CitedText text={line} />
                </li>
              ))}
            </ul>
          </ReadSection>
        ) : null}
        <WorkSection />
        <ReadSection name="not-read" title={READ_NOT_READ}>
          <p className="next-cockpit-reading-why">{READ_NEVER}</p>
        </ReadSection>
      </div>
    </Why>
  );
}

export function ReadingResult({
  question,
  again,
  slotted,
  steerOff = '',
}: {
  /** The question before the press, which keeps the result's head while a later direction is unsettled. */
  readonly question: ReactNode;
  /** Steer back's row and box, where the control offers it. */
  readonly slotted: SteerSlot | null;
  /** Why Steer back does not carry the departures listed, said beside them (`steerWithheld`). */
  readonly steerOff?: string;
  /** What a press was answered with under the result; the run control itself is the card header's. */
  readonly again: (steer: SteerSlot | null) => ReactNode;
}) {
  const { model } = useDrift();
  const { shape, raw, annotation, entries, source } = model;
  if (!shape || !raw || !annotation) return null;
  const answer =
    shape.criteria.length || shape.departures.length
      ? driftAnswer(shape, entries, source.scan)
      : null;
  const coverage = coverageLimits(shape);
  const idle = idleLine(shape, raw);
  /* From the reading rather than from the live row. A reading describes the moment it was taken. */
  const arrived = arrivedLine(annotation, entries);
  const intent = shape.criteria.filter((row) => row.key !== CLAIMS);
  const outcomes = intent.filter((row) => isOutcomeLine(row.key)).length;
  /* The answer's own departures, in the reading's order: the goal, then each outcome line. */
  const departures = answer?.kind === 'departs' ? answer.departures : [];
  const departed = new Set(departures.map((row) => row.key));
  /* A refused goal is said under the Goal field and in the verdict; no row repeats it, and no line or claim
     of that run is drawn, because the reading found nothing to read them against. */
  const refused = answer?.kind === 'goal-unclear';
  const goal = refused ? [] : intent.filter((row) => row.key === 'goal' && !departed.has(row.key));
  const lines = refused
    ? []
    : intent.filter((row) => isOutcomeLine(row.key) && !departed.has(row.key));
  /* What the agent claimed, after the intent it is independent of. */
  const claimed = refused ? [] : claimsDrawn(shape);
  const quiet = goal.length + lines.length + claimed.length > 0;
  /* A current result keeps the disclosure and accounting without a second run control: the card header holds
     the one, in every state. A direction question owns the run path while it stands.
     [DEC-27](../../../docs/design-reading-a-session.md#dec-27-the-first-view-of-a-session-is-the-goal-analyze-drift-and-the-result) */
  const foot = question ? null : again(null);
  /* The verdict sentence above the level says the answer once; a heading here says it only where that
     sentence is not drawn, over a reading marked inaccurate. */
  const marked = annotation['not_accurate'] === true;
  return (
    <div className="next-session-drift-check next-cockpit-result gap-1" data-next-result>
      {question}
      {/* A marked reading's verdicts stay readable and are set aside: dimmed, never hidden, under the one
          message the level's slot holds. An unmarked reading's wrapper adds no box. */}
      <div
        className={marked ? 'flex flex-col gap-1 opacity-60' : 'contents'}
        {...(marked ? { 'data-next-disowned': '' } : {})}
      >
        {answer && marked ? (
          <ResultAnswer
            answer={answer}
            midFlight={shape.scope === 'mid-flight'}
            focusKey={question ? null : `reading:${model.key}`}
          />
        ) : null}
        {idle ? (
          <p className="next-cockpit-reading-why" data-next-reading-idle>
            {idle}
          </p>
        ) : null}
        {coverage ? (
          <p className="next-cockpit-reading-why" data-next-reading-coverage>
            {coverage}
          </p>
        ) : null}
        {departures.length ? (
          <div className="flex flex-col gap-3.5" data-next-departures>
            {departures.map((row) => (
              <DepartureCard key={row.key} row={row} outcomes={outcomes} />
            ))}
          </div>
        ) : null}
        {departures.length && steerOff ? (
          <p className="next-cockpit-reading-why" data-next-steer-off>
            {steerOff}
          </p>
        ) : null}
        {quiet ? (
          <div
            className={`flex flex-col gap-3 ${departures.length ? 'border-t border-[var(--rule)] pt-3' : ''}`}
            data-next-result-quiet
          >
            {goal.map((row) => (
              <QuietRow key={row.key} row={row} outcomes={outcomes} tag="div" />
            ))}
            {lines.length ? (
              <ol className="next-cockpit-result-lines">
                {lines.map((row) => (
                  <QuietRow key={row.key} row={row} outcomes={outcomes} tag="li" />
                ))}
              </ol>
            ) : null}
            {claimed.map((row) => (
              <QuietRow key={row.key} row={row} outcomes={outcomes} tag="div" />
            ))}
          </div>
        ) : null}
        {/* Steer back, its own section after the departures it steers from. While a later direction stands the
          question owns the primary press and Steer back is the secondary beside it (owner, 2026-10-20). */}
        {slotted ? <SteerSection buttons={slotted.button} box={slotted.box} /> : null}
      </div>
      {foot ? <div className="next-cockpit-result-press">{foot}</div> : null}
      <div
        className="flex flex-wrap items-start gap-x-4 gap-y-2 border-t border-[var(--rule)] pt-2.5"
        data-next-result-footer
      >
        <ResultFoot />
        <Baseline shape={shape} raw={raw} arrived={arrived} />
        {question ? null : <WhatIsSent />}
        <div className="self-center empty:hidden">
          <ReadingCount count={nextNumber(annotation['reading_count']) || 0} />
        </div>
      </div>
    </div>
  );
}

/* The Drift card's answer in one sentence, first under its heading (usability review, 2026-10-20: the level,
   the count and what they rest on were spread over the meter, the answer and each card). Drawn from the
   stored reading the result below draws, and only while that result stands: not over an unreadable reading
   or one the reader marked inaccurate. It stays while a run over it is in view, dimmed. It is the one place
   the card says its answer, so it is also where focus lands when a result replaces the progress. */
export function DriftVerdict({ focus }: { readonly focus: boolean }) {
  const { ctx, model, cleared } = useDrift();
  const { shape, raw, annotation, entries, source, annotate } = model;
  const ref = useFocusKey<HTMLParagraphElement>(
    ctx.shell.controls.focusLane,
    focus ? `reading:${model.key}` : null,
  );
  if (!verdictShape({ annotate, shape, raw, annotation }) || !shape) return null;
  const answer = driftAnswer(shape, entries, source.scan);
  const analysis = model.analysis;
  const standing = analysis && analysis.level !== 'not_enough' ? analysis : null;
  const text = verdictLine({
    answer,
    level: standing?.label ?? '',
    heldBack: analysis && !standing ? analysis.reasons.blockers : [],
    byId: model.byId,
    midFlight: shape.scope === 'mid-flight',
  });
  /* The slot belongs to the reading: with no level drawn for it, a live estimate the reader switched on has
     one to draw and does not, and the page says so rather than leave the switch looking broken. */
  const estimate = model.estimate;
  const hidesLive =
    Boolean(analysis) &&
    !standing &&
    !model.drafted &&
    estimate !== null &&
    'level' in estimate &&
    LEVEL_SCALE.includes(estimate.level);
  const early = earlyLine(answer, shape, raw, entries);
  return (
    <>
      <p
        ref={ref}
        tabIndex={-1}
        className="mx-4 my-0 max-w-[var(--measure)] text-value font-semibold leading-[1.45] text-foreground focus-visible:outline-2 focus-visible:outline-solid focus-visible:outline-[var(--accent)] focus-visible:outline-offset-1"
        data-next-drift-verdict
        {...(focus ? { 'data-next-focus': `reading:${model.key}` } : {})}
      >
        {text}
      </p>
      {hidesLive ? (
        <p
          className="mx-4 my-0 max-w-[var(--measure)] text-value leading-[1.45] text-foreground"
          data-next-drift-live-hidden
        >
          {LIVE_HIDDEN}
        </p>
      ) : null}
      {early ? (
        <p
          className="mx-4 my-0 max-w-[var(--measure)] text-value leading-[1.45] text-foreground"
          data-next-drift-early
        >
          {early}
        </p>
      ) : null}
      {cleared ? (
        <p
          className="mx-4 my-0 max-w-[var(--measure)] text-value leading-[1.45] text-foreground"
          data-next-drift-cleared
        >
          {clearedLine(cleared.count, clock(cleared.readAt), cleared.corrections)}
        </p>
      ) : null}
    </>
  );
}

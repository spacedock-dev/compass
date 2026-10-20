import { SampleBeside } from '../sample/SampleMark';
import { Card } from '../ui/card';
import { Button } from '../ui/button';
import { useLayoutEffect, useRef, type ReactNode } from 'react';
import { nextNumber } from '../api/bootstrap';
import { contextKey } from '../api/identity';
import { useDisplayed } from '../shell/context';
import { useFocusKey } from '../controls';
import { ActionButton } from '../intent/ActionButton';
import { entryWindow, olderEntriesRemain, type WorkEntry } from '../intent/work';
import { markNotAccurate } from './actions';
import { DepartureSummaryLine } from '../sessions/SummaryParts';
import { useDrift } from './context';
import { EvidenceList } from './Evidence';
import { evidenceRows } from './level';
import {
  arrivedLine,
  citedKind,
  citedLine,
  claimsDrawn,
  constraintName,
  coverageLimits,
  driftAnswer,
  goalSourceLine,
  resultStale,
  resultState,
  resultStatus,
  resultWhere,
  resultWork,
  verdictLine,
  type Answer,
} from './result';
import { fmtDur } from './route';
import { clock } from '../observed';
import {
  CLAIMS,
  CLAUSE_UNRETAINED,
  DEPARTURE,
  NOT_REACHED,
  READ_INTENT,
  READ_MODEL,
  READ_NEVER,
  READ_NOT_READ,
  READ_SCOPE,
  READ_SESSION,
  READ_SUMMARY,
  RESULT_CANT_TELL,
  RESULT_DEPARTS,
  RESULT_MARK_UNSAVED,
  RESULT_MARKED,
  RESULT_NOT_ACCURATE,
  RESULT_NOT_ACCURATE_HINT,
  RESULT_NOTHING_FOUND,
  RESULT_UNMARK,
  unloadedCites,
} from './sentences';
import type { SteerSlot } from './ReadingControl';
import { isOutcomeLine, type Criterion, type Shape } from './shape';
import { Why } from './Why';

/* Accent on a reading would read as "met", a claim about intent from partial evidence. The result keeps
   secondary ink and no colour under any verdict; clay marks a departure and nothing else. */

const LABEL =
  'm-0 text-label font-semibold uppercase tracking-[.07em] text-[var(--ink-label)] [font-family:var(--mono)]';
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
  const chips = held.length ? (
    <ul className="m-0 flex list-none flex-col gap-1 p-0" data-next-cited-entries={row.key}>
      {held.map((entry) => {
        const id = String(entry.id || '');
        const where = resultWhere(entry, model.numbers) || 'Entry';
        return (
          <li
            key={id}
            className="grid min-w-0 grid-cols-[auto_minmax(0,1fr)] items-center gap-x-2.5"
          >
            <Button
              type="button"
              className="min-h-[44px] px-2.5 py-1 font-[family-name:var(--mono)] text-label"
              data-next-cockpit-action="finding-jump"
              data-next-finding={row.key}
              data-next-cite={id}
              aria-label={`Show ${where} in Full activity for ${named}`}
              onClick={(event) => chooseFinding(row.key, event.currentTarget, id)}
            >
              {where}
            </Button>
            <span className="min-w-0 text-body leading-[1.5] text-muted-foreground [overflow-wrap:anywhere]">
              {quote ? citedLine(entry) : citedKind(entry)}
            </span>
          </li>
        );
      })}
    </ul>
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
}: {
  readonly row: Criterion;
  readonly status: string;
  readonly rows: boolean;
  /** What already quotes each cited entry's words, so its record here leaves them out. */
  readonly quoted?: boolean;
}) {
  const { model } = useDrift();
  const full = resultStatus(row, model.numbers, model.byId);
  const listed = rows ? evidenceRows(row.citedIds, model.numbers, model.byId) : [];
  return (
    <Why name={`result-evidence:${row.key}`} summary="Evidence">
      <p
        className="m-0 text-body font-semibold leading-[1.45] text-foreground"
        data-next-evidence-head
      >
        {sentenceCase(row.label)}
      </p>
      {full === status ? null : <span className="next-cockpit-reading-evidence">{full}</span>}
      {row.why ? <p className="next-cockpit-reading-why">{row.why}</p> : null}
      {row.result === NOT_REACHED && row.detail ? (
        <p className="next-cockpit-reading-detail">{row.detail}</p>
      ) : null}
      {row.limit ? (
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
   headline (no model writes one: [DEC-28](../../../docs/design-session-summary.md#the-ruling) answer 7), What
   as the cited entries, and Why as the reading's stored `detail`, the one string a model wrote. */
function DepartureCard({ row, outcomes }: { readonly row: Criterion; readonly outcomes: number }) {
  const { model } = useDrift();
  const detail = String(row.detail || '').trim();
  const head = `departure-head:${model.key}:${row.key}`;
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
          <p className={`${LABEL} text-[var(--clay)]`} data-next-departure-label>
            {`Departure · ${constraintName(row.key, outcomes)}`}
          </p>
          <h4
            id={head}
            tabIndex={-1}
            className={`m-0 text-body font-semibold leading-[1.45] [overflow-wrap:anywhere] ${row.clauseKnown ? 'text-foreground' : 'text-muted-foreground'}`}
          >
            {row.clauseKnown && row.clause ? row.clause : CLAUSE_UNRETAINED}
          </h4>
        </div>
        <div className="flex max-w-[45rem] flex-col gap-1" data-next-departure-what>
          <p className={LABEL}>What</p>
          <CitedEntries row={row} quote />
        </div>
        <div className="flex max-w-[45rem] flex-col gap-0.5" data-next-departure-why>
          <p className={LABEL}>Why Compass reads this as drift</p>
          <p className="next-cockpit-reading-detail m-0">{detail || NO_DETAIL}</p>
        </div>
        {row.coverage ? <p className={QUIET}>{row.coverage}</p> : null}
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
  const status = resultStatus(row, model.numbers, model.byId, true);
  const claims = row.key === CLAIMS;
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
          <em className="next-cockpit-reading-result">{status}</em>
          {claims ? null : (
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
        {claimDeparts ? (
          <span className="next-cockpit-reading-detail">{detail || NO_DETAIL}</span>
        ) : null}
        {row.coverage ? <span className="next-cockpit-reading-why">{row.coverage}</span> : null}
        <CitedEntries row={row} />
        <EvidenceMore row={row} status={status} rows={claimDeparts} />
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

function ResultWorkView() {
  const { model } = useDrift();
  const { shape } = model;
  if (!shape) return null;
  const work = resultWork(model.entries, model.numbers, model.source.scan, shape.windowStart);
  if (!work) return null;
  return (
    <div className="next-cockpit-result-work">
      <h3>Where the work went</h3>
      <ul>
        {work.groups.map((group) => (
          <li key={group.folder} className="next-cockpit-result-folder">
            <span className="next-cockpit-result-path">
              {group.folder || 'The working directory'}
            </span>
            <span>{`${String(group.files)} file${group.files === 1 ? '' : 's'}`}</span>
            <span>{group.references}</span>
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
    </div>
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
  if (readAt === null || !model.annotate) return null;
  const unsaved = ctx.drift.notAccurate.has(model.key);
  const control = (
    <ActionButton
      weight="quiet"
      label={marked ? RESULT_UNMARK : RESULT_NOT_ACCURATE}
      busyLabel="Saving…"
      pendingKey={`not-accurate:${model.key}`}
      action="not-accurate"
      arg={String(readAt)}
      focusKey={`not-accurate:${model.key}`}
      onPress={() => {
        if (!model.identity) return;
        const top = foot.current?.getBoundingClientRect().top;
        held.current = top === undefined ? null : { top, from: marked, at: Date.now() };
        void markNotAccurate(ctx, model.identity, readAt, marked);
      }}
    />
  );
  return (
    <div
      ref={foot}
      className="next-cockpit-result-foot"
      data-next-result-mark={marked ? 'marked' : 'unmarked'}
    >
      {marked ? (
        <>
          <p className="next-cockpit-reading-why" role="status">
            {RESULT_MARKED}
          </p>
          {control}
        </>
      ) : (
        <>
          {control}
          <p className="next-cockpit-reading-why">{RESULT_NOT_ACCURATE_HINT}</p>
        </>
      )}
      {unsaved ? (
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

/* What it read, one click away: the model, the intent it read against (which revision, when and where it came
   from), how much of the session it read, and what it never reads. Revision and times are about the reading,
   never about the work. */
function Baseline({ shape, arrived }: { readonly shape: Shape; readonly arrived: string }) {
  const { model } = useDrift();
  const cap = nextNumber(model.payload['annotate_cap']);
  /* With no time it said "time not recorded"; adopted words were saved rather than typed, so their missing
     time is the save's. */
  const meta =
    shape.revisionRead === null
      ? ''
      : [
          `Version ${String(shape.revisionRead)}`,
          shape.revisionReadAt !== null
            ? `${shape.promptSource ? 'saved' : 'typed'} ${fmtDur(Math.max(0, model.generated - shape.revisionReadAt))} ago`
            : `${shape.promptSource ? 'save time' : 'time'} not recorded`,
          shape.promptSource ? 'drafted from your prompt' : '',
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
    READ_SCOPE[shape.scope] ?? shape.scopeText,
    ...readSentences(shape.cutoff),
    level?.range ? `Entries read: ${level.range}.` : '',
    level?.reasons?.first ?? '',
    goalSourceLine(shape),
    arrived,
  ].filter(Boolean);
  return (
    <Why name="reading-baseline" summary={READ_SUMMARY}>
      <div className="flex flex-col gap-[12px]" data-next-read>
        {shape.stamp ? (
          <ReadSection name="model" title={READ_MODEL}>
            <p className="next-cockpit-reading-stamp m-0">{shape.stamp}</p>
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
                <li key={line}>{line}</li>
              ))}
            </ul>
          </ReadSection>
        ) : null}
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
}: {
  /** The question before the press, which keeps the result's head while a later direction is unsettled. */
  readonly question: ReactNode;
  /** Steer back's row and box, where the control offers it. */
  readonly slotted: SteerSlot | null;
  /** The stale result's one run control. */
  readonly again: (steer: SteerSlot | null, showRun?: boolean) => ReactNode;
}) {
  const { model } = useDrift();
  const { shape, raw, annotation, entries, source } = model;
  if (!shape || !raw || !annotation) return null;
  const stale = resultStale(shape, raw, annotation, entries);
  const staleState = Boolean(stale);
  const answer =
    shape.criteria.length || shape.departures.length
      ? driftAnswer(shape, entries, source.scan)
      : null;
  const coverage = coverageLimits(shape);
  /* From the reading rather than from the live row. A reading describes the moment it was taken. */
  const arrived = arrivedLine(annotation, entries);
  const intent = shape.criteria.filter((row) => row.key !== CLAIMS);
  const outcomes = intent.filter((row) => isOutcomeLine(row.key)).length;
  /* The answer's own departures, in the reading's order: the goal, then each outcome line. */
  const departures = answer?.kind === 'departs' ? answer.departures : [];
  const departed = new Set(departures.map((row) => row.key));
  const goal = intent.filter((row) => row.key === 'goal' && !departed.has(row.key));
  const lines = intent.filter((row) => isOutcomeLine(row.key) && !departed.has(row.key));
  /* What the agent claimed, after the intent it is independent of. */
  const claimed = claimsDrawn(shape);
  const quiet = goal.length + lines.length + claimed.length > 0;
  /* A current result keeps the disclosure and accounting without a second run control.
     [DEC-27](../../../docs/design-reading-a-session.md#dec-27-the-first-view-of-a-session-is-the-goal-analyze-drift-and-the-result)
     A direction question owns the sole run path while it stands. */
  const leadSteer = !question && slotted?.lead ? slotted : null;
  const steers =
    slotted && !question ? (
      <>
        {leadSteer ? null : <div className="next-cockpit-reading-ask">{slotted.button}</div>}
        {slotted.box}
      </>
    ) : null;
  const foot = staleState
    ? steers
    : question
      ? null
      : again(leadSteer ? { ...leadSteer, button: null } : slotted, false);
  const callout = staleState && !question ? again(null) : null;
  return (
    <div className="next-session-drift-check next-cockpit-result gap-1" data-next-result>
      {question}
      {stale ? (
        <Card
          variant="reading-stale"
          className="next-cockpit-result-stale"
          data-next-result-stale={stale.kind}
        >
          <p className="next-cockpit-result-stale-head">
            {stale.before !== null
              ? `This check is from before your ${clock(stale.before)} message.`
              : stale.head}
          </p>
          {stale.superseded ? (
            <p className="next-cockpit-reading-stale">{stale.superseded}</p>
          ) : null}
          {callout}
        </Card>
      ) : null}
      {answer ? (
        <ResultAnswer
          answer={answer}
          midFlight={shape.scope === 'mid-flight'}
          focusKey={staleState || question ? null : `reading:${model.key}`}
        />
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
      <ResultWorkView />
      {/* Steer back after what it steers back from, as the design draws it. Its primary state is the card's
          own rule (`steerPrimary`), unchanged here. */}
      {leadSteer ? (
        <div className="next-cockpit-reading-ask" data-next-result-primary>
          {leadSteer.button}
        </div>
      ) : null}
      {foot ? <div className="next-cockpit-result-press">{foot}</div> : null}
      <div
        className="flex flex-wrap items-start gap-x-4 gap-y-2 border-t border-[var(--rule)] pt-2.5"
        data-next-result-footer
      >
        <ResultFoot />
        <Baseline shape={shape} arrived={arrived} />
      </div>
    </div>
  );
}

/* The Drift card's answer in one sentence, first under its heading (usability review, 2026-10-20: the level,
   the count and what they rest on were spread over the meter, the answer and each card). Drawn from the
   stored reading the result below draws, and only while that result stands: not over a running analysis, an
   unreadable reading, or one the reader marked inaccurate. */
export function DriftVerdict() {
  const { model } = useDrift();
  const { shape, raw, annotation, entries, source, job, annotate } = model;
  if (!annotate || !shape || shape.malformed || !raw || !annotation || job) return null;
  if (annotation['not_accurate'] === true) return null;
  if (!shape.criteria.length && !shape.departures.length) return null;
  const answer = driftAnswer(shape, entries, source.scan);
  const analysis = model.analysis;
  const standing = analysis && analysis.level !== 'not_enough' ? analysis : null;
  const text = verdictLine({
    answer,
    level: standing?.label ?? '',
    levelKey: standing?.level ?? '',
    reason: standing?.reasons.first ?? '',
    byId: model.byId,
    midFlight: shape.scope === 'mid-flight',
  });
  return (
    <p
      className="mx-4 my-0 max-w-[var(--measure)] text-value font-semibold leading-[1.45] text-foreground"
      data-next-drift-verdict
    >
      {text}
    </p>
  );
}

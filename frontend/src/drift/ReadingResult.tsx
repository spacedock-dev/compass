import { SampleBeside, SampleMark } from '../sample/SampleMark';
import { Card } from '../ui/card';
import { Button } from '../ui/button';
import { useLayoutEffect, useRef, type ReactNode } from 'react';
import { nextNumber } from '../api/bootstrap';
import { contextKey } from '../api/identity';
import { useDisplayed } from '../shell/context';
import { useFocusKey } from '../controls';
import { ActionButton } from '../intent/ActionButton';
import { entryWindow, olderEntriesRemain } from '../intent/work';
import { markNotAccurate } from './actions';
import { useDrift } from './context';
import { EvidenceList } from './Evidence';
import { evidenceRows } from './level';
import {
  arrivedLine,
  claimsDrawn,
  coverageLine,
  driftAnswer,
  resultStale,
  resultState,
  resultStatus,
  resultWhere,
  resultWork,
  type Answer,
  type EntryIndex,
  type Numbers,
} from './result';
import { fmtDur } from './route';
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

/* Accent on a reading would read as "met", a claim about intent from partial evidence.
   The result keeps secondary ink and no colour under any verdict. */

function ClauseCell({ row }: { readonly row: Criterion }) {
  if (row.key === CLAIMS) return null;
  return (
    <span className={`next-cockpit-reading-clause${row.clauseKnown ? '' : '-absent'}`}>
      {row.clause}
    </span>
  );
}

/* Only the post-rule row supplies prose and citations. A withdrawn verdict has already lost both; raw model
   text is never used as a fallback. */
function Account({
  row,
  showClause = true,
}: {
  readonly row: Criterion;
  readonly showClause?: boolean;
}) {
  const { model } = useDrift();
  const clause = showClause && String(row.clause || '').trim();
  const detail = String(row.detail || '').trim();
  return (
    <div className="next-cockpit-assessment-account">
      <h3>Model assessment</h3>
      {clause ? <p className="next-cockpit-assessment-clause">{`Read intent: ${clause}`}</p> : null}
      <p className="next-cockpit-reading-detail">
        {detail || 'No explanation was retained for this assessment.'}
      </p>
      <EvidenceList rows={evidenceRows(row.citedIds, model.numbers, model.byId)} scope={row.key} />
    </div>
  );
}

function Tail({ row }: { readonly row: Criterion }) {
  return row.limit ? (
    <span className="next-cockpit-reading-limit">{`limit · ${row.limit}`}</span>
  ) : (
    <>
      {row.evidence.map((line, index) => (
        <span key={index} className="next-cockpit-reading-evidence">
          {line}
        </span>
      ))}
    </>
  );
}

/* One line of the result's checklist: a glyph by state, the line's own words as its title, the ruled status
   beneath, and the source tag, why and limit one click away under "Evidence". The glyph is shape first: a
   cross for departs, a neutral filled dot for consistent (never a check, never green), a dashed circle for
   can't tell; the clay on the cross is the one colour. */
function ResultItem({
  row,
  numbers,
  byId,
  tag,
}: {
  readonly row: Criterion;
  readonly numbers: Numbers;
  readonly byId: EntryIndex;
  readonly tag: 'li' | 'div';
}) {
  const { model } = useDrift();
  const record = useDisplayed((snapshot) =>
    snapshot.records.get(contextKey(model.projectKey, model.identity)),
  );
  const status = resultStatus(row, numbers, byId, true);
  const full = resultStatus(row, numbers, byId);
  const unloaded =
    row.unloaded > 0 && olderEntriesRemain(record, entryWindow(model.session, model.payload));
  /* The press reads by the record's cursor alone, with no window shortcut, so a retained reading that cites an
     entry from before the current window keeps its way there. The sentence above stays window-bound. */
  const loadable = row.unloaded > 0 && record?.status === 'loaded' && !record.reachedStart;
  const Tag = tag;
  return (
    <Tag
      className="next-cockpit-reading-row"
      data-next-result-state={resultState(row)}
      {...(tag === 'li'
        ? {}
        : row.key === CLAIMS
          ? { 'data-next-result-claims': '' }
          : { 'data-next-result-goal': '' })}
    >
      <span className="next-cockpit-result-glyph" aria-hidden="true" />
      <span className="next-cockpit-result-body">
        <ClauseCell row={row} />
        <em className="next-cockpit-reading-result">{status}</em>
        <FindingJump row={row} loadable={loadable} />
        {row.key === CLAIMS && row.result === DEPARTURE ? (
          <Account row={row} showClause={false} />
        ) : null}
        {row.coverage ? <span className="next-cockpit-reading-why">{row.coverage}</span> : null}
        {unloaded ? (
          <span className="next-cockpit-reading-why" data-next-unloaded>
            {unloadedCites(row.unloaded)}
          </span>
        ) : null}
        <Why name={`result-evidence:${row.key}`} summary="Evidence">
          <span className="next-cockpit-reading-name">{row.label}</span>
          {full === status ? null : <span className="next-cockpit-reading-evidence">{full}</span>}
          {row.why ? <span className="next-cockpit-reading-why">{row.why}</span> : null}
          {row.result === NOT_REACHED && row.detail ? (
            <p className="next-cockpit-reading-detail">{row.detail}</p>
          ) : null}
          <Tail row={row} />
        </Why>
      </span>
    </Tag>
  );
}

/* Offered where the row's cited entries are drawn, and where some are not yet loaded and older pages remain to
   read them from: the press reads those pages itself. */
function FindingJump({ row, loadable }: { readonly row: Criterion; readonly loadable: boolean }) {
  const { chooseFinding, jumpMissing } = useDrift();
  // Kept while its "could not be loaded" sentence stands, so the way back from that sentence has a place to land.
  if (!row.citedIds.length && !loadable && jumpMissing?.press.key !== row.key) return null;
  const constraint =
    row.key === 'goal'
      ? 'Goal'
      : isOutcomeLine(row.key)
        ? `Expected outcome line ${row.key === 'output' ? '1' : row.key.slice(5)}`
        : 'What the agent claimed';
  return (
    <SampleBeside id={row.key === 'goal' ? 'cited' : ''}>
      <Button
        type="button"
        variant="bare"
        data-next-cockpit-action="finding-jump"
        data-next-finding={row.key}
        aria-label={`Show cited entries in Full activity for ${constraint}: ${row.clause}`}
        onClick={(event) => chooseFinding(row.key, event.currentTarget)}
      >
        Show cited entries
      </Button>
    </SampleBeside>
  );
}

/* The answer, and under a departure the headline with its count and a short account built from each
   departure's detail and its citation, never a model's narrative. The count renders only here. `midFlight`
   leads the answer with "So far:", so a reading of a running session never looks like a reading of how it
   ended. */
function ResultAnswer({
  answer,
  midFlight,
  primary,
  focusKey,
}: {
  readonly answer: Answer;
  readonly midFlight: boolean;
  readonly primary?: ReactNode;
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
      <>
        <h3 {...headingProps} className={`next-cockpit-result-headline ${ring}`}>
          {lead}
          <span>{RESULT_DEPARTS}</span>
          <span className="next-cockpit-result-count">{count}</span>
          <SampleMark id="analysis" />
        </h3>
        {primary}
        {answer.departures.map((row) => (
          <Account key={row.key} row={row} />
        ))}
      </>
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
  const session = [
    READ_SCOPE[shape.scope] ?? shape.scopeText,
    ...readSentences(shape.cutoff),
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
  const { shape, raw, annotation, entries, numbers, byId, source } = model;
  if (!shape || !raw || !annotation) return null;
  const stale = resultStale(shape, raw, annotation, entries);
  const staleState = Boolean(stale);
  const answer =
    shape.criteria.length || shape.departures.length
      ? driftAnswer(shape, entries, source.scan)
      : null;
  const coverage = coverageLine(shape);
  /* From the reading rather than from the live row. A reading describes the moment it was taken. */
  const arrived = arrivedLine(annotation, entries);
  const goal = shape.criteria.filter((row) => row.key === 'goal');
  const lines = shape.criteria.filter((row) => isOutcomeLine(row.key));
  /* What the agent claimed, after the intent it is independent of, under its own heading. */
  const claimed = claimsDrawn(shape);
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
          <p className="next-cockpit-result-stale-head">{stale.head}</p>
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
          primary={
            leadSteer ? (
              <div className="next-cockpit-reading-ask" data-next-result-primary>
                {leadSteer.button}
              </div>
            ) : null
          }
        />
      ) : null}
      {coverage ? (
        <p className="next-cockpit-reading-why" data-next-reading-coverage>
          {coverage}
        </p>
      ) : null}
      {goal.map((row) => (
        <ResultItem key={row.key} row={row} numbers={numbers} byId={byId} tag="div" />
      ))}
      {lines.length ? (
        <div className="next-cockpit-result-checklist">
          <h3>Against expected outcome</h3>
          <ol className="next-cockpit-result-lines">
            {lines.map((row) => (
              <ResultItem key={row.key} row={row} numbers={numbers} byId={byId} tag="li" />
            ))}
          </ol>
        </div>
      ) : null}
      {claimed.length ? (
        <div className="next-cockpit-result-claims">
          <h3>What the agent claimed</h3>
          {claimed.map((row) => (
            <ResultItem key={row.key} row={row} numbers={numbers} byId={byId} tag="div" />
          ))}
        </div>
      ) : null}
      <ResultWorkView />
      {foot ? <div className="next-cockpit-result-press">{foot}</div> : null}
      <ResultFoot />
      <Baseline shape={shape} arrived={arrived} />
    </div>
  );
}

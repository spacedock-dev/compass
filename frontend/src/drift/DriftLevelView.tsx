import { CitedText } from './CitedText';
import { Alert } from '../ui/alert';
import { Badge } from '../ui/badge';
import { Fragment } from 'react';
import { GLOSSARY, PROGRESS_LEVEL_WORDS } from '../language/glossary';
import { formatDurationWords, formatTimestamp } from '../shell/format';
import { useFocusKey } from '../controls';
import { annotationLines, goalUnavailable, storeUnreadable } from '../intent/annotation';
import { intentUnsaved } from '../intent/derive';
import { useDrift } from './context';
import { analysisRow, meterSegments, readingStored, type Signals } from './level';
import { driftAnswer, earlyReadingSeconds, verdictNamesLevel, verdictShape } from './result';
import { readingRoute, routeRefusal } from './route';
import {
  BLOCKER_LINES,
  HARNESS_LIMIT,
  WORK_HARNESSES,
  LEVEL_SCALE,
  LIVE_LEVEL_NAMES,
  LIVE_SOURCE_LINE,
  LIVE_LINE,
  LIVE_MONITOR_LINE,
  LIVE_SAVE,
  NUDGE,
  UNKNOWN_KEY,
} from './sentences';
import { EvidenceList } from './Evidence';
import { MarkedNotice } from './MarkedNotice';
import { Why } from './Why';

/* The level, its source and time, the meter, the source line and where it rose, then the nudge at High. No
   live region: the nudge is drawn, never announced, because the live estimate raises nothing
   ([DEC-26](../../../docs/design-reading-a-session.md#dec-26-four-drift-levels-and-a-live-estimate-after-every-turn)
   item 5). The legacy page's `nextDriftLevel` is the oracle. */

export function Meter({ level, dim = false }: { readonly level: string; readonly dim?: boolean }) {
  return (
    <p className="next-session-drift-meter" aria-hidden="true" {...(dim ? { 'data-dim': '' } : {})}>
      {meterSegments(level).map((segment, index) => (
        <span
          // The four segments are fixed positions on a fixed scale.
          key={index}
          className="next-session-drift-seg"
          data-level={segment.level}
          {...(segment.on ? { 'data-on': '' } : {})}
        />
      ))}
    </p>
  );
}

/* The four labels under the meter's segments, the current one marked. Hidden from a screen reader, which has
   the level word already and would otherwise hear all four after it. */
export function Scale({
  level,
  plain = false,
}: {
  readonly level: string;
  readonly plain?: boolean;
}) {
  return (
    <p className="next-session-drift-scale wrap-anywhere" aria-hidden="true">
      {LEVEL_SCALE.map((name) => (
        <span key={name} {...(name === level ? { 'data-current': '' } : {})}>
          {plain ? PROGRESS_LEVEL_WORDS.get(name) : LIVE_LEVEL_NAMES[name]}
        </span>
      ))}
    </p>
  );
}

export function PillMeter({ level }: { readonly level: string }) {
  return (
    <span className="next-session-drift-pill-meter" aria-hidden="true">
      {meterSegments(level).map((segment, index) => (
        <span
          key={index}
          className="next-session-drift-seg"
          data-level={segment.level}
          {...(segment.on ? { 'data-on': '' } : {})}
        />
      ))}
    </span>
  );
}

function SignalsView({ signals }: { readonly signals: Signals }) {
  return (
    <div className="next-cockpit-recorded-signals">
      {signals.lines.length || signals.evidence.length ? (
        <>
          <h3>Recorded signals</h3>
          {signals.lines.map((line) => (
            <p key={line} className="next-session-drift-reason">
              <CitedText text={line} />
            </p>
          ))}
          <EvidenceList rows={signals.evidence} scope="signals" />
        </>
      ) : null}
      {signals.limits.length ? (
        <>
          <h3>Limits of this estimate</h3>
          {signals.limits.map((line) => (
            <p key={line} className="next-session-drift-reason">
              <CitedText text={line} />
            </p>
          ))}
        </>
      ) : null}
    </div>
  );
}

export function DriftLevelView() {
  const { model } = useDrift();
  const { session, harness, annotation, payload } = model;
  if (!WORK_HARNESSES.includes(harness)) {
    return (
      <p className="next-session-drift-limit" data-next-drift-limit>
        {HARNESS_LIMIT}
      </p>
    );
  }
  /* No level over an unsaved draft: an estimate of drift from words the reader has not yet chosen measures
     nothing of theirs. A result's own level is drawn over the live estimate, as the design's result stage
     draws it. */
  const analysis = model.analysis;
  const measured = model.estimate;
  const found = analysis ?? measured;
  const liveOnly = harness === 'claude';
  const livePending = liveOnly && model.liveOn && !analysis;
  /* A marked analysis contributes no level, and its message carries the Undo, so it comes before every branch
     below: the live estimate, switched on, must not take the slot and leave the mark with no way back. */
  if (!model.drafted && annotation?.['not_accurate'] === true && readingStored(annotation)) {
    return null;
  }
  const save = found && 'save' in found;
  if (livePending && (model.drafted || save)) {
    return (
      <p className="next-session-drift-limit" data-next-drift-save>
        {LIVE_SAVE}
      </p>
    );
  }
  // The monitor explanation follows its switch into More; a level still stays beside Analyze.
  const running = Boolean(model.job);
  /* A reading that stands draws a level or none: with none, the verdict sentence above says what the reading
     found and why no level is drawn, so no "Not enough recorded yet" bar stands in for it. */
  const level =
    found && 'level' in found && !(found.analysis && found.level === 'not_enough') ? found : null;
  if (model.drafted || !level || !level.label) {
    /* Before any analysis there is no level, so none is drawn: "Not checked yet" over four empty segments
       labelled nothing. */
    return null;
  }
  const high = level.level === 'high' || level.level === 'extreme';
  /* While an analysis runs the design keeps the title and dims the meter, and drops the detail line. Over an
     unsaved edit the nudge would point at a press the page refuses, so it goes; the level is over the saved
     words. */
  const detail =
    level.level && !running
      ? [level.analysis ? level.line : level.monitor ? LIVE_MONITOR_LINE : LIVE_LINE, level.rose]
          .filter(Boolean)
          .join(' ')
      : '';
  const reasons = !running && level.reasons ? level.reasons : { first: '', blockers: [] };
  const signals: Signals | null = level.signals;
  /* The verdict sentence above names an analysis level, so the word is not said again over its meter. */
  const verdict = level.analysis
    ? verdictShape({
        annotate: model.annotate,
        shape: model.shape,
        raw: model.raw,
        annotation,
      })
    : null;
  const worded =
    verdict !== null && verdictNamesLevel(driftAnswer(verdict, model.entries, model.source.scan));
  return (
    <>
      <div className="next-session-drift-live" data-next-drift-level>
        <p className="next-session-drift-live-head">
          {worded ? null : <span className="next-session-drift-level">{level.label}</span>}
          {level.source && !level.monitor ? (
            <span className="next-session-drift-source">{level.source}</span>
          ) : null}
        </p>
        {level.level ? (
          <Fragment>
            <Meter level={level.level} dim={running} />
            <Scale level={level.level} />
          </Fragment>
        ) : null}
        {detail ? (
          <p className="next-session-drift-detail">
            <CitedText text={detail} />
          </p>
        ) : null}
        {level.monitor && level.note && !running ? (
          <p className="next-session-drift-reason" data-next-live-reason-line>
            {level.note}
          </p>
        ) : null}
        {/* A monitor level is a model's assessment, so the line saying there is none would contradict it. */}
        {!running && !level.analysis && !level.monitor && !readingStored(annotation) ? (
          <p className="next-session-drift-detail">No model assessment for this intent yet.</p>
        ) : null}
        {/* An analysis level's range and reason are said under What the analysis read, with the rest of
            what it read; a live estimate's stay beside it. */}
        {level.range && !running && !level.analysis ? (
          <p className="next-session-drift-range">
            <CitedText text={level.range} />
          </p>
        ) : null}
        {!signals && reasons.first && !level.analysis ? (
          <p className="next-session-drift-reason">
            <CitedText text={reasons.first} />
          </p>
        ) : null}
        {!running && signals ? <SignalsView signals={signals} /> : null}
        {reasons.blockers.length ? (
          <Why name="drift-why-not-low" summary="Why not None or low">
            {reasons.blockers.map((line) => (
              <p key={line} className="next-cockpit-reading-why">
                {line}
              </p>
            ))}
          </Why>
        ) : null}
      </div>
      {/* The design's C2 callout, placed definitely: directly under the live level at High or Extreme, before
          the control it points at. */}
      {high &&
      level.anchored &&
      !level.analysis &&
      !running &&
      !routeRefusal(payload, session) &&
      !intentUnsaved(model.input) ? (
        <Alert as="p" variant="drift-nudge" announce={false} className="next-session-drift-nudge">
          {NUDGE}
        </Alert>
      ) : null}
    </>
  );
}

/* Why the server withheld a stored reading's level, when the reason is about the reading as a whole rather than
   its rows: what the check read has changed since, or a later direction of yours it measured against is still
   unsettled. Read from the published analysis row, so the card says what the Evidence tab says. */
function withheldReason(model: ReturnType<typeof useDrift>['model']): string {
  const published = analysisRow(model.input.contexts, model.projectKey, model.session);
  const reasons = Array.isArray(published?.['reasons']) ? (published['reasons'] as unknown[]) : [];
  if (published?.['level'] !== 'not_enough') return '';
  for (const token of ['record-changed', 'later-direction'] as const) {
    if (reasons.includes(token)) return BLOCKER_LINES[token] ?? '';
  }
  return '';
}

function absence(model: ReturnType<typeof useDrift>['model']) {
  const { annotation, raw, shape, entries, source, analysis, estimate, stale } = model;
  if (stale) {
    return [
      GLOSSARY.outOfDate.plain,
      stale.kind === 'withdrawn'
        ? stale.head
        : 'This check describes earlier work or an earlier goal.',
    ];
  }
  if (model.latestCheckWithheld)
    return [GLOSSARY.cantTell.plain, 'The latest progress check did not produce a reading.'];
  if (raw && shape) {
    if (shape.malformed) return [GLOSSARY.cantTell.plain, UNKNOWN_KEY];
    const answer = driftAnswer(shape, entries, source.scan);
    const held = withheldReason(model);
    // On a departure the finding stays the answer; `ProgressAnswer` says why it carries no level.
    if (held && answer.kind !== 'departs') return [GLOSSARY.cantTell.plain, held];
    // The cited finding itself is the answer when a supported level is unavailable.
    if (answer.kind === 'departs') return null;
    if (answer.kind === 'goal-unclear')
      return [GLOSSARY.goalTooVague.plain, 'Give the goal a specific outcome Compass can check.'];
    const early = earlyReadingSeconds(answer, shape, raw, entries);
    const published = analysisRow(model.input.contexts, model.projectKey, model.session);
    const shortRecord =
      shape.scope !== 'final' &&
      analysis?.level === 'not_enough' &&
      published?.['level'] === 'not_enough' &&
      Array.isArray(published['reasons']) &&
      published['reasons'].includes('outcome-not-reached');
    if (early !== null || shortRecord)
      return [
        GLOSSARY.tooEarlyToTell.plain,
        early === null
          ? 'The record has too little work to check progress yet.'
          : `The check covered only the first ${formatDurationWords(early)} of the session.`,
      ];
    return [
      GLOSSARY.cantTell.plain,
      'The record did not give Compass enough evidence to place the work on the scale.',
    ];
  }
  // Words that exist and cannot be read are neither a goal to check nor none: say nothing, as the row does.
  if (goalUnavailable(model.session)) return null;
  if (!annotation)
    return [
      GLOSSARY.cantTell.plain,
      'Compass could not tell whether this session has a saved goal.',
    ];
  if (annotation['reading_refused'] === true)
    return [GLOSSARY.cantTell.plain, 'Compass could not read the saved check.'];
  if (
    !String(annotation['goal'] ?? '').trim() &&
    !annotationLines(annotation).length &&
    !model.drafted
  )
    return [GLOSSARY.noGoalYet.plain, 'Give Compass a goal to check progress against.'];
  if (estimate && 'level' in estimate && estimate.level === 'not_enough')
    return [
      GLOSSARY.tooEarlyToTell.plain,
      estimate.monitor
        ? 'The Live monitor had too little recorded work to check progress.'
        : 'The record has too little work to estimate progress yet.',
    ];
  // Not checked yet points at Check progress, which no harness without a reading route offers: say nothing.
  if (!readingRoute(model.payload, model.session)) return null;
  return [
    GLOSSARY.notCheckedYet.plain,
    model.liveOn
      ? 'The Live monitor has not completed a check yet.'
      : 'Compass has no saved progress check for this goal.',
  ];
}

export function SessionProgressLevel() {
  const { model } = useDrift();
  const word = PROGRESS_LEVEL_WORDS.get(model.pill?.level ?? '');
  if (!word) return null;
  return (
    <span className="text-label font-semibold" data-next-session-progress>
      {word}
      {model.pillSoFar ? ' so far' : ''}
    </span>
  );
}

export function ProgressAnswer({ focus }: { readonly focus: boolean }) {
  const { ctx, model } = useDrift();
  const { annotation, raw, stale, pill: level } = model;
  const ref = useFocusKey<HTMLDivElement>(
    ctx.shell.controls.focusLane,
    focus ? `reading:${model.key}` : null,
  );
  const marked = annotation?.['not_accurate'] === true && readingStored(annotation);
  const word = PROGRESS_LEVEL_WORDS.get(level?.level ?? '');
  const readAt = raw?.['read_at'];
  const time =
    readAt === model.generated && model.generated > 0
      ? 'just now'
      : formatTimestamp(readAt, model.generated);
  const unreadable = storeUnreadable(model.payload);
  if (model.job && !raw && !unreadable) return null;
  const missing = !level ? absence(model) : null;
  const held = !level && !missing && raw && !stale ? withheldReason(model) : '';
  const detail = level?.analysis
    ? level.line
    : level?.monitor
      ? 'From the Live monitor’s latest progress check.'
      : LIVE_SOURCE_LINE;
  return (
    <div
      ref={ref}
      tabIndex={-1}
      className="grid gap-2 px-4"
      data-next-progress-answer
      {...(focus ? { 'data-next-focus': `reading:${model.key}` } : {})}
    >
      {unreadable ? (
        <p className="text-body text-muted-foreground">{unreadable}</p>
      ) : !model.annotate ? null : marked ? (
        <MarkedNotice />
      ) : word && level ? (
        <div className="grid gap-1" data-next-drift-level>
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            {time && level.analysis ? (
              <p
                className="m-0 text-label text-muted-foreground"
                data-next-drift-stamp
              >{`Checked ${time} against your goal`}</p>
            ) : null}
            <Badge
              variant="drift-pill"
              className="ms-auto"
              data-next-drift-pill
              data-level={level.level}
              tone={
                level.level === 'medium' || level.level === 'high' || level.level === 'extreme'
                  ? level.level
                  : undefined
              }
            >
              <strong>{word}</strong>
            </Badge>
          </div>
          <Meter level={level.level} />
          <Scale level={level.level} plain />
          {level.level === 'none_or_low' ? (
            <p className="text-body">No departure found in what Compass read</p>
          ) : null}
          <p className="m-0 text-label text-muted-foreground" data-next-drift-source>
            {detail}
          </p>
        </div>
      ) : missing ? (
        <div className="grid gap-0.5 text-muted-foreground" data-next-progress-absence>
          <p
            className="m-0 text-value font-semibold"
            {...(stale ? { 'data-next-result-stale': stale.kind } : {})}
          >
            {missing[0]}
          </p>
          <p className="m-0 text-label">
            <span className="font-semibold">How this works</span> · {missing[1]}
          </p>
        </div>
      ) : held ? (
        <p className="m-0 text-label text-muted-foreground" data-next-progress-withheld>
          {held}
        </p>
      ) : null}
    </div>
  );
}

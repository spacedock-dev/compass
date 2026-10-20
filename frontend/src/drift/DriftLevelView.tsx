import { CitedText } from './CitedText';
import { Alert } from '../ui/alert';
import { Badge } from '../ui/badge';
import { Fragment } from 'react';
import { annotationLines } from '../intent/annotation';
import { intentUnsaved } from '../intent/derive';
import { useDrift } from './context';
import { meterSegments, readingStored, type Signals } from './level';
import { routeRefusal } from './route';
import {
  HARNESS_LIMIT,
  WORK_HARNESSES,
  LEVEL_HIDDEN_MARKED,
  LEVEL_SCALE,
  LIVE_LEVEL_NAMES,
  LIVE_LINE,
  LIVE_SAVE,
  NUDGE,
  UNCHECKED,
} from './sentences';
import { EvidenceList } from './Evidence';
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
export function Scale({ level }: { readonly level: string }) {
  return (
    <p className="next-session-drift-scale" aria-hidden="true">
      {LEVEL_SCALE.map((name) => (
        <span key={name} {...(name === level ? { 'data-current': '' } : {})}>
          {LIVE_LEVEL_NAMES[name]}
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

/* The header pill: a level on the scale only, never "Not enough recorded yet", and never on a Sessions row. Not
   a link: the page routes on its fragment, and the Drift section leads the column at narrow widths. */
export function DriftPill() {
  const { model } = useDrift();
  const level = model.pill;
  if (!level) return null;
  return (
    <Badge variant="drift-pill" className="next-session-drift-pill" data-next-drift-pill>
      <PillMeter level={level.level} />
      <span>
        Drift: <strong>{level.label}</strong>
      </span>
    </Badge>
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
  const found = analysis && analysis.level !== 'not_enough' ? analysis : (measured ?? analysis);
  const liveOnly = harness === 'claude';
  const livePending = liveOnly && model.liveOn && !analysis;
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
  const level = found && 'level' in found ? found : null;
  if (model.drafted || !level || !level.label) {
    /* A marked analysis contributes no level. Its slot says so, so the reader who marked it sees why the
       meter is gone, where the meter was. */
    if (!model.drafted && annotation?.['not_accurate'] === true && readingStored(annotation)) {
      return (
        <p className="next-session-drift-limit" data-next-drift-marked>
          {LEVEL_HIDDEN_MARKED}
        </p>
      );
    }
    const unchecked =
      model.annotate &&
      annotation &&
      !readingStored(annotation) &&
      Boolean(String(annotation['goal'] || '').trim() || annotationLines(annotation).length);
    if (model.drafted || !unchecked) return null;
    return (
      <>
        <div className="next-session-drift-live" data-next-drift-unchecked>
          <p className="next-session-drift-live-head">
            <span className="next-session-drift-level">{UNCHECKED}</span>
          </p>
          <Meter level="" dim={running} />
          <Scale level="" />
        </div>
      </>
    );
  }
  const high = level.level === 'high' || level.level === 'extreme';
  /* While an analysis runs the design keeps the title and dims the meter, and drops the detail line. Over an
     unsaved edit the nudge would point at a press the page refuses, so it goes; the level is over the saved
     words. */
  const detail =
    level.level && !running
      ? [level.analysis ? level.line : LIVE_LINE, level.rose].filter(Boolean).join(' ')
      : '';
  const reasons = !running && level.reasons ? level.reasons : { first: '', blockers: [] };
  const signals: Signals | null = level.signals;
  return (
    <>
      <div className="next-session-drift-live" data-next-drift-level>
        <p className="next-session-drift-live-head">
          <span className="next-session-drift-level">{level.label}</span>
          {level.source ? <span className="next-session-drift-source">{level.source}</span> : null}
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
        {!running && !level.analysis && !readingStored(annotation) ? (
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

import { nextNumber } from '../api/bootstrap';
import { compatSessKey } from '../api/identity';
import type { SessionIdentity } from '../api/types';
import { annotateOn, annotationOf, storeUnreadable, type Annotation } from '../intent/annotation';
import { identityOf } from '../intent/context';
import {
  intentDraft,
  intentDrafted,
  lineSource,
  type Draft,
  type DraftInput,
} from '../intent/derive';
import type { Held } from '../intent/held';
import {
  conflictCandidates,
  entryLabel,
  entryNumbering,
  workSource,
  type WorkEntry,
  type WorkSource,
} from '../intent/work';
import { endedAt, nativeSession, type Row } from '../observed';
import type { RecordEntry } from '../store/board';
import { harnessLabels } from '../sessions/rows';
import { analysisLevel, liveEstimate, type Contexts, type DriftLevel } from './level';
import { ciEntries } from './ciRead';
import { resultStale, type Stale } from './result';
import { readingJob, readingRoute } from './route';
import { LEVEL_SCALE } from './sentences';
import { priorDepartures, type PriorDeparture } from './prior';
import { lineRequestFloors, readingShape, type Shape } from './shape';

/* What the Drift section and the activity list below it both read, derived once per render from the board, the
   reader's held words and the observed record, so the list's "#<n>" and a reading's citations come from one
   set of entries. Nothing here fetches, sends or writes. */

export interface DriftModel {
  readonly session: Row;
  /** The board with whatever a reply told the page laid over it. */
  readonly payload: Row;
  /** The board object the card was drawn from, which a second distinct one counts as a second payload. */
  readonly base: Row;
  readonly project: string;
  readonly projectKey: string;
  readonly key: string;
  readonly identity: SessionIdentity | null;
  readonly harness: string;
  readonly annotate: boolean;
  readonly annotation: Annotation | null;
  readonly input: DraftInput;
  readonly draft: Draft | null;
  readonly drafted: boolean;
  readonly source: WorkSource;
  /** The full set, never the displayed window: a citation resolves against what the payload holds. */
  readonly entries: readonly WorkEntry[];
  readonly numbers: ReadonlyMap<string, string>;
  /** Every number the page can say, `numbers` and the fixed numbers of entries before the intent's window. */
  readonly labels: ReadonlyMap<string, string>;
  /** Entries from before the intent's window opened: numbered in `labels`, never read by Analyze. */
  readonly outside: ReadonlySet<string>;
  readonly byId: ReadonlyMap<string, WorkEntry>;
  readonly generated: number;
  readonly limit: string;
  /** Some later direction of the reader's is still unsettled, so a baseline may not be the one wanted. */
  readonly unsettled: boolean;
  readonly raw: Row | null;
  readonly shape: Shape | null;
  /** Earlier departures the store kept that the standing reading answers only with the agent's message. */
  readonly priors: readonly PriorDeparture[];
  /** The entries the surviving departures rest on, which the activity list flags "Cited". */
  readonly cited: ReadonlySet<string>;
  readonly job: Row | null;
  readonly route: Row | null;
  /** The live monitor switch is on for this session (and the harness has an estimate to show). */
  readonly liveOn: boolean;
  /** The live estimate: a level, or the instruction to save the intent first, or nothing. */
  readonly estimate: DriftLevel | { readonly save: true } | null;
  /** The level the stored reading earned, only while it read the words shown now. */
  readonly analysis: DriftLevel | null;
  /** The level the header pill shows, which never reads "Not enough recorded yet" and never shows over a draft. */
  readonly pill: DriftLevel | null;
  readonly stale: Stale | null;
  /** A newer published check attempt left no new reading. */
  readonly latestCheckWithheld: boolean;
  /** The pill's level is provisional: the session is running, or the reading it shows read a running turn. */
  readonly pillSoFar: boolean;
  /** The header's "N entries": nothing where the record was not read, because 0 would be a default. */
  readonly entryCount: number | null;
  /** The count is a floor: only the newest pages of the record are held, and older ones remain to read. The
      header, the summary's size and the window count all read it with `entryCount`, so they say one thing. */
  readonly entriesPartial: boolean;
  /** The entries since the intent's window opened, where one has and entries before it are held; else null. */
  readonly windowCount: number | null;
}

function humanLabel(value: string): string {
  const words = String(value || 'work')
    .replace(/[-_]+/g, ' ')
    .trim();
  return words ? (words[0] ?? '').toUpperCase() + words.slice(1) : 'Work';
}

/* The reading's Expected Output limit, apart from the record's own line. On Claude Code it is lifted wherever a
   reading can be made: the agent's own messages go with the words and carry a line's verdict whether or not a
   check can be sent
   ([DEC-17](../../../docs/design-reading-a-session.md#amended-2026-10-03-owner-the-agents-own-words-are-evidence)).
   With no reading model at all, the demotion stays. */
export function outputLimit(payload: Row, harness: string): string {
  if (harness === 'pi') return '';
  const label = harnessLabels(payload).get(harness) || humanLabel(harness);
  /* Its own sentence, not the record's: this row is in the panel and the record is in the activity column
     beside it, so the record line's "above" would point the wrong way here. */
  if (harness === 'codex') {
    /* Codex's agent messages are not sent, so only a check can carry a line's verdict, and only where a
       reading can carry the checks. */
    const route = readingRoute(payload, { harness });
    if (route?.['provider'] && route['destination']) return '';
    return `${label} records the checks a session ran, but no reading can carry them here, so a reading cannot judge an expected output here.`;
  }
  if (harness !== 'claude') {
    return `${label} publishes no demonstrated work results, so nothing in this session’s observed record is an inspected file, test or deliverable.`;
  }
  const route = readingRoute(payload, { harness });
  if (route?.['provider']) return '';
  return `${label} records the checks a session ran, but no reading can carry them here, so a reading cannot judge an expected output here.`;
}

export interface ModelInput {
  readonly record?: RecordEntry;
  readonly session: Row;
  readonly payload: Row;
  readonly base: Row;
  readonly project: string;
  readonly projectKey: string;
  readonly contexts: Contexts;
  readonly held: Held;
  /** The live monitor switch is on for this session. */
  readonly liveOn: boolean;
  /** The level the Live monitor's last Haiku check earned, which replaces the estimate while it stands. */
  readonly monitor?: DriftLevel | null;
}

function readingParts(input: ModelInput) {
  const { session, payload, contexts, held } = input;
  const annotate = annotateOn(payload);
  /* With the store off the page draws no words of the reader's and no stored reading, whatever the row carries. */
  const annotation = annotate ? annotationOf(session) : null;
  const draftInput: DraftInput = { held, contexts, payload, session, annotation };
  const source = workSource(contexts, input.projectKey, session, input.record);
  const entries = source.all || source.entries;
  const numbering = entryNumbering(session, source, payload);
  const numbers = new Map(
    [...numbering.numbers].map(([entry, n]) => [String(entry.id || ''), n] as const),
  );
  /* An entry before the window keeps its fixed number on a chip, muted: saving an intent once turned every chip
     before it into the bare word "entry" and the header's 62 entries into 2, as though the record were erased.
     Counted numbers start at the window, so an earlier entry has none to keep. */
  const labels = new Map(numbers);
  const outside = new Set<string>();
  for (const entry of numbering.earlier) {
    const id = String(entry.id || '');
    outside.add(id);
    const label = numbering.ordinals ? entryLabel(entry) : null;
    if (label !== null) labels.set(id, label);
  }
  const read = source.state === 'read' || source.state === 'empty';
  const harness = String(session['harness'] || '');
  const draft = intentDraft(draftInput);
  /* Any stored value that is there: a malformed one is the shape contract's to refuse, not the page's to
     skip, so the reading block draws its refusal instead of vanishing. */
  const stored = annotation?.['assessment'];
  const raw = stored ? (stored as Row) : null;
  const limit = outputLimit(payload, harness);
  /* The same open set gates the question and the reading's demotion, so those two cannot disagree about
     whether a baseline is settled. */
  const openDirections = annotate ? conflictCandidates(annotation, entries, session, draft) : [];
  const unsettled = openDirections.length > 0;
  const shape = raw
    ? readingShape(
        raw,
        annotation,
        entries,
        limit,
        unsettled,
        (line) => lineSource(line, source),
        lineRequestFloors(session, annotation, source),
        openDirections,
      )
    : null;
  const generated = nextNumber(payload['generated']) ?? 0;
  // Codex keeps its saved reading and evidence without a displayed level.
  const analysis =
    harness !== 'codex' && annotate && raw && shape
      ? analysisLevel({
          contexts,
          projectKey: input.projectKey,
          session,
          annotation,
          shape,
          work: source,
          payload,
          generated,
        })
      : null;
  const drafted = intentDrafted(draftInput);
  return {
    annotate,
    annotation,
    draftInput,
    source,
    entries,
    numbering,
    numbers,
    labels,
    outside,
    read,
    harness,
    draft,
    raw,
    limit,
    unsettled,
    shape,
    generated,
    analysis,
    drafted,
  };
}

export function buildModel(input: ModelInput): DriftModel {
  const { session, payload, contexts } = input;
  const {
    annotate,
    annotation,
    draftInput,
    source,
    entries,
    numbering,
    numbers,
    labels,
    outside,
    read,
    harness,
    draft,
    raw,
    limit,
    unsettled,
    shape,
    generated,
    analysis,
    drafted,
  } = readingParts(input);
  const estimate = liveEstimate({
    on: input.liveOn,
    monitor: input.monitor ?? null,
    harness,
    contexts,
    projectKey: input.projectKey,
    session,
    annotation,
    work: source,
    payload,
    generated,
  });
  const stale = raw && shape && annotation ? resultStale(shape, raw, annotation, entries) : null;
  const withheldAt = nextNumber(annotation?.['reading_withheld_at']);
  const readAt = nextNumber(raw?.['read_at']);
  const latestCheckWithheld =
    Boolean(annotation?.['reading_withheld']) &&
    (!raw || (withheldAt !== null && readAt !== null && withheldAt > readAt));
  // A saved reading or a refused lookup owns the slot even when it supplies no level.
  const shown = raw || annotation?.['reading_refused'] === true ? analysis : estimate;
  const pill =
    annotate &&
    annotation &&
    !storeUnreadable(payload) &&
    !drafted &&
    !stale &&
    !latestCheckWithheld &&
    shown &&
    'level' in shown &&
    LEVEL_SCALE.includes(shown.level)
      ? shown
      : null;
  /* "So far" while the turn is open: a running session's level can still move, and a reading made then
     covers only the work up to it, whatever the session has done since. A state the board does not publish
     claims neither. */
  const state = nativeSession(session)['state'];
  const running = typeof state === 'string' && state !== 'idle' && endedAt(session) === null;
  const pillSoFar =
    Boolean(pill) && (running || (pill?.analysis === true && shape?.scope === 'mid-flight'));
  const entryCount = numbers.size + numbering.earlier.length;
  const completeRecord = input.record?.status === 'loaded' && input.record.reachedStart;
  return {
    session,
    payload,
    base: input.base,
    project: input.project,
    projectKey: input.projectKey,
    key: compatSessKey(session),
    identity: identityOf(session),
    harness,
    annotate,
    annotation,
    input: draftInput,
    draft,
    drafted,
    source,
    entries,
    numbers,
    labels,
    outside,
    /* The CI checks a reading cites resolve beside the session's entries, and are in no list or numbering. */
    byId: new Map(
      [
        ...entries,
        ...ciEntries(
          shape?.ci ?? null,
          String(session['harness'] ?? ''),
          String(session['sid'] ?? ''),
        ),
      ].map((entry) => [String(entry.id || ''), entry]),
    ),
    generated,
    limit,
    unsettled,
    raw,
    shape,
    priors: annotate ? priorDepartures(session['annotation_prior_departures'], shape, entries) : [],
    cited: new Set((shape?.departures ?? []).flatMap((row) => row.citedIds || []).filter(Boolean)),
    job: readingJob(payload, session),
    route: readingRoute(payload, session),
    liveOn: input.liveOn,
    estimate,
    analysis,
    pill,
    stale,
    latestCheckWithheld,
    pillSoFar,
    entryCount: completeRecord || entryCount > 0 ? entryCount : null,
    /* Retained entries still give a floor if the first page or a later page could not be read. */
    entriesPartial: !completeRecord && entryCount > 0,
    windowCount: read && numbering.earlier.length ? numbers.size : null,
  };
}

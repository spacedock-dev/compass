import { nextNumber } from '../api/bootstrap';
import { compatSessKey } from '../api/identity';
import type { SessionIdentity } from '../api/types';
import { annotateOn, annotationOf, type Annotation } from '../intent/annotation';
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
import type { Row } from '../observed';
import type { RecordEntry } from '../store/board';
import { harnessLabels } from '../sessions/rows';
import { analysisLevel, liveEstimate, type Contexts, type DriftLevel } from './level';
import { readingJob, readingRoute } from './route';
import { LEVEL_SCALE } from './sentences';
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
  /** The header's "N entries": nothing where the record was not read, because 0 would be a default. */
  readonly entryCount: number | null;
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
}

export function buildModel(input: ModelInput): DriftModel {
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
  const unsettled = annotate && conflictCandidates(annotation, entries, session, draft).length > 0;
  const shape = raw
    ? readingShape(
        raw,
        annotation,
        entries,
        limit,
        unsettled,
        (line) => lineSource(line, session, source, payload),
        lineRequestFloors(session, annotation, source),
      )
    : null;
  const generated = nextNumber(payload['generated']) ?? 0;
  const estimate = liveEstimate({
    on: input.liveOn,
    harness,
    contexts,
    projectKey: input.projectKey,
    session,
    annotation,
    work: source,
    payload,
    generated,
  });
  const analysis =
    annotate && raw && shape
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
  /* The analysis level is unaffected by the switch, so its pill shows whichever way the switch is set. */
  const shown: DriftLevel | { readonly save: true } | null =
    analysis && analysis.level !== 'not_enough' ? analysis : (estimate ?? analysis);
  const drafted = intentDrafted(draftInput);
  const pill =
    shown && 'level' in shown && !drafted && LEVEL_SCALE.includes(shown.level) ? shown : null;
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
    byId: new Map(entries.map((entry) => [String(entry.id || ''), entry])),
    generated,
    limit,
    unsettled,
    raw,
    shape,
    cited: new Set((shape?.departures ?? []).flatMap((row) => row.citedIds || []).filter(Boolean)),
    job: readingJob(payload, session),
    route: readingRoute(payload, session),
    liveOn: input.liveOn,
    estimate,
    analysis,
    pill,
    entryCount: read ? numbers.size + numbering.earlier.length : null,
    windowCount: read && numbering.earlier.length ? numbers.size : null,
  };
}

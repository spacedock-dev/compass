import { nextNumber } from '../api/bootstrap';
import { durationSince, isRecord, type Row } from '../observed';
import { PROMPT_SOURCES } from '../sessions/intent';

/* The annotation a session row carries, read the way the legacy page reads it, and the small sentences
   built from it that the Intent log and the session page's Intent section both print. One reader for
   both, because two readings of one record is how the two surfaces came to say different things about
   the same words. Nothing here fetches or holds reader state. */

export type Annotation = Readonly<Record<string, unknown>>;

/* The fields a row publishes, spelt as `annotations.published` spells them (the legacy page derives its
   own copy from the same list). `known` below tests exactly these, so a field this list lacks is one the
   page would never notice arriving. */
export const ANNOTATION_FIELDS: readonly string[] = [
  'goal',
  'goal_why',
  'lines_why',
  'line_1',
  'line_1_source',
  'line_1_source_id',
  'line_2',
  'line_2_source',
  'line_2_source_id',
  'line_3',
  'line_3_source',
  'line_3_source_id',
  'line_4',
  'line_4_source',
  'line_4_source_id',
  'line_5',
  'line_5_source',
  'line_5_source_id',
  'line_6',
  'line_6_source',
  'line_6_source_id',
  'revision',
  'revision_count',
  'at',
  'goal_source',
  'goal_source_at',
  'goal_saved_at',
  'window_start',
  'binding_why',
  'settled_at',
  'settled_through',
  'settled_revision',
  'assessment',
  'reading_count',
  'reading_withheld',
  'reading_withheld_at',
  'reading_refused',
  'not_accurate',
  'discarded_at',
  'discarded_why',
];

/* The row's annotation, or null when it published none. Null is "nothing was typed AND no reason was
   published", which is a row from a build older than the field set and not an unannotated session: an
   unannotated row carries its absence sentences. */
export function annotationOf(session: Row | null | undefined): Annotation | null {
  if (!session) return null;
  const known = ANNOTATION_FIELDS.some((name) => {
    const value = session[`annotation_${name}`];
    return value !== undefined && value !== null && value !== '' && value !== 0;
  });
  if (!known) return null;
  return Object.fromEntries(ANNOTATION_FIELDS.map((name) => [name, session[`annotation_${name}`]]));
}

/* The store's own bound on a line, six, spelt as `reading.MAX_OUTCOME_LINES` spells it. */
export const OUTCOME_LINES_MAX = 6;

export interface OutcomeLine {
  readonly k: number;
  readonly text: string;
  readonly source: string;
  readonly sourceId: string;
}

/* The expected outcome's lines, in order, as the store publishes them: flat `line_<k>` fields. A blank
   slot is not a line. */
export function annotationLines(annotation: Annotation | null | undefined): OutcomeLine[] {
  const lines: OutcomeLine[] = [];
  for (let k = 1; k <= OUTCOME_LINES_MAX; k += 1) {
    const text = String(annotation?.[`line_${String(k)}`] || '');
    if (!text.trim()) continue;
    lines.push({
      k,
      text,
      source: String(annotation?.[`line_${String(k)}_source`] || 'typed'),
      sourceId: String(annotation?.[`line_${String(k)}_source_id`] || ''),
    });
  }
  return lines;
}

/* Where a line came from, in the reader's words, for a surface with no record to number against. */
export function outcomeLineSource(line: Pick<OutcomeLine, 'source'> | null | undefined): string {
  return line?.source === 'entry' ? 'added from an entry' : 'typed';
}

/* Whether a row is a discard record rather than words. Absence, presence and discarded are three
   states: a caller that tested only `revision_count` would fold the first and third together. */
export function annotationDiscarded(annotation: Annotation | null | undefined): boolean {
  return nextNumber(annotation?.['discarded_at']) !== null;
}

export function discardStamp(
  annotation: Annotation | null | undefined,
  generated: number | null,
): string {
  if (!annotationDiscarded(annotation)) return '';
  const age = durationSince(generated, annotation?.['discarded_at']);
  return age === null ? 'discarded, and when was not recorded' : `discarded ${age} ago`;
}

/* The record's account, and the second sentence only where a raise still quotes the words it says are
   gone. Chosen from the published sentences and never composed, because they claim things about two
   stores this page cannot check. */
export function discardAccount(
  annotation: Annotation | null | undefined,
  departures: unknown,
  published: Row,
): string[] {
  if (!annotation || !annotationDiscarded(annotation)) return [];
  const record = String(annotation['discarded_why'] || published['record'] || '');
  const rows = Array.isArray(departures) ? departures : [];
  const standing = rows.length ? String(published['record_standing'] || '') : '';
  return [record, standing].filter(Boolean);
}

/* "revision 4 of 4", or "revision 20, 16 kept" once the store has started dropping the oldest. Past the
   bound the sentence names both numbers for what they are, because read as "N of M" the pair goes
   arithmetically impossible the moment they diverge. */
export function revisionLine(
  annotation: Annotation | null | undefined,
  generated: number | null,
): string {
  const revision = nextNumber(annotation?.['revision']);
  const count = nextNumber(annotation?.['revision_count']);
  if (revision === null || count === null || count <= 0) return '';
  const age = durationSince(generated, annotation?.['at']);
  const goalSource = annotation?.['goal_source'];
  const verb = PROMPT_SOURCES.includes(goalSource as string) ? 'saved' : 'typed';
  const typed = age === null ? '' : ` · ${verb} ${age} ago`;
  return revision > count
    ? `revision ${String(revision)}, ${String(count)} kept${typed} · older revisions dropped`
    : `revision ${String(revision)} of ${String(count)}${typed}`;
}

/* The store's own character class, character for character. `records.safe_text` turns every run of
   these into ONE space, so a pasted line break was already gone at the save while the box still showed
   it. Collapsing here makes the box show what will be stored. The class is assembled from parts because
   the lint rule that forbids a control character in a pattern reads literals, and this one is the point. */
const UNSAFE_CLASS = [
  '\\u0000-\\u001f',
  '\\u007f',
  '\\u200b',
  '\\u200e',
  '\\u200f',
  '\\u202a-\\u202e',
  '\\u2066-\\u2069',
].join('');
export const HELD_UNSAFE = new RegExp(`[${UNSAFE_CLASS}]+`, 'g');

export function scrub(text: string): string {
  return text.replace(HELD_UNSAFE, ' ');
}

/* Claude Code wraps a paste in `<pasted_content id="N">` and `</pasted_content>`, and `records.strip_paste_wrapper`
   takes the two tags off before the server publishes a direction. This is the same rule on the page, for a
   direction an older server or a republished history still sends with them, so the reader never reads the
   harness's tags as their own words. The text between them stays; only the two tags go. */
const PASTE_TAG = /<\/?pasted_content(?:\s[^<>]*)?>/g;

export function stripPasteWrapper(text: string): string {
  return text.replace(PASTE_TAG, '').trim();
}

/* The server's own cap on a typed box, published as `annotate_cap`, and 240 where it did not publish one. */
export const HELD_CAP_DEFAULT = 240;

export function heldCap(payload: Row | null | undefined): number {
  const cap = nextNumber(payload?.['annotate_cap']);
  return cap !== null && cap > 0 ? Math.round(cap) : HELD_CAP_DEFAULT;
}

/* The server's sentence while the annotation store cannot be read, or "". While it stands, no box may say
   nothing was typed: the words may be on disk in a file this build could not read. */
export function storeUnreadable(payload: Row | null | undefined): string {
  return String(payload?.['annotate_unreadable'] || '');
}

export function annotateOn(payload: Row | null | undefined): boolean {
  return isRecord(payload) && payload['annotate'] === true;
}

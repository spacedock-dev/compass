import type { Outline, OutlineBlock, OutlineCoverage } from '../api/outline';
import { clock } from '../observed';

/* What the What the session has done card says from Compass's outline, before any summary exists. Every
   sentence here describes the grouping or the read behind it; none says whether the requested work was
   delivered, and a check's result is only ever the tool's own report
   ([the outline contract](../../../docs/design-session-summary.md#bounds-and-focused-grouping)). */

export const OUTLINE_LABEL = 'Outline: how Compass grouped this session, no model involved';
export const OUTLINE_LOADING = "Reading this session's record for an outline…";
export const OUTLINE_FAILED =
  'The outline could not be read. Compass tries again on the next update.';
export const OUTLINE_EMPTY = 'The part of the record Compass read holds no entries yet.';
/* A part with no prompt of its own to name: work before the first message the read holds, or work that carries on
   from a message the read did not reach. */
export const NO_PROMPT_OPENING = 'Work before your first message';
export const NO_PROMPT_CONTINUED = 'Work carrying on from earlier in this session';
/* The prompt is the person's own words, masked by the server; a block head is a glance, and the whole message
   is one press away in Full activity. */
export const PROMPT_CHARS = 180;

export type OutlineView =
  | { readonly kind: 'loading' }
  | { readonly kind: 'failed' }
  | { readonly kind: 'absent' }
  | { readonly kind: 'none'; readonly sentence: string }
  | {
      readonly kind: 'blocks';
      readonly blocks: readonly BlockView[];
      readonly notes: readonly string[];
      readonly empty: boolean;
    };

export interface BlockView {
  readonly key: string;
  readonly promptId: string | null;
  readonly prompt: string | null;
  readonly promptFull: string | null;
  /** What heads a part that has no prompt of its own. */
  readonly noPrompt: string;
  readonly at: string | null;
  readonly opening: boolean;
  /** What the part did, in short sentences. No entry numbers, and no count said twice. */
  readonly line: string;
  /** One row per check still failing, newest runs; the count of those not listed follows. */
  readonly failures: readonly { readonly factId: string; readonly title: string }[];
  readonly moreFailures: number;
}

const plural = (n: number, one: string, many: string) => `${String(n)} ${n === 1 ? one : many}`;

/* Cut at a word, never inside one: a title once ended "…after Tu". A single word longer than half the limit has
   no boundary worth keeping, so it is cut where it stands. */
export function trimPrompt(title: string): string {
  const flat = title.replace(/\s+/g, ' ').trim();
  if (flat.length <= PROMPT_CHARS) return flat;
  const room = flat.slice(0, PROMPT_CHARS - 1);
  const wholeWord = /\s/.test(flat.charAt(PROMPT_CHARS - 1));
  const space = room.lastIndexOf(' ');
  const kept = wholeWord || space < PROMPT_CHARS / 2 ? room : room.slice(0, space);
  return `${kept.replace(/[\s,;:.\-–—]+$/, '')}…`;
}

/* Why there is no outline, in the reader's words. `harness` is the harness's display name. */
export function noOutline(outline: Outline, harness: string): string {
  if (outline.state === 'unsupported')
    return `${harness} keeps no record Compass can page through, so this session has no outline. Full activity below lists what the harness reported.`;
  if (outline.state === 'stale')
    return "The session's record changed while Compass was reading it. Compass reads it again on the next update.";
  if (outline.reason === 'outline_busy')
    return 'Compass is updating this outline. It will be checked again on the next update.';
  if (outline.reason === 'time')
    return 'Compass ran out of time while reading the outline. It will try again on the next update.';
  if (outline.reason === 'outline_state_limit' || outline.reason === 'outline_stream_limit')
    return 'Compass reached an outline limit. A complete outline is not available for this record.';
  if (outline.reason === 'session_not_matched')
    return 'Compass could not match this page to exactly one session, so it read no record for an outline.';
  return "Compass could not find this session's record on this machine, so there is no outline.";
}

/* What the read behind the outline did not cover, said once above the blocks. */
export function coverageNotes(coverage: OutlineCoverage | null, more: number): string[] {
  const notes: string[] = [];
  if (coverage) {
    const replies = coverage.agentReplies === 'not_read';
    const work = coverage.checksAndFiles === 'not_admitted';
    if (replies && work)
      notes.push(
        'Only your messages are outlined for this harness: the outline has no agent replies, checks or files.',
      );
    else if (replies)
      notes.push('The outline has no agent replies: they are not read for this harness.');
    else if (work)
      notes.push('The outline has no checks or files: they are not outlined for this harness.');
  }
  const reasons = new Set(coverage?.unread.map((region) => region.reason));
  const resourceLimit = reasons.has('outline_state_limit') || reasons.has('outline_stream_limit');
  const readLimit = [
    'oversized_line',
    'outline_line_limit',
    'outline_input_limit',
    'outline_boundary_limit',
  ].some((reason) => reasons.has(reason));
  const classification = reasons.has('classification_pending');
  const unfinished = reasons.has('partial_line');
  const unreadable = reasons.has('unreadable_subagent');
  if (resourceLimit)
    notes.push('Compass reached an outline limit. Some recorded work is not included.');
  if (readLimit)
    notes.push(
      "Some recorded work could not fit within the outline's read limits and is not included.",
    );
  if (unfinished)
    notes.push('A record ends with an unfinished entry. That entry is not included yet.');
  if (unreadable)
    notes.push("A subagent's record could not be read, so some of its work is not included.");
  if (classification)
    notes.push('Compass is updating recorded checks. Check counts may change on later updates.');
  if (
    !resourceLimit &&
    !readLimit &&
    !unfinished &&
    !unreadable &&
    (!classification || reasons.size > 1)
  ) {
    if (reasons.size > 0 || coverage?.complete === false) {
      const retryable = ['bytes', 'time', 'before_window', 'children_not_read'].some((reason) =>
        reasons.has(reason),
      );
      notes.push(
        retryable
          ? 'This outline is partial. Compass will try to read more on later updates.'
          : 'This outline is partial. Some recorded work is not included.',
      );
    } else if (coverage?.complete !== true) {
      notes.push('Compass has not confirmed how much of the record this outline covers.');
    }
  }
  // Hidden groups are display omissions, not unread source or an exhaustive activity promise.
  if (more > 0)
    notes.push(
      `${plural(more, 'earlier part of this session is', 'earlier parts of this session are')} not shown here.`,
    );
  return notes;
}

const folderName = (folder: string) =>
  folder === '' || folder === '.' ? 'the project root' : folder;
const spoken = (items: readonly string[]) =>
  items.length < 2
    ? (items[0] ?? '')
    : `${items.slice(0, -1).join(', ')} and ${items.at(-1) ?? ''}`;

/* What a part did, in short sentences. Checks and files are left out where the harness's are not read, so a zero
   never stands for "not looked at". "Ran N checks" is every check run, a failing one included; the red row under
   the part is that same check, and no failure count is added to the sentence. A failure a later pass followed is
   said as fixed, in the same plain voice as the rest, because a red test written first is the work going as
   planned. One whose fix may lie in work Compass did not read is said as unread, never as still failing. */
export function blockLine(block: OutlineBlock, coverage: OutlineCoverage | null): string {
  const { counts } = block;
  const replies = coverage?.agentReplies !== 'not_read';
  const work = coverage?.checksAndFiles !== 'not_admitted';
  const did: string[] = [];
  if (replies && counts.agentMessages)
    did.push(`replied ${plural(counts.agentMessages, 'time', 'times')}`);
  if (work && counts.checks) did.push(`ran ${plural(counts.checks, 'check', 'checks')}`);
  if (work && counts.files) {
    const where = block.folders.map((row) => folderName(row.folder));
    const listed = block.folders.reduce((sum, row) => sum + row.files, 0);
    did.push(
      `wrote ${plural(counts.files, 'file', 'files')}${
        where.length ? `${listed < counts.files ? ', mostly' : ''} in ${spoken(where)}` : ''
      }`,
    );
  }
  const sentences: string[] = [];
  if (did.length) sentences.push(`The agent ${spoken(did)}.`);
  if (work && counts.checksFixed)
    sentences.push(
      counts.checksFixed === 1
        ? 'A check that failed passed on a later run.'
        : `${String(counts.checksFixed)} checks that failed passed on a later run.`,
    );
  if (work && counts.checksUnknown)
    sentences.push(
      counts.checksUnknown === 1
        ? 'A check failed here; Compass did not read whether a later run fixed it.'
        : `${String(counts.checksUnknown)} checks failed here; Compass did not read whether a later run fixed them.`,
    );
  if (counts.subagentEntries)
    sentences.push(`Subagents added ${plural(counts.subagentEntries, 'entry', 'entries')}.`);
  if (!sentences.length && replies && work)
    sentences.push('No agent work is recorded under this message.');
  if (sentences.length && block.partial) sentences.push('Counted only as far as Compass read.');
  return sentences.join(' ');
}

export function outlineView(
  outline: Outline | null,
  context: { readonly loaded: boolean; readonly failed: boolean },
  harness: string,
): OutlineView {
  if (!outline) {
    if (context.failed) return { kind: 'failed' };
    return context.loaded ? { kind: 'absent' } : { kind: 'loading' };
  }
  if (outline.state !== 'ok') return { kind: 'none', sentence: noOutline(outline, harness) };
  const blocks = outline.blocks.map((block) => ({
    key: block.span.first,
    promptId: block.prompt?.factId ?? null,
    prompt: block.prompt ? trimPrompt(block.prompt.title) : null,
    promptFull: block.prompt ? block.prompt.title : null,
    noPrompt: block.opening ? NO_PROMPT_OPENING : NO_PROMPT_CONTINUED,
    at: block.prompt?.at
      ? clock(block.prompt.at)
      : block.span.fromAt
        ? clock(block.span.fromAt)
        : null,
    opening: block.opening,
    line: blockLine(block, outline.coverage),
    failures: block.failures.map((row) => ({ factId: row.factId, title: row.title })),
    moreFailures: Math.max(0, block.counts.checksFailed - block.failures.length),
  }));
  return {
    kind: 'blocks',
    blocks,
    notes: coverageNotes(outline.coverage, outline.moreBlocks),
    empty: blocks.length === 0,
  };
}

/* The card's right-hand header: when the board this outline came with was read, and whether the session is
   still going, so a reader knows the outline can grow. */
export const STAMP_FAILED = 'the latest update could not be read';

/* `failed` is a refresh that failed while an earlier outline is still drawn. The entry's revision is then the
   failed read's, so it is not stamped as an update. */
export function outlineStamp(revision: number | null, running: boolean, failed = false): string {
  const at = failed
    ? STAMP_FAILED
    : revision !== null && revision > 0
      ? `updated ${clock(revision)}`
      : '';
  return [at, running ? 'still running' : ''].filter(Boolean).join(' · ');
}

/* Why Full activity could not show a chip's entry. One from before the intent's start is not listed there by
   design, so it is not said to have failed to load. */
export function missingSentence(n: string | null, outside: boolean): string {
  const what = n ? `entry #${n}` : 'that entry';
  return outside
    ? `Full activity lists entries from your intent’s start, so it does not show ${what}.`
    : `Full activity does not show ${what}: it could not be loaded, or it sits in a folded run of checks.`;
}

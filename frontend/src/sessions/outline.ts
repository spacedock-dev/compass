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
export const NO_PROMPT = 'Before the first message of yours this outline read';
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
  readonly at: string | null;
  readonly first: string;
  readonly last: string;
  readonly entries: number;
  readonly counts: readonly string[];
  readonly failures: readonly { readonly factId: string; readonly title: string }[];
}

const plural = (n: number, one: string, many: string) => `${String(n)} ${n === 1 ? one : many}`;

export function trimPrompt(title: string): string {
  const flat = title.replace(/\s+/g, ' ').trim();
  return flat.length > PROMPT_CHARS ? `${flat.slice(0, PROMPT_CHARS - 1).trimEnd()}…` : flat;
}

/* Why there is no outline, in the reader's words. `harness` is the harness's display name. */
export function noOutline(outline: Outline, harness: string): string {
  if (outline.state === 'unsupported')
    return `${harness} keeps no record Compass can page through, so this session has no outline. Full activity below lists what the harness reported.`;
  if (outline.state === 'stale')
    return "The session's record changed while Compass was reading it. Compass reads it again on the next update.";
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
        'Only your messages are read for this harness: the outline has no agent replies, checks or files.',
      );
    else if (replies)
      notes.push('The outline has no agent replies: they are not read for this harness.');
    else if (work)
      notes.push('The outline has no checks or files: they are not read for this harness.');
    const reasons = new Set(coverage.unread.map((region) => region.reason));
    if (coverage.startsAt !== null || reasons.has('before_window'))
      notes.push(
        "Compass read only the newest part of this session's record, so the outline starts partway.",
      );
    if (reasons.has('time') || reasons.has('bytes'))
      notes.push(
        'Compass stopped reading at its limit, so the newest entries may be missing. It reads again on the next update.',
      );
    if (reasons.has('oversized_line')) notes.push('A record line too large to read was skipped.');
    if (reasons.has('unreadable_subagent'))
      notes.push("A subagent's record could not be read, so its checks and files are not counted.");
  }
  if (more > 0)
    notes.push(
      `${plural(more, 'earlier message of yours is', 'earlier messages of yours are')} not shown here. Full activity lists every entry.`,
    );
  return notes;
}

/* The counts under a block. Checks and files are left out where the harness's are not read, so a zero never
   stands for "not looked at". */
export function blockCounts(block: OutlineBlock, coverage: OutlineCoverage | null): string[] {
  const counts = block.counts;
  const parts = [plural(block.span.entries, 'entry', 'entries')];
  if (coverage?.agentReplies !== 'not_read' && counts.agentMessages)
    parts.push(plural(counts.agentMessages, 'agent reply', 'agent replies'));
  if (coverage?.checksAndFiles !== 'not_admitted') {
    if (counts.checks)
      parts.push(
        counts.checksFailed
          ? `${plural(counts.checks, 'check', 'checks')} run, ${String(counts.checksFailed)} failed as the tool reported`
          : plural(counts.checks, 'check run', 'checks run'),
      );
    if (counts.files) {
      const folders = block.folders
        .map((row) => `${row.folder || 'no folder'} (${String(row.files)})`)
        .join(', ');
      parts.push(
        `${plural(counts.files, 'file', 'files')} written${folders ? ` in ${folders}` : ''}`,
      );
    }
  }
  if (counts.subagentEntries)
    parts.push(plural(counts.subagentEntries, 'subagent entry', 'subagent entries'));
  return parts;
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
    at: block.prompt?.at
      ? clock(block.prompt.at)
      : block.span.fromAt
        ? clock(block.span.fromAt)
        : null,
    first: block.span.first,
    last: block.span.last,
    entries: block.span.entries,
    counts: blockCounts(block, outline.coverage),
    failures: block.failures.map((row) => ({ factId: row.factId, title: row.title })),
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
export function outlineStamp(revision: number | null, running: boolean): string {
  const at = revision !== null && revision > 0 ? `updated ${clock(revision)}` : '';
  return [at, running ? 'still running' : ''].filter(Boolean).join(' · ');
}

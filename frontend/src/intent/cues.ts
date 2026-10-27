import type { Row } from '../observed';
import type { Ctx } from './context';
import { DISCARD_UNCONFIRMED, HELD_CUES, isReadsFrom, readsFromSentence } from './sentences';

/* The sentence a marked kind earns, for the element that draws it and the region that carries it. Two
   derivations of one cue is how a region comes to say something the block never printed, and the discard
   family's sentences are the server's rather than this page's, so this is the only place that knows which
   table a kind belongs to. */
export function heldSentence(kind: string, published: Row | null | undefined): string {
  if (!kind) return '';
  if (kind === 'discard-unconfirmed') return DISCARD_UNCONFIRMED;
  if (isReadsFrom(kind)) return readsFromSentence(kind);
  if (kind.startsWith('discard-')) return String(published?.[kind.slice('discard-'.length)] || '');
  return HELD_CUES[kind] ?? '';
}

export function publishedDiscard(payload: Row | null | undefined): Row {
  const said = payload?.['annotate_discard'];
  return typeof said === 'object' && said !== null && !Array.isArray(said) ? (said as Row) : {};
}

/* Speaks a stamped kind once. An armed discard goes to the assertive region alone, because the dwell before a
   second press is 1.2 seconds and a polite message queues; every other kind first takes back an armed
   warning the same key was holding, since the sentence it left standing says nothing has been deleted yet. */
export function say(ctx: Ctx, key: string, kind: string): void {
  const data = ctx.shell.runtime.store.getSnapshot().data as unknown as Row | null;
  if (kind !== 'discard-armed') ctx.shell.announcer.retractArmed(key);
  ctx.shell.announcer.announce(key, heldSentence(kind, publishedDiscard(data)), {
    assertive: kind === 'discard-armed',
  });
}

/* Stamps a mark and says it: the one point every cue family passes through. A press whose outcome is said
   once its refresh has drawn it stamps with `held.mark` and calls `say` itself. */
export function markAndSay(ctx: Ctx, key: string, kind: string): void {
  ctx.held.mark(key, kind);
  say(ctx, key, kind);
}

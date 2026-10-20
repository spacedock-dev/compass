import { useEffect } from 'react';
import { useDrift } from './context';
import { correctionStale, correctionStamp, failedChecks } from './correction';
import { composeCorrection, correctionDraft } from './steerActions';

/* On every render of the slot. Unedited, a correction from a record that no longer holds is dropped:
   recomposed from the server where there is still something to steer from, closed where there is not. Edited,
   it is the reader's and is kept, marked as composed from an older record, with Recompose beside it. Run after
   the commit, never from the render: a render never starts a request inside itself. */
export function useFollowCorrection(offered: boolean): void {
  const { ctx, model } = useDrift();
  const { key, identity } = model;
  useEffect(() => {
    const { drift } = ctx;
    const held = drift.corrections.get(key);
    const source = model.source;
    /* Only against a record read: while it is being fetched again, whether there is anything to steer from
       is not known, and a box closed then would close on a gap in the page rather than a change in the
       record. */
    const read = source.state === 'read' || source.state === 'empty';
    if (!held || held.pending || held.recomposing || !Array.isArray(held.parts) || !read) return;
    const ids = new Set(
      (source.all || source.entries || []).map((entry) => String(entry.id || '')),
    );
    if (!Array.isArray(held.cited)) {
      held.cited = held.parts
        .filter((part): part is { readonly entry: string } => typeof part !== 'string')
        .map((part) => String(part.entry || ''))
        .filter((id) => ids.has(id));
    }
    if (!Array.isArray(held.failed)) {
      held.failed = failedChecks(
        model.session,
        source.all || source.entries || [],
        source.scan,
      ).map((entry) => String(entry.id || ''));
    }
    if (!correctionStale(held, model.annotation, source, model.session)) return;
    if (held.edited) {
      if (!held.stale) {
        held.stale = true;
        drift.notify();
      }
      return;
    }
    if (!offered || !held.open) {
      drift.corrections.delete(key);
      drift.notify();
      return;
    }
    /* The old box stays drawn while the request is out, so a key typed into it lands in it rather than
       nowhere. Freeze its last rendering before this record can renumber the old server parts. */
    held.recomposeText =
      typeof held.shownText === 'string' ? held.shownText : correctionDraft(held);
    held.recomposing = true;
    if (identity) void composeCorrection(ctx, identity, correctionStamp(model.annotation), held);
  });
}

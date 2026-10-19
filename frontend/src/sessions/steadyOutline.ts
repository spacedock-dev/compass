import { useState } from 'react';
import type { ContextEntry } from '../store/board';

type Sources = Readonly<Record<string, unknown>>;

const sourcesOf = (data: unknown): Sources | null => {
  const sources = (data as { sources?: unknown } | null | undefined)?.sources;
  return sources && typeof sources === 'object' ? (sources as Sources) : null;
};

const stateOf = (sources: Sources | null): unknown =>
  (sources?.['outline'] as { state?: unknown } | undefined)?.state;

/* A read of a running session that overlaps an append answers `stale`, with no blocks and no plan. Drawing that
   would swap the outline for "the record changed while Compass was reading it" until the next revision, so the
   last good outline and its plan for the same session stay drawn while the server catches up. */
export function useSteadyOutline(
  entry: ContextEntry | undefined,
  key: string,
): ContextEntry | undefined {
  const [kept, setKept] = useState<{ readonly key: string; readonly sources: Sources } | null>(
    null,
  );
  const sources = sourcesOf(entry?.data);
  /* Derived during render, guarded so it settles: the shape `DriftProvider` uses for its shown answer. */
  if (sources && stateOf(sources) === 'ok' && (kept?.sources !== sources || kept.key !== key))
    setKept({ key, sources });
  if (!entry || !sources || stateOf(sources) !== 'stale' || kept?.key !== key) return entry;
  const summary = sources['summary'];
  const keptSummary = kept.sources['summary'];
  return {
    ...entry,
    data: {
      ...(entry.data as Record<string, unknown>),
      sources: {
        ...sources,
        outline: kept.sources['outline'],
        summary:
          summary && typeof summary === 'object' && keptSummary && typeof keptSummary === 'object'
            ? { ...summary, plan: (keptSummary as Sources)['plan'] }
            : summary,
      },
    } as unknown as ContextEntry['data'],
  };
}

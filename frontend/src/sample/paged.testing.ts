import type { SampleFixture } from './fixture';

type Json = Record<string, unknown>;
type Fact = { readonly fact_id: string; readonly type?: string };

export type CitationDepth = 'newest' | 'middle' | 'oldest';

/* The shipped sample's record split into three pages, as a longer sample's record is captured: the newest
   page, then `older-1` and `older-2` back to the start. The board's context holds only the newest page's
   messages, as a long session's tail does, so an older message is found only by reading its page. The
   reading's goal finding cites one message on the page `depth` names. The shipped fixture is one page,
   so without this a test could not tell a record read to its start from one that stopped early. */
export function pagedSample(fixture: SampleFixture, depth: CitationDepth): SampleFixture {
  const entries = (fixture.record['entries'] as Fact[]).slice();
  const third = Math.ceil(entries.length / 3);
  const pages = [
    entries.slice(0, third),
    entries.slice(third, 2 * third),
    entries.slice(2 * third),
  ];
  const page = (index: number): Json => ({
    ...fixture.record,
    entries: pages[index],
    next: index === pages.length - 1 ? null : `older-${String(index + 1)}`,
    reached_start: index === pages.length - 1,
  });
  const cited = pages[{ newest: 0, middle: 1, oldest: 2 }[depth]]?.[1] ?? pages[0]?.[0];
  const newest = new Set(pages[0]?.map((fact) => fact.fact_id));
  const messages = new Set(entries.map((fact) => fact.fact_id));
  const semantic = fixture.context['semantic'] as Json;
  const context = {
    ...fixture.context,
    semantic: {
      ...semantic,
      facts: (semantic['facts'] as Fact[]).filter(
        (fact) => !messages.has(fact.fact_id) || newest.has(fact.fact_id),
      ),
    },
  };
  const board = structuredClone(fixture.board);
  const row = (board['sessions'] as Json[])[0] as Json;
  const criteria = (row['annotation_assessment'] as Json)['criteria'] as Json;
  criteria['goal'] = { ...(criteria['goal'] as Json), cites: [cited?.fact_id] };
  return {
    ...fixture,
    board,
    context,
    record: page(0),
    older: { 'older-1': page(1), 'older-2': page(2) },
  };
}

export function citedGoal(fixture: SampleFixture): string {
  const row = (fixture.board['sessions'] as Json[])[0] as Json;
  const goal = ((row['annotation_assessment'] as Json)['criteria'] as Json)['goal'] as Json;
  return (goal['cites'] as string[])[0] ?? '';
}

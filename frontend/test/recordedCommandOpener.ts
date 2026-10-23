import { NO_NAME_COMMAND } from '../src/observed/session';

/* A session with no title whose first prompt was a command is not said to have an unpublished title
   (docs/design-frontend-migration.md#held-to-recorded-answers). The recordings still say "Title not published"
   and are never re-recorded, so a differential test restates that one phrase on the recorded side for exactly
   the rows the payload marks `first_prompt_control`, and holds every other word to the recording. */
const RECORDED = 'Title not published';

type Row = Record<string, unknown>;

export function commandOpenerRows(payload: unknown): Row[] {
  const sessions = (payload as Row | null)?.['sessions'];
  if (!Array.isArray(sessions)) return [];
  return (sessions as unknown[]).filter(
    (row): row is Row =>
      !!row && typeof row === 'object' && (row as Row)['first_prompt_control'] === true,
  );
}

export function isCommandOpener(rows: readonly Row[], sid: unknown, harness?: unknown): boolean {
  return rows.some(
    (row) =>
      String(row['sid'] ?? '') === String(sid ?? '') &&
      (harness == null || row['harness'] === harness),
  );
}

/* The observed model: any row-shaped object (a `sid`) whose `titleText` is the recorded phrase. */
export function projectRecordedCommandOpener<T>(value: T, payload: unknown): T {
  const rows = commandOpenerRows(payload);
  const walk = (node: unknown): unknown => {
    if (Array.isArray(node)) return node.map(walk);
    if (!node || typeof node !== 'object') return node;
    const entry = node as Row;
    const mapped = Object.fromEntries(
      Object.entries(entry).map(([key, item]) => [key, walk(item)]),
    );
    if (
      mapped['titleText'] === RECORDED &&
      'sid' in entry &&
      isCommandOpener(rows, entry['sid'], entry['harness'])
    )
      mapped['titleText'] = NO_NAME_COMMAND;
    return mapped;
  };
  const projected = walk(value) as Row;
  /* The coverage caveats are the distinct reasons behind a column no row could fill, so when every title is
     unknown the one recorded reason becomes each distinct reason now worded, in place. */
  const coverage = projected['coverage'] as Row | undefined;
  const caveats = coverage?.['caveats'];
  const sessions = projected['sessions'];
  if (Array.isArray(caveats) && Array.isArray(sessions) && caveats.includes(RECORDED)) {
    const reasons = [...new Set(sessions.map((row) => (row as Row)['titleText'] as string))];
    const at = caveats.indexOf(RECORDED);
    const next = [...caveats.slice(0, at), ...reasons, ...caveats.slice(at + 1)];
    return { ...projected, coverage: { ...coverage, caveats: [...new Set(next)] } } as T;
  }
  return projected as T;
}

/* A legacy Sessions row drawn as HTML: the phrase inside the row and its link's label. */
export function projectRecordedRowOpener(root: ParentNode, payload: unknown): void {
  const rows = commandOpenerRows(payload);
  root.querySelectorAll('article.next-operation-row').forEach((row) => {
    const data = (row as HTMLElement).dataset;
    if (!isCommandOpener(rows, data['nextSession'], data['nextHarness'])) return;
    const walker = document.createTreeWalker(row, NodeFilter.SHOW_TEXT);
    for (let node = walker.nextNode(); node; node = walker.nextNode())
      if (node.nodeValue?.includes(RECORDED))
        node.nodeValue = node.nodeValue.replaceAll(RECORDED, NO_NAME_COMMAND);
    row.querySelectorAll('[aria-label]').forEach((labelled) => {
      const label = labelled.getAttribute('aria-label') ?? '';
      if (label.includes(RECORDED))
        labelled.setAttribute('aria-label', label.replaceAll(RECORDED, NO_NAME_COMMAND));
    });
  });
}

/* Where the rows of a surface cannot be matched back to the payload (a rail or a project page draws its own
   links), the live side is restated instead: the new phrase reads as the recorded one. It can occur only for a
   row marked `first_prompt_control === true`, since `noTitleText` gates it on that, and the unit tests beside
   each surface hold the new phrase itself. */
export function restateLiveOpener(root: ParentNode): void {
  const walker = document.createTreeWalker(root as Node, NodeFilter.SHOW_TEXT);
  for (let node = walker.nextNode(); node; node = walker.nextNode())
    if (node.nodeValue?.includes(NO_NAME_COMMAND))
      node.nodeValue = node.nodeValue.replaceAll(NO_NAME_COMMAND, RECORDED);
  root.querySelectorAll('*').forEach((element) => {
    for (const attribute of element.getAttributeNames()) {
      const text = element.getAttribute(attribute) ?? '';
      if (text.includes(NO_NAME_COMMAND))
        element.setAttribute(attribute, text.replaceAll(NO_NAME_COMMAND, RECORDED));
    }
  });
}

export function restateLiveOpenerValue<T>(value: T): T {
  if (typeof value === 'string') return value.replaceAll(NO_NAME_COMMAND, RECORDED) as T;
  if (Array.isArray(value)) return value.map(restateLiveOpenerValue) as T;
  if (value && typeof value === 'object')
    return Object.fromEntries(
      Object.entries(value).map(([key, item]) => [key, restateLiveOpenerValue(item)]),
    ) as T;
  return value;
}

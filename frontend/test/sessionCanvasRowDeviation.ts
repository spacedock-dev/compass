/* Sessions rows follow the redesign canvas, 2026-11-24. See docs/design-frontend-migration.md#held-to-recorded-answers.
   A row is now its title, one descriptor line (harness, project, start, end), the Now line and what the
   session waits on, then the goal. The Project, Next and Blocked columns are gone: the Waiting on you tile
   carries the block. The recorded row is rearranged as the page now draws it, so the comparison still reads
   every title, harness, project, end age, Now value, held question, outcome and goal in order. The end and git
   facts are said once, so the recorded outcome and git line are joined as the page joins them, and a row with
   no goal says "No goal yet" where the recorded row offered "Add a goal". The start age
   is new, with no recorded answer, so the page's copy is set aside; the mounted tests and the Sessions
   canvas row story check it.

   2026-11-24, saved progress: the far-right cell can draw a stored departure pill
   (`data-next-drift-pill`) or a quiet date or goal word. The recorded rows have no progress cell.
   2026-11-24, absence words: a row may now draw one grey word in a far-right cell (`data-next-row-absence`,
   Not checked yet). The recorded rows never had it, so the page's copy is set aside, and the
   mounted tests, `rowAbsence.test.ts` and the canvas row story check it. Over a store that cannot be read the
   recorded row said No goal yet or offered a prompt as the goal; the page now says Saved goal unavailable
   there. Neither wording is held to the other, so the goal fact is set aside on both sides for that board. */

import { outcomeLine } from '../src/sessions/rows';

const text = (node: Element | null | undefined): string => node?.textContent ?? '';

function recordedRow(row: Element) {
  const identity = row.querySelector('.next-operation-identity');
  const harness = row.querySelector('.next-operation-harness');
  const where = row.querySelector('[data-next-operation-fact="where"]');
  const now = row.querySelector('[data-next-operation-fact="now"]');
  const blocked = row.querySelector('[data-next-operation-fact="blocked"]');
  if (!identity || !harness || !now) return;
  const doc = row.ownerDocument;
  const span = (value: string) => {
    const node = doc.createElement('span');
    node.textContent = value;
    return node;
  };

  const descriptor = doc.createElement('span');
  descriptor.setAttribute('data-next-row-descriptor', '');
  descriptor.append(span(text(harness)));
  const project = text(where?.querySelector('strong'));
  if (project.trim()) descriptor.append(' · ', span(project));
  const ended = [...now.querySelectorAll('em')].find((em) => /^ended /.test(text(em)));
  if (ended) {
    const age = span(text(ended));
    age.setAttribute('data-next-row-ended', '');
    descriptor.append(' · ', age);
    ended.remove();
  }
  harness.replaceWith(descriptor);

  const value = now.querySelector('strong');
  const task = [...identity.querySelectorAll('.next-operation-assignment')].find((line) =>
    text(line).startsWith('Current task · '),
  );
  const line = span(text(value));
  line.setAttribute('data-next-operation-fact', 'now');
  if (value?.classList.contains('next-absence') && task) {
    line.textContent = text(task);
    task.remove();
  }
  const placed: Element[] = [line];
  const note = text(blocked?.querySelector('em'));
  if (note.trim() && note.trim() !== text(value).trim()) {
    const held = span(note);
    held.setAttribute('data-next-row-block-note', '');
    placed.push(held);
  }
  // 2026-11-24: the end and git facts are said once. The recorded outcome and git line are joined the way
  // the page now joins them, so both recorded sentences still decide the compared text.
  for (const outcome of [...row.querySelectorAll('.next-operation-outcome')].filter(
    (found) => !found.parentElement?.closest('.next-operation-outcome'),
  )) {
    const git = outcome.querySelector('.next-operation-outcome');
    const said = [...outcome.childNodes]
      .filter((node) => node !== git)
      .map((node) => node.textContent ?? '')
      .join('')
      .trim();
    const facts = outcomeLine(said, text(git).trim());
    outcome.remove();
    if (!facts) continue;
    const joined = span(facts);
    joined.className = outcome.className;
    placed.push(joined);
  }
  descriptor.after(...placed);
  // 2026-11-24: a row with no goal says "No goal yet" and offers no "Add a goal" action.
  for (const add of row.querySelectorAll('[data-next-operation-fact="goal"] a')) {
    if (text(add).trim() === 'Add a goal') add.replaceWith(span('No goal yet'));
  }
  for (const retired of [
    where,
    now,
    blocked,
    row.querySelector('[data-next-operation-fact="next"]'),
  ])
    retired?.remove();
}

export function maskCanvasRow(root: ParentNode, recorded = false, goalUnavailable = false) {
  for (const row of root.querySelectorAll('article.next-operation-row')) {
    if (recorded) recordedRow(row);
    else {
      row.querySelector('[data-next-row-started]')?.remove();
      row.querySelector('[data-next-row-absence], [data-next-drift-pill]')?.remove();
    }
    if (goalUnavailable) row.querySelector('[data-next-operation-fact="goal"]')?.remove();
  }
}

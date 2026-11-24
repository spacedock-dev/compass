/* Sessions rows follow the redesign canvas, 2026-11-24. See docs/design-frontend-migration.md#held-to-recorded-answers.
   A row is now its title, one descriptor line (harness, project, start, end), the Now line and what the
   session waits on, then the goal. The Project, Next and Blocked columns are gone: the Waiting on you tile
   carries the block. The recorded row is rearranged as the page now draws it, so the comparison still reads
   every title, harness, project, end age, Now value, held question, outcome and goal in order. The start age
   is new, with no recorded answer, so the page's copy is set aside; the mounted tests and the Sessions
   canvas row story check it. */

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
  placed.push(
    ...[...row.querySelectorAll('.next-operation-outcome')].filter(
      (outcome) => !outcome.parentElement?.closest('.next-operation-outcome'),
    ),
  );
  descriptor.after(...placed);
  for (const retired of [
    where,
    now,
    blocked,
    row.querySelector('[data-next-operation-fact="next"]'),
  ])
    retired?.remove();
}

export function maskCanvasRow(root: ParentNode, recorded = false) {
  for (const row of root.querySelectorAll('article.next-operation-row')) {
    if (recorded) recordedRow(row);
    else row.querySelector('[data-next-row-started]')?.remove();
  }
}

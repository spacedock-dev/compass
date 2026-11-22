/* Sessions rows, 2026-11-23. See docs/design-frontend-migration.md#held-to-recorded-answers.
   Compare the same facts and links after setting aside the state and progress displays. */
export function maskSessionRowPresentation(root: ParentNode, recorded = false) {
  for (const row of root.querySelectorAll('article.next-operation-row')) {
    for (const node of row.querySelectorAll(
      recorded
        ? '[data-next-row-state], .next-operation-scan-only, .next-operation-drift'
        : '[data-next-row-state], .next-operation-scan-only, .next-operation-progress',
    )) {
      node.remove();
    }
    const title = row.querySelector('.next-operation-route');
    const harness = row.querySelector('.next-operation-harness');
    if (title && harness) title.after(harness);
  }
}

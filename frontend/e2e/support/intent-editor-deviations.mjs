/* The draft marks' badge became the goal's source line (docs/design-frontend-migration.md, Held to recorded
   answers, 2026-10-19): "from your prompt[ · latest| · HH:MM]" and the excerpt cue now read
   "From your prompt · first|latest|HH:MM · not saved." with the cap sentence and, for an excerpt, the cue. */
const ANALYZE_READS = 'Analyze reads at most the first 1,000 characters of any prompt.';
const EXCERPT = 'Excerpt. Analyze looks up the source when pressed.';
function sourceLine(marks) {
  const badge = marks.replace(EXCERPT, '').trim();
  const which = badge.match(/^from your prompt · (.+)$/)?.[1] ?? 'first';
  const clipped = marks.includes(EXCERPT) ? ` ${EXCERPT}` : '';
  return `From your prompt · ${which} · not saved. ${ANALYZE_READS}${clipped}`;
}

export function intentEditorDeviations(recorded) {
  const value = structuredClone(recorded);
  const added = [];
  const drafted = value.fields?.[0]?.marks.includes('from your prompt') ?? false;
  for (const field of value.fields ?? []) {
    // The popup's options are proven through its roles; the recorded native option DOM is retired.
    field.menu = [];
    // Both counts read "n / cap", as the mockup draws the goal's.
    field.counts = field.counts.map((count) => count.replace(/^(\d+)\/(\d+)$/, '$1 / $2'));
    if (field.kind === 'goal') {
      field.buttons = field.buttons.filter(([label]) => label !== 'Clear');
      if (field.marks) {
        field.marks = sourceLine(field.marks);
        field.sources = [[field.marks, false], ...field.sources];
        field.cues = field.cues.filter((cue) => cue !== EXCERPT);
      }
    }
    if (field.kind === 'lines') {
      field.label = 'Expected outcome · up to 6 lines';
      if (field.boxes.length !== 1 || field.boxes[0]) {
        added.push(...field.buttons.filter(([label]) => label === '+ Add a line'));
        field.buttons = field.buttons.filter(([label]) => label !== '+ Add a line');
      }
      if (field.boxes.length === 1 && !field.boxes[0])
        field.buttons = field.buttons.filter(
          ([label]) => label !== 'Remove' && label !== '+ Add a line',
        );
    }
  }
  value.notes = value.notes?.filter((note) => !note.startsWith('Saved'));
  if (value.footer) {
    value.footer.hint = '';
    value.footer.buttons.unshift(...added);
    value.footer.buttons = value.footer.buttons.filter(
      ([label, inert]) => label !== 'Undo changes' || !inert,
    );
  }
  if (value.question) {
    const said = value.question.said;
    const count = said.match(/You gave (\d+) later directions/)?.[1] ?? '1';
    const since =
      said.match(/since (.*?), the/)?.[1] ?? (drafted ? 'your first prompt' : 'saving your intent');
    value.question.said = `${count} later direction${count === '1' ? '' : 's'} since ${since}.`;
  }
  return value;
}

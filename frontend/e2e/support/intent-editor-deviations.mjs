/* The draft marks' badge became the goal's source line (docs/design-frontend-migration.md, Held to recorded
   answers, 2026-10-19), and the line's words changed on 2026-10-23: the recorded "from your prompt[ · latest|
   · HH:MM]" now reads "Drafted from your first|latest prompt · not saved" or "Drafted from the prompt you
   chose · not saved", and the recorded excerpt cue is the suffix " · Shortened here; Analyze reads the whole
   prompt". The cap sentence is under "What is sent", not on this line. */
const EXCERPT = 'Excerpt. Analyze looks up the source when pressed.';
const SHORTENED = ' · Shortened here; Analyze reads the whole prompt';
function sourceLine(marks) {
  const badge = marks.replace(EXCERPT, '').trim();
  const which = badge.match(/^from your prompt · (.+)$/)?.[1] ?? 'first';
  const name =
    which === 'first'
      ? 'your first prompt'
      : which === 'latest'
        ? 'your latest prompt'
        : 'the prompt you chose';
  const clipped = marks.includes(EXCERPT) ? SHORTENED : '';
  return `Drafted from ${name} · not saved${clipped}`;
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

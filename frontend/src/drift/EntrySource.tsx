import { useId } from 'react';
import { ActivityHead } from './ActivityHead';
import type { WorkRow } from './workList';
import { disclosureKey, useControls } from '../controls';
import { useControlledDisclosureState } from '../controls/useDisclosureState';

/* Where an entry came from, one press away on its row. Read out on every row it was the same record-type sentence
   eighty times over, so the head carries a small toggle and the sentence shows under it only when asked for. A
   plain toggle over the disclosure store rather than a Disclosure: one Base UI popover per row, on a list of
   hundreds, moved rows after a press had scrolled one into view. The open state is the store's, keyed like every
   disclosure (docs/design-reader-state.md#the-inventory). */
function useEntrySource(project: string, scope: string, id: string) {
  const controls = useControls();
  const key = disclosureKey({ project, scope, name: `entry-source:${id}` });
  const open = useControlledDisclosureState(controls.disclosures, key);
  const panel = useId();
  return {
    open,
    panel,
    toggle: () => {
      controls.noteToggle();
      controls.disclosures.set(key, !open);
    },
  };
}

function EntrySourceToggle({
  open,
  panel,
  label,
  onToggle,
}: {
  readonly open: boolean;
  readonly panel: string;
  readonly label: string;
  readonly onToggle: () => void;
}) {
  return (
    <button
      type="button"
      className="cursor-pointer border-0 bg-transparent p-0 text-label text-muted-foreground underline-offset-2 hover:underline"
      aria-expanded={open}
      aria-controls={panel}
      aria-label={label}
      data-next-entry-source-toggle
      onClick={onToggle}
    >
      {open ? 'Source ▴' : 'Source ▾'}
    </button>
  );
}

/* A row's head with its Source toggle, and the sentence under it while open. */
export function EntryHead({
  row,
  turnRange,
  project,
  scope,
}: {
  readonly row: WorkRow;
  readonly turnRange: string | null;
  readonly project: string;
  readonly scope: string;
}) {
  const source = useEntrySource(project, scope, row.entry.id);
  return (
    <>
      <ActivityHead
        row={row}
        turnRange={turnRange}
        source={
          <EntrySourceToggle
            open={source.open}
            panel={source.panel}
            label={`Source of entry ${row.n === null ? 'not numbered' : `#${row.n}`}`}
            onToggle={source.toggle}
          />
        }
      />
      <p id={source.panel} className="next-cockpit-work-source m-0" hidden={!source.open}>
        {row.source}
      </p>
    </>
  );
}

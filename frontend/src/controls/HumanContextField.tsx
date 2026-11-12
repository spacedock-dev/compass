import { Label } from '../ui/label';
import { Button } from '../ui/button';
import { useId, useLayoutEffect, useState, type FormEvent, type KeyboardEvent } from 'react';
import { MEMO_LIMIT, type MemoKind, type MemoState } from '../storage';
import { CharacterCount } from '../ui/CharacterCount';
import { DraftTextarea } from './DraftField';
import { useControls, useValueStore } from './kit';
import { useFocusKey } from './useFocusKey';

export interface HumanContextFieldProps {
  /** The released key, from `memoKey`: unique project key (or label), scope and kind. */
  readonly memoKey: string;
  readonly kind: MemoKind;
  readonly label: string;
  readonly placeholder: string;
}

function cueText(state: MemoState | undefined): string {
  if (state === 'error') return 'Browser storage unavailable';
  return state === 'saved' ? 'Saved in this browser' : 'Autosaves in this browser';
}

/* A note the reader keeps about a project or one session, in this browser only.
   It is saved on every input: memory first, so the words survive a storage
   failure, then storage, and the cue says which happened. The editor is an
   uncontrolled textarea, handed its words once and read through `onInput`:
   writing `value` back would erase the browser's undo history even when the text
   looked identical, and replacing the node would cost the caret, the inner
   scroll and an active composition. */
export function HumanContextField(props: HumanContextFieldProps) {
  const controls = useControls();
  const editing = useValueStore(controls.memoEditing);
  return editing?.key === props.memoKey ? (
    <Editor key={props.memoKey} {...props} fresh={editing.fresh} />
  ) : (
    <Reading {...props} />
  );
}

function editKey(memoKey: string): string {
  return `memo-edit:${memoKey}`;
}

function Reading({ memoKey, kind, label }: HumanContextFieldProps) {
  const controls = useControls();
  const ref = useFocusKey<HTMLButtonElement>(controls.focusLane, editKey(memoKey));
  const value = controls.memo.read(memoKey);
  return (
    <div className="ctl-memo" data-memo-field={kind}>
      <span>{label}</span>
      <strong>{value || 'Not set'}</strong>
      <Button
        variant="default"
        type="button"
        className="ctl-memo-edit"
        aria-label={`Edit ${label}`}
        ref={ref}
        onClick={() => controls.startMemoEdit(memoKey)}
      >
        Edit
      </Button>
    </div>
  );
}

function Editor({
  memoKey,
  kind,
  label,
  placeholder,
  fresh,
}: HumanContextFieldProps & { readonly fresh: boolean }) {
  const controls = useControls();
  const [state, setState] = useState<MemoState | undefined>(() => controls.memo.state(memoKey));
  const [initial] = useState(() => controls.memoDraft(memoKey) ?? controls.memo.read(memoKey));
  const [length, setLength] = useState(() => [...initial].length);
  const over = length > MEMO_LIMIT;
  const boxId = useId();
  const cueId = useId();
  const countId = useId();
  const focusKey = `memo:${memoKey}`;

  /* Focus on the press that opened the editor, never on a remount of one that was
     already open: a view change and back keeps whatever the reader had focused. */
  useLayoutEffect(() => {
    if (!fresh) return;
    controls.focusLane.focus(focusKey);
    controls.memoEditingSeen();
  }, [controls, fresh, focusKey]);

  const close = (restore: boolean) => {
    if (!restore && over) return;
    controls.finishMemoEdit({ restore });
    // The editor's own controls are about to leave; Edit is where the reader was.
    queueMicrotask(() => controls.focusLane.focus(editKey(memoKey)));
  };

  const onInput = (event: FormEvent<HTMLTextAreaElement>) => {
    const box = event.currentTarget;
    const text = box.value;
    const length = [...text].length;
    setLength(length);
    controls.setMemoDraft(memoKey, text);
    if (length > MEMO_LIMIT) return;
    setState(controls.memo.write(memoKey, text));
  };

  /* Escape in the box or on Done restores the original unless another tab saved,
     then closes with no announcement. Stopped here so the page's own Escape, which
     reads as "leave this view", never sees it. */
  const onKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    if (event.key !== 'Escape') return;
    event.preventDefault();
    event.stopPropagation();
    close(true);
  };

  return (
    <div className="ctl-memo ctl-memo--editing" data-memo-field={kind} onKeyDown={onKeyDown}>
      <Label htmlFor={boxId}>{label}</Label>
      <DraftTextarea
        appearance="memo"
        id={boxId}
        memoryKey={`memo:${memoKey}`}
        focusKey={focusKey}
        placeholder={placeholder}
        defaultValue={initial}
        aria-describedby={`${cueId} ${countId}`}
        aria-invalid={over || undefined}
        onInput={onInput}
      />
      <CharacterCount id={countId} length={length} limit={MEMO_LIMIT} />
      <small id={cueId} data-memo-cue={kind}>
        {over ? '' : cueText(state)}
      </small>
      <Button variant="default" type="button" disabled={over} onClick={() => close(false)}>
        Done
      </Button>
    </div>
  );
}

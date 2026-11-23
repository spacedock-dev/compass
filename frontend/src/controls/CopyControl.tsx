import { Button } from '../ui/button';
import { useId } from 'react';
import { laneKey } from './keyedState';
import { useControls, useKeyedValue } from './kit';

export type CopyKind = 'id' | 'link' | 'command';

export interface CopyControlProps {
  readonly kind: CopyKind;
  /** The exact pair. The cue is keyed on both, as everything else keyed by session is: a sid is unique within a harness and nowhere else. */
  readonly harness: string;
  readonly sid: string;
  /** What is copied: the sid, the absolute link, or the validated resume command. */
  readonly value: string;
  /** Raw values can be read from the tooltip and accessible name in technical views. */
  readonly exposeValue?: boolean;
}

const LANE = { id: 'copy', link: 'link', command: 'command' } as const;
const LABEL = { id: 'Copy ID', link: 'Copy link', command: 'Copy command' } as const;
const SAID = {
  copied: {
    id: (sid: string) => (sid ? `Copied session ID ${sid}` : 'Copied session ID'),
    link: () => 'Copied a link to this session',
    command: (value: string) => (value ? `Copied ${value}` : 'Copied re-entry command'),
  },
  failed: {
    id: () => 'Session ID could not be copied',
    link: () => 'The link to this session could not be copied',
    command: () => 'Re-entry command could not be copied',
  },
} as const;

function accessibleName(kind: CopyKind, sid: string, value: string, exposeValue: boolean): string {
  if (kind === 'id') return exposeValue ? `Copy session ID ${sid}` : 'Copy session ID';
  if (kind === 'link') return 'Copy a link to this session';
  return exposeValue ? `Copy re-entry command ${value}` : 'Copy re-entry command';
}

/* Three controls in one lane, each with its own cue: copying the ID is not proof
   the command was copied. The value rides `title` as well as the clipboard, so a
   context with no clipboard still shows the reader what to paste or type.
   Nothing here runs on mount: the clipboard is touched only inside the press. */
export function CopyControl({ kind, harness, sid, value, exposeValue = true }: CopyControlProps) {
  const controls = useControls();
  const key = laneKey(LANE[kind], harness, sid);
  const state = useKeyedValue(controls.cues, key);
  const cueId = useId();
  const cue = state === 'copied' || state === 'failed' ? state : undefined;

  const press = async () => {
    const press = controls.press();
    const announceKey = `copy:${kind}:${harness}:${sid}#${String(press)}`;
    try {
      const clipboard = controls.clipboard();
      if (!value || !clipboard) throw new Error('clipboard unavailable');
      await clipboard.writeText(value);
    } catch {
      controls.cues.remember(key, 'failed');
      controls.announce(announceKey, SAID.failed[kind]());
      return;
    }
    controls.cues.remember(key, 'copied');
    controls.announce(
      announceKey,
      SAID.copied[kind](exposeValue ? (kind === 'id' ? sid : value) : ''),
    );
  };

  return (
    <>
      <Button
        type="button"
        variant="copy"
        data-copy-kind={kind}
        {...(cue ? { 'data-copy-state': cue, 'aria-describedby': cueId } : {})}
        aria-label={accessibleName(kind, sid, value, exposeValue)}
        title={exposeValue ? value : undefined}
        onClick={() => void press()}
      >
        <span aria-hidden="true">{LABEL[kind]}</span>
      </Button>
      {cue ? (
        <span id={cueId} className="ctl-visually-hidden">
          {cue === 'copied' ? 'Copied' : 'Copy failed'}
        </span>
      ) : null}
    </>
  );
}

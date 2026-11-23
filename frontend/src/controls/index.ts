/* The shared controls and the reader-state lanes behind them. The shell builds `createControls` once
   from props (live-region announcer, storage, runtime `focus`), mounts `ControlsProvider` near the
   root, and builds one `createDisplayGate` whose `paint` is the runtime's paint option. Nothing here
   fetches, polls, opens a stream, reads browser storage directly or writes to a clipboard outside a
   press. */
export { ControlsProvider } from './ControlsProvider';
export { CopyControl, type CopyControlProps, type CopyKind } from './CopyControl';
export { DraftInput, DraftTextarea } from './DraftField';
export { Disclosure, type DisclosureProps } from './Disclosure';
export { disclosureKey } from './disclosureStore';
export {
  choiceOpenIn,
  createDisplayGate,
  installChoiceRelease,
  type DisplayGate,
} from './displayGate';
export { createFieldMemory, FIELD_MEMORY_LIMIT } from './fieldMemory';
export { createFocusLane, type FocusLane } from './focusLane';
export { HumanContextField, type HumanContextFieldProps } from './HumanContextField';
export { CUE_LIMIT, CUE_TTL_MS, laneKey } from './keyedState';
export {
  createControls,
  useControls,
  useKeyedValue,
  useValueStore,
  type Announce,
  type ClipboardLike,
  type Controls,
  type ControlsDeps,
} from './kit';
export { BriefingUnavailable } from './briefingUnavailable';
export { CopyStatusUpdate, type CopyStatusUpdateProps } from './CopyStatusUpdate';
export { RaiseControl, type RaiseControlProps } from './RaiseControl';
export { resumeCommand } from './resumeCommand';
export { useChoiceRelease } from './useChoiceRelease';
export { useDisplayedSelector } from './useDisplayed';
export { useFocusKey } from './useFocusKey';

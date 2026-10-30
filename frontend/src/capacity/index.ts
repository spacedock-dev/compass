/* The capacity strip, the usage consent and the observer-model consent controls.

   Wiring, which this step leaves to the shell:
   - the Sessions view draws `<CapacityStrip />` after its groups, as the legacy page does;
   - the Console tab passes `usage={(windows) => <RailUsage windows={windows} />}` and `observer={<ObserverControls projectKey focus />}` to
     `ProjectConsole`, which places each where the legacy Console did.
   The quota parameter rides every poll until the reader turns it off (`UsageSwitch`), and a model request
   starts only on the press of "Summarize this session". */
export { CapacityStrip } from './CapacityStrip';
export { ObserverControls, type ObserverControlsProps } from './ObserverControls';
export { RailUsage, UsageSwitch } from './UsageConsent';
export { heldFor, useConsent, useSelectedWindow, useUsageOffered, type Consent } from './held';
export {
  harnessLabels,
  projectSpread,
  rowKey,
  selectRows,
  stripRows,
  type Spread,
  type StripRow,
} from './model';

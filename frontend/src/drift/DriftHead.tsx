import { compatSessKey } from '../api/identity';
import { Disclosure, disclosureKey } from '../controls';
import { liveMonitorShown } from '../intent/liveMonitor';
import { LiveMonitorSwitch } from '../intent/LiveMonitorSwitch';
import { useDrift } from './context';
import { readingsOff, readingsOn } from './route';
import { TurnOff } from './ReadingControl';
import { SETTINGS } from './sentences';

/* What the Drift card's header holds beside its title: Drift settings, one control in every state, and,
   while model calls are paused, Resume model calls beside it, because a paused card must show how to resume
   without a second press. The Live monitor switch and Pause model calls live inside the settings, not in the
   card's body: before an analysis the body is a heading, one sentence and Analyze drift.
   [The More inventory](../../../docs/design-reading-a-session.md#where-everything-in-more-went) */
export function DriftHeadControls() {
  const { model } = useDrift();
  const off = readingsOff(model.payload);
  const monitor = liveMonitorShown(model.session, model.payload);
  const pause = readingsOn(model.payload);
  if (!off && !monitor && !pause) return null;
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1" data-next-drift-controls>
      {off ? <TurnOff head /> : null}
      {monitor || pause ? (
        <Disclosure
          variant="popover"
          disclosureKey={disclosureKey({
            project: model.project,
            scope: compatSessKey(model.session),
            name: 'drift-settings',
          })}
          summary={SETTINGS}
          focusKey={`drift-settings:${compatSessKey(model.session)}`}
        >
          <div className="flex flex-col gap-3" data-next-drift-settings>
            {monitor ? <LiveMonitorSwitch /> : null}
            {pause ? <TurnOff head /> : null}
          </div>
        </Disclosure>
      ) : null}
    </div>
  );
}

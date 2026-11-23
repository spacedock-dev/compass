import { useDrift } from './context';
import { readingsOff } from './route';
import { TurnOff } from './ReadingControl';

/* A paused card keeps the way to resume beside the action it stopped. The shared switch lives in
   AI use and privacy and Settings. */
export function DriftHeadControls() {
  const { model } = useDrift();
  return readingsOff(model.payload) ? <TurnOff head /> : null;
}

import { useEffect } from 'react';
import { Alert } from '../ui/alert';
import { compatSessKey } from '../api/identity';
import { useLiveMonitor } from '../intent/liveMonitor';
import { useShell } from '../shell/context';
import { useDrift } from './context';

/* Why the Live monitor is off, in the Drift card where the level it would have drawn is. An end the reader
   did not ask for leaves a note, kept in memory so a redraw keeps it and a reload does not; turning the
   monitor on again clears it. It is announced once, when it appears, because a monitor that turns itself
   off is a change the reader should not have to find. */
export function LiveMonitorNote() {
  const { model } = useDrift();
  const shell = useShell();
  const view = useLiveMonitor(model.session, model.payload);
  const key = `live-monitor-note:${compatSessKey(model.session)}`;
  const note = view.note;
  useEffect(() => {
    if (note) shell.announcer.announce(key, note);
  }, [shell, key, note]);
  if (!note || view.on) return null;
  return (
    <Alert as="p" variant="intent-note" className="px-4" data-next-live-note>
      {note}
    </Alert>
  );
}

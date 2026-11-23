import { useState } from 'react';
import { GLOSSARY } from '../language/glossary';
import { RouteLink } from '../shell/RouteLink';
import { useShell } from '../shell/context';
import { Alert } from '../ui/alert';
import { Button } from '../ui/button';
import { SAMPLE_HARNESS, SAMPLE_PROJECT, SAMPLE_SID } from './ids';

export function SampleInvite() {
  const { controls, runtime } = useShell();
  const dismissal = runtime.storage.sampleInvite;
  const [dismissed, setDismissed] = useState(() => dismissal.dismissed());
  if (dismissed) return null;
  return (
    <Alert
      variant="notice"
      announce={false}
      className="my-4 flex flex-wrap items-center gap-4"
      data-sample-invite
    >
      <p className="m-0 grow basis-[360px]">
        <strong>New to Compass?</strong> Open an example session to see how goals, progress checks
        and {GLOSSARY.steerBack.plain} work. Nothing in it is saved or sent.
      </p>
      <RouteLink
        variant="primary"
        route={{
          view: 'session',
          project: SAMPLE_PROJECT,
          harness: SAMPLE_HARNESS,
          session: SAMPLE_SID,
        }}
      >
        See an example
      </RouteLink>
      <Button
        emphasis="quiet"
        className="text-[var(--status-ended-ink)]"
        type="button"
        onClick={() => {
          dismissal.dismiss();
          setDismissed(true);
          controls.focusLane.focus('primary-current');
        }}
      >
        Not now
      </Button>
    </Alert>
  );
}

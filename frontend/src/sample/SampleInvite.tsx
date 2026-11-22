import { RouteLink } from '../shell/RouteLink';
import { Alert } from '../ui/alert';
import { SAMPLE_HARNESS, SAMPLE_PROJECT, SAMPLE_SID } from './ids';

/* How a new reader finds the sample, above the Sessions list. */
export function SampleInvite() {
  return (
    <Alert as="p" variant="notice" announce={false} className="mb-3" data-sample-invite>
      <strong>New to Compass?</strong>{' '}
      <RouteLink
        route={{
          view: 'session',
          project: SAMPLE_PROJECT,
          harness: SAMPLE_HARNESS,
          session: SAMPLE_SID,
        }}
      >
        See a sample session (view only)
      </RouteLink>{' '}
      to see how Compass shows a session’s goal and the results of progress checks.
    </Alert>
  );
}

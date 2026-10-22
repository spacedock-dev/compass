import type { ReactNode } from 'react';
import { compatSessKey } from '../api/identity';
import { Disclosure, disclosureKey } from '../controls';
import { readingRoute, routeRefusal } from '../drift/route';
import { CLAUDE_READER_LIMIT, STEER_HARNESSES, WORK_HARNESSES } from '../drift/sentences';
import { harnessLabels } from '../sessions/rows';
import { usePanel } from './useIntent';
import type { Row } from '../observed';

export function HowTo() {
  const { payload, session, project } = usePanel();
  return <IntentHowTo payload={payload} session={session} project={project} />;
}

export function IntentHowTo({
  payload,
  session,
  project,
  children,
}: {
  readonly payload: Row;
  readonly session?: Row;
  readonly project: string;
  readonly children?: ReactNode;
}) {
  const harness = String(session?.['harness'] || '');
  const labels = harnessLabels(payload);
  const label = (key: string) =>
    labels.get(key) || ({ claude: 'Claude Code', pi: 'Pi' }[key] ?? key);
  const route = session ? readingRoute(payload, session) : null;
  const reader = route?.['provider']
    ? String(route['label'] || route['provider'])
    : session
      ? routeRefusal(payload, session)
      : 'availability is shown in each session';
  const steer =
    session && STEER_HARNESSES.includes(harness)
      ? 'available here'
      : `${STEER_HARNESSES.map(label).join(' and ')} only`;
  return (
    <Disclosure
      disclosureKey={disclosureKey({
        project,
        scope: session ? compatSessKey(session) : 'sessions',
        name: 'intent-howto',
      })}
      summary="How Intent and drift works"
      variant="popover"
      focusKey={`intent-howto:${session ? compatSessKey(session) : 'sessions'}`}
    >
      <h3 className="text-body font-semibold">How Intent and drift works</h3>
      <p>
        1. Give the goal. A session's /goal is detected and used until you edit it; else Compass
        drafts from your first prompt.
      </p>
      <p>
        2. Press Analyze drift. It asks once to allow the reading and counts against a daily cap,
        shown beside the button.
      </p>
      <p>
        3. Read where the work left your goal. On Claude Code, copy a correction to steer it back.
      </p>
      <p
        data-next-intent-howto-limit
      >{`Drift level: ${WORK_HARNESSES.map(label).join(' and ')} sessions only. Analyze drift here: ${reader}${reader.endsWith('.') ? '' : '.'} Steer back: ${steer}. Compass never writes into sessions.`}</p>
      <p data-next-intent-howto-no-line>
        With no expected outcome line: no level, and “Can't tell” unless your goal departs.
      </p>
      <p data-next-intent-howto-settle>
        Readings settle a command's latest unpiped run, failed or passed with nothing written after
        it. A recorded write breaking a folder limit also departs.
      </p>
      <p data-next-intent-howto-accuracy>{CLAUDE_READER_LIMIT}</p>
      {children}
    </Disclosure>
  );
}

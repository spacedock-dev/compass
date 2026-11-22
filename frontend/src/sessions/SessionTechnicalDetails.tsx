import { useContext, useSyncExternalStore, type ReactNode } from 'react';
import { compatSessKey } from '../api/identity';
import { useControls } from '../controls';
import { useControlledDisclosureState } from '../controls/useDisclosureState';
import { TechnicalReadingEvidence } from '../drift/ReadingResult';
import { SessionAiPrivacy } from './SessionAiPrivacy';
import { SessionCheckSettings } from './SessionCheckSettings';
import { TechnicalDetails } from '../controls/TechnicalDetails';
import { GLOSSARY } from '../language/glossary';
import type { Row } from '../observed';
import { SampleMark } from '../sample/SampleMark';
import { TourContext } from '../sample/tourContext';
import { ACTIVITY_LOG, TECHNICAL_EVIDENCE, fullActivityKey } from './fullActivityKey';

export function SessionTechnicalDetails({
  project,
  session,
  children,
  reports,
}: {
  readonly project: string;
  readonly session: Row;
  readonly children: ReactNode;
  readonly reports: ReactNode;
}) {
  const sample = useContext(TourContext);
  const key = fullActivityKey(project, session);
  const { disclosures, technicalTabs } = useControls();
  const open = useControlledDisclosureState(disclosures, key);
  const selected = useSyncExternalStore(technicalTabs.subscribe, () => technicalTabs.read(key));

  return (
    <div
      className="next-session-activity"
      data-next-session-activity
      data-next-session-full-activity
    >
      <TechnicalDetails
        disclosureKey={key}
        focusKey={`full-activity:${compatSessKey(session)}`}
        aside={sample ? <SampleMark id="activity" /> : null}
        tabs={[
          { id: ACTIVITY_LOG, label: GLOSSARY.activityLog.plain, content: children },
          {
            id: 'ai-use',
            label: GLOSSARY.aiUseAndPrivacy.plain,
            content: open ? <SessionAiPrivacy /> : null,
          },
          {
            id: 'check-settings',
            label: 'Check settings',
            content: open ? <SessionCheckSettings visible={selected === 'check-settings'} /> : null,
          },
          {
            id: TECHNICAL_EVIDENCE,
            label: 'Evidence',
            content: open && selected === TECHNICAL_EVIDENCE ? <TechnicalReadingEvidence /> : null,
          },
          { id: 'reports', label: 'Reports', content: reports },
        ]}
      />
    </div>
  );
}

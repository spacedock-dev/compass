import { useContext, type ReactNode } from 'react';
import { compatSessKey } from '../api/identity';
import { TechnicalDetails } from '../controls/TechnicalDetails';
import { GLOSSARY } from '../language/glossary';
import type { Row } from '../observed';
import { SampleMark } from '../sample/SampleMark';
import { TourContext } from '../sample/tourContext';
import { ACTIVITY_LOG, fullActivityKey } from './fullActivityKey';

export function SessionTechnicalDetails({
  project,
  session,
  children,
}: {
  readonly project: string;
  readonly session: Row;
  readonly children: ReactNode;
}) {
  const sample = useContext(TourContext);
  return (
    <div
      className="next-session-activity"
      data-next-session-activity
      data-next-session-full-activity
    >
      <TechnicalDetails
        disclosureKey={fullActivityKey(project, session)}
        focusKey={`full-activity:${compatSessKey(session)}`}
        aside={sample ? <SampleMark id="activity" /> : null}
        tabs={[{ id: ACTIVITY_LOG, label: GLOSSARY.activityLog.plain, content: children }]}
      />
    </div>
  );
}

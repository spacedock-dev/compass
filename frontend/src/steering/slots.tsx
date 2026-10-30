import { ObserverControls, RailUsage } from '../capacity';
import { ProjectConsole } from '../delegation';
import type { ProjectSlots } from '../project/slots';
import { ProjectDecisions } from './ProjectDecisions';
import { ProjectSteer } from './ProjectSteer';
import { StageConditions } from './StageConditions';

/* The pieces of the project page this step supplies, in the shape the project page's slots take. The page
   composes them by `PROJECT_SLOTS = STEERING_SLOTS`; nothing else here knows where they are mounted. Each is
   a function of what the page knows (the exact project, its stable key, the exact selected session and the
   sessions in scope), and none starts a request of its own beyond the passive reads the board makes. */
export const STEERING_SLOTS: ProjectSlots = {
  steering: ({ project }) => <ProjectSteer project={project} />,
  courseConditions: ({ sessions }) => <StageConditions sessions={sessions} />,
  decisions: ({ project, projectKey, focus }) => (
    <ProjectDecisions project={project} projectKey={projectKey} focus={focus} />
  ),
  console: ({ project, projectKey, focus }) => (
    <ProjectConsole
      project={project}
      projectKey={projectKey}
      focus={focus}
      usage={(windows) => <RailUsage windows={windows} />}
      observer={<ObserverControls projectKey={projectKey} focus={focus} />}
    />
  ),
  projectsConditions: () => <StageConditions sessions={null} />,
};

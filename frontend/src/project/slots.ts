import type { ReactNode } from 'react';
import type { SessionIdentity } from '../api/types';
import { STEERING_SLOTS } from '../steering/slots';
import { nativeSession } from '../observed';
import type { ProjectModel } from './model';

/* What the project page leaves to the steering step: the steering bar, the stage conditions, the
   Decisions tab's timeline and the Console tab's operating rail. Each is a function of what the page
   knows (the exact project, its stable key, the exact selected session and the sessions in scope) and
   draws a stated placeholder until the step supplies it, because a blank would read as an empty healthy
   panel. The composition lives in one place, `PROJECT_SLOTS`, and the views never import the steering
   step, so neither step depends on the other's internals. */
export interface ProjectSlotContext {
  /** The route's project label, exactly: it keys every disclosure and every draft. */
  readonly project: string;
  /** The stable project key the context is read by, which is not always the label. */
  readonly projectKey: string;
  /** The exact selected session, or null at project scope. `state` decides whether a final output is yet a result. */
  readonly focus: (SessionIdentity & { readonly state?: string }) | null;
  /** The exact sessions in scope: the focused one, or the project's. */
  readonly sessions: readonly SessionIdentity[];
}

export interface ProjectSlots {
  /** The project's steering bar, between the recovery strip and the tabs. */
  readonly steering?: (context: ProjectSlotContext) => ReactNode;
  /** The workflow stage conditions waiting on the reader, above the Course evidence. */
  readonly courseConditions?: (context: ProjectSlotContext) => ReactNode;
  /** The Decisions tab's body: the decision summary and the semantic timeline. */
  readonly decisions?: (context: ProjectSlotContext) => ReactNode;
  /** The Console tab's body: the operating rail, the terminal and the setup disclosure. */
  readonly console?: (context: ProjectSlotContext, view?: 'usage' | 'technical') => ReactNode;
  /** The stage conditions above the Projects list: every workflow, as that page shows them. */
  readonly projectsConditions?: () => ReactNode;
}

/** The slots as the page ships them. The steering step's components replace the placeholders here, and nowhere else. */
export const PROJECT_SLOTS: ProjectSlots = STEERING_SLOTS;

export function slotContext(model: ProjectModel): ProjectSlotContext {
  const identity = model.focusIdentity;
  return {
    project: model.route.project,
    projectKey: model.projectKey,
    focus: identity
      ? {
          ...identity,
          state: String(model.focus ? (nativeSession(model.focus)['state'] ?? '') : ''),
        }
      : null,
    sessions: identity
      ? [identity]
      : model.group.sessions.flatMap((row) =>
          row['harness'] && row['sid']
            ? [{ harness: String(row['harness']), sid: String(row['sid']) }]
            : [],
        ),
  };
}

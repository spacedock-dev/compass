/* The Sessions screen and the session page: the observed model drawn as rows, one exact session's detail,
   and the answer to a request it holds. The pieces the Intent step mounts (the departure rows, the
   re-entry line, the goal-focus request) are exported beside the screens that own their wording. */
export { AnswerBlock } from './AnswerBlock';
export { SessionDetail } from './SessionDetail';
export { SessionsView, StatusDot } from './SessionsView';
export { RouteAnchor } from './RouteAnchor';
export { goalFocusFor, answerNotesFor } from './heldState';
export {
  intentDraft,
  promptCandidate,
  sessionInstruction,
  PROMPT_SOURCES,
  PROMPT_CHOSEN,
  type PromptCandidate,
} from './intent';
export { departureRow, deliveryAbsence, unaskedDepartures, raiseLimit } from './detail';
export { DepartureReentry, UnaskedDepartureBody } from './DepartureParts';

/* Notifications: when a banner is raised, who raises it, and the Settings control that asks the reader. The
   owner is one per runtime and sees every accepted payload; the control is a press, never a prompt on
   load. */
export {
  askBanner,
  harnessName,
  notifyEdge,
  sessionBanner,
  type Banner,
  type NotifyEdge,
} from './edges';
export { NotificationControl } from './NotificationControl';
export {
  createNotifyHost,
  createNotifyOwner,
  LANE_REPORT_ATTEMPTS,
  QUIET_REPEAT_MS,
  type NotifyControlState,
  type NotifyDeps,
  type NotifyHost,
  type NotifyOwner,
} from './owner';
export {
  notifyOwnerFor,
  startNotifications,
  type NotifyOptions,
  type NotifyRuntime,
} from './registry';

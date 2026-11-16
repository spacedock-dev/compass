import { nativeSession } from '../observed/native';
import {
  asPayload,
  isRecord,
  payloadAskRows,
  payloadSessionRows,
  type Row,
} from '../observed/values';
import { askBanner, notifyEdge, sessionBanner, type Banner } from './edges';

/* What a tab does about notifications, as one owner outside the rendered tree. It is built once per
   runtime and fed every accepted payload, so StrictMode's second effect, a remount and a route change
   cannot make a second one: two owners would each hold their own idea of what was already announced, and
   every banner would appear twice. The legacy page's `next-notify.js`, held to it by the differential test.

   Nothing here runs a banner or a request on mount. A banner is created for a transition the board
   published after the first payload it saw (primed), only while this tab owns the browser lane and the
   reader has granted permission; the permission prompt opens only on a press; the lane report is the one
   POST this module sends, and it names two scalars about the tab and no session. */

export interface NotifyHost {
  /** Whether the browser has a Notification API at all, read live so a test can script it. */
  supported(): boolean;
  /** `default`, `granted`, `denied`, or `unsupported`. */
  permission(): string;
  /** Opens the browser's prompt; `done` runs when the reader answers. */
  request(done: () => void): void;
  /** Raises one banner. May throw: permission can be revoked while a tab is open. */
  create(title: string, options: { readonly body: string; readonly tag: string }): void;
}

export interface NotifyDeps {
  readonly host: NotifyHost;
  readonly now: () => number;
  /** The lane report; true when the server accepted it. */
  readonly postLane: () => Promise<boolean>;
  /** Whether this tab is the one that holds the live stream. */
  readonly isLeader: () => boolean;
}

export type NotifyControlState = 'enable' | 'blocked' | null;

/* Match the native popup_repeat_suppress_sec precedent, not all native gates. A later real turn inside
   this per-tab window can also be suppressed. */
export const QUIET_REPEAT_MS = 600 * 1000;

/* Three, then stop until something changes. A post only fails when the server is broken, and retrying one
   per poll against a broken server is the heartbeat this whole design exists to avoid. */
export const LANE_REPORT_ATTEMPTS = 3;

export function createNotifyHost(): NotifyHost {
  const api = (): typeof Notification | undefined =>
    typeof Notification === 'undefined' ? undefined : Notification;
  return {
    supported: () => api() !== undefined,
    permission: () => {
      const notification = api();
      return notification ? notification.permission || 'default' : 'unsupported';
    },
    request(done) {
      const notification = api();
      if (!notification || !notification.requestPermission) return;
      let result: Promise<unknown> | undefined;
      try {
        result = (
          notification.requestPermission as (callback: () => void) => Promise<unknown> | undefined
        )(done);
      } catch {
        return;
      }
      if (result && typeof result.then === 'function') result.then(done, done);
    },
    create(title, options) {
      const notification = api();
      if (!notification) throw new Error('Notification is not available');
      new notification(title, options);
    },
  };
}

export function createNotifyOwner(deps: NotifyDeps) {
  const { host } = deps;
  const listeners = new Set<() => void>();
  let version = 0;
  let shownPermission = host.permission();
  let lastPayload: Row | null = null;

  let sessionStates = new Map<string, unknown>();
  let primed = false;
  let notifiedAsks = new Set<string>();
  const quietNudgedAt = new Map<string, number>();
  const stageNotified = new Set<string>();
  let stagePrimed = false;

  let laneInFlight = false;
  let laneReportedThrough = 0;
  let laneReportedEver = false;
  let laneFailures = 0;

  function bump(): void {
    version += 1;
    for (const listener of [...listeners]) listener();
  }

  /* Whether this tab raises the banners. The server's own native lane takes it when it publishes one, so
     the two never both fire for one transition. */
  function browserOwns(payload: Row | null): boolean {
    return !(payload && payload['native_notify']) && host.supported();
  }

  function raise(banner: Banner): boolean {
    try {
      host.create(banner.title, { body: banner.body, tag: banner.tag });
      return true;
    } catch {
      // Permission can be revoked while a tab is open, and a lane is not a claim that a banner appeared.
      return false;
    }
  }

  /* Under [DEC-19](docs/design-reading-a-session.md#dec-19-the-page-may-report-a-lane-never-a-delivery) the
     page may report that a notification lane EXISTS in it, and may never report a delivery. So this posts
     two scalars about the tab, names no session, and is never sent per raise.

     Only a WORKING lane is reported. A tab reporting that it has no lane would say nothing true about the
     board: several tabs can be open, and this one being blocked says nothing about another that is not.

     WHEN IT RESENDS, and why it is not a load-time one-shot. The page has no way to know the server
     restarted, and a report that lives in the server's memory is gone when it does. So the condition is a
     DISAGREEMENT: this tab has a lane and the payload says none has been reported. That covers the first
     render, the permission grant and a restart, without a heartbeat and without a token for the boot. Once
     the payload agrees, nothing is sent again. */
  function laneReportNeeded(payload: Row | null): boolean {
    if (laneInFlight) return false;
    if (!host.supported() || host.permission() !== 'granted') return false;
    if (payload && payload['browser_lane'] === true) {
      laneFailures = 0;
      return false;
    }
    if (laneFailures >= LANE_REPORT_ATTEMPTS) return false;
    /* A server that does not publish the key at all is one this page cannot read an answer from, so it gets
       one report and never a second. Treating a missing key as a disagreement is the same heartbeat by
       another route, and it is the likelier one: a page from this build against a server from an older
       one sees exactly that. */
    if (!(payload && Object.hasOwn(payload, 'browser_lane'))) return !laneReportedEver;
    /* Gated on the payload being NEWER than the one last posted against. The page renders many times per
       collection, and the server's answer cannot appear until the next one, so without this every render
       between the post and the next payload posts again. */
    const generated = Number(payload['generated']);
    return !Number.isFinite(generated) || generated > laneReportedThrough;
  }

  function reportLane(payload: Row | null): void {
    if (!laneReportNeeded(payload)) return;
    const generated = Number(payload && payload['generated']);
    laneInFlight = true;
    const settle = (ok: boolean): void => {
      laneInFlight = false;
      if (ok) {
        laneFailures = 0;
        laneReportedEver = true;
        if (Number.isFinite(generated)) laneReportedThrough = generated;
      } else {
        laneFailures += 1;
      }
    };
    try {
      deps.postLane().then(settle, () => settle(false));
    } catch {
      settle(false);
    }
  }

  return {
    /* One accepted payload. Runs for every body the store accepts, before it is shown: a transition is a
       fact about the board, not about what the reader has been shown, and a paint held back by an open
       option list must not delay a banner. */
    sync(input: unknown): void {
      const payload = asPayload(input);
      lastPayload = payload;
      reportLane(payload);
      const seen = new Map<string, unknown>();
      const now = deps.now();
      for (const [key, issuedAt] of quietNudgedAt) {
        if (now - issuedAt >= QUIET_REPEAT_MS) quietNudgedAt.delete(key);
      }
      const fire = browserOwns(payload) && host.permission() === 'granted';
      for (const source of payloadSessionRows(payload)) {
        const session = nativeSession(source);
        const key = `${String(session['harness'])}:${String(session['sid'])}`;
        const edge = notifyEdge(session, sessionStates.get(key));
        seen.set(key, session['state']);
        if (!fire || !primed || !edge) continue;
        const quiet = session['state'] === 'idle';
        if (quiet && quietNudgedAt.has(key)) continue;
        if (raise(sessionBanner(payload, session, edge)) && quiet) quietNudgedAt.set(key, now);
      }

      const asks = payload['ask'] && Array.isArray(payload['asks']) ? payloadAskRows(payload) : [];
      const seenAsks = new Set<string>();
      const fresh: Row[] = [];
      for (const ask of asks) {
        const id = String(ask['id'] || '');
        if (!id) continue;
        seenAsks.add(id);
        if (fire && !notifiedAsks.has(id)) fresh.push(ask);
      }
      notifiedAsks = seenAsks;
      if (fresh.length) raise(askBanner(payload, fresh));

      const stage = payload['tripwires'];
      if (isRecord(stage) && stage['enabled']) {
        const rules = Array.isArray(stage['rules']) ? (stage['rules'] as unknown[]) : [];
        for (const rule of rules) {
          if (!isRecord(rule)) continue;
          const id = String(rule['event_id'] || '');
          if (!id || stageNotified.has(id)) continue;
          stageNotified.add(id);
          if (!stagePrimed || !fire || !deps.isLeader()) continue;
          raise({
            title: 'Workflow stage condition',
            body: `${String(rule['workflow'])}: ${String(rule['why'])}`,
            tag: id,
          });
        }
        stagePrimed = true;
      }
      sessionStates = seen;
      primed = true;
      if (host.permission() !== shownPermission) {
        shownPermission = host.permission();
        bump();
      }
    },

    /* The header's control: a button while the reader can still be asked, a note once they said no, and
       nothing where a banner is not this tab's to raise or has already been allowed. */
    control(input: unknown): NotifyControlState {
      const payload = isRecord(input) ? input : null;
      if (!payload || !browserOwns(payload)) return null;
      const permission = host.permission();
      if (permission === 'granted' || permission === 'unsupported') return null;
      return permission === 'denied' ? 'blocked' : 'enable';
    },

    /* The only way the browser's prompt opens. */
    request(): void {
      host.request(() => {
        shownPermission = host.permission();
        // A grant is what makes the tab a lane, and it should be reported now rather than at the next poll.
        reportLane(lastPayload);
        bump();
      });
    },

    subscribe(listener: () => void): () => void {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    version: (): number => version,
  };
}

export type NotifyOwner = ReturnType<typeof createNotifyOwner>;

import { isRecord } from '../observed/values';

/* Turn off quota reading hides every figure the board publishes for a credential-backed row, on every
   surface that draws one: the Sessions strip, the project's Usage view and Needs you. Claude's row counts as
   credential-backed whichever source filled it, the fetch or Claude Code's own status line, because the
   switch sits on that row and a reader who turned it off expects its percentages gone
   ([Q-13](docs/design-usage-quota.md#q-13)). Codex reads disk and Antigravity hands its quota over, so their
   local readings stay. This is a display rule: the server still publishes what it holds. */
const LOCAL_QUOTA = new Set(['codex', 'antigravity']);

export function quotaShown(harness: unknown, off: boolean): boolean {
  return !off || LOCAL_QUOTA.has(String(harness ?? ''));
}

const filtered = new WeakMap<object, Record<string, unknown>>();

/* The payload with the hidden rows' `usage` entries removed, the same object while the switch is on. One
   copy per payload, so a selector that reads it returns a stable value between polls. */
export function withoutHiddenQuota<T>(payload: T, off: boolean): T {
  if (!off || !isRecord(payload) || !Array.isArray(payload['usage'])) return payload;
  let shown = filtered.get(payload);
  if (!shown) {
    shown = {
      ...payload,
      usage: (payload['usage'] as unknown[]).filter(
        (entry) => isRecord(entry) && quotaShown(entry['harness'], true),
      ),
    };
    filtered.set(payload, shown);
  }
  return shown as T;
}

/* Whether the payload holds a row the switch is hiding, so a surface can say a window was read. */
export function hidesQuota(payload: unknown, off: boolean): boolean {
  return (
    off &&
    isRecord(payload) &&
    Array.isArray(payload['usage']) &&
    payload['usage'].some((entry) => isRecord(entry) && !quotaShown(entry['harness'], true))
  );
}

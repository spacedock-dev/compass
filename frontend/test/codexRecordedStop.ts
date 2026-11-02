/* Departure, 2026-11-02 (docs/design-frontend-migration.md#held-to-recorded-answers): Codex joined Claude Code
   in the list of harnesses read at a turn stop, so a Codex row's recorded `turn_end_at` is a stop on this page
   and was not on the retired one, whose list stayed `["claude"]`. The retired page answers from its recording
   and cannot be asked a different question, so a differential test sends it the recorded payload unchanged and
   takes the field off Codex rows on this page's side only. Every other answer is still held to the recording;
   the stop itself is held by `observed.test.ts` and the Drift stories. */
export function withoutCodexRecordedStop<T>(row: T): T {
  if (typeof row !== 'object' || row === null || Array.isArray(row)) return row;
  const held = row as Record<string, unknown>;
  if (held['harness'] !== 'codex') return row;
  const { turn_end_at: _recorded, ...rest } = held;
  return rest as T;
}

export function withoutCodexRecordedStops<T>(payload: T): T {
  if (typeof payload !== 'object' || payload === null || Array.isArray(payload)) return payload;
  const held = payload as Record<string, unknown>;
  if (!Array.isArray(held['sessions'])) return payload;
  return {
    ...held,
    sessions: (held['sessions'] as unknown[]).map(withoutCodexRecordedStop),
  } as T;
}

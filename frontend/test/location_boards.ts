type Row = Record<string, unknown>;

export function locationBoard(count = 9): Row {
  return {
    generated: 1900000000,
    sessions: Array.from({ length: count }, (_, i) => ({
      harness: 'claude',
      sid: `audit-${String(i)}`,
      project: 'audits',
      project_key: 'path:audits',
      checkout_key: 'checkout:a7b8c9',
      project_identity_source: 'working directory path',
      title: `Audit ${String(i)}`,
      state: 'idle',
      started_at: 1899999000 + i,
      last_activity: 1899999990,
      worktree: null,
    })),
    harnesses: [{ key: 'claude', label: 'Claude Code', reports_needs_input: true }],
  };
}

export const locationRows = (board: Row) => board['sessions'] as Row[];

export function locationRow(board: Row, index: number): Row {
  const row = locationRows(board)[index];
  if (!row) throw new Error(`No fixture row ${String(index)}`);
  return row;
}

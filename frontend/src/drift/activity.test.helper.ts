import type { WorkEntry } from '../intent/work';
import { toolReportLine, toolReportParts, type WorkRow } from './workList';

export function activityRow(
  n: number,
  extra: Partial<WorkEntry> = {},
  flags: WorkRow['flags'] = [],
): WorkRow {
  const entry: WorkEntry = {
    id: `c${String(n)}`,
    type: 'tool_report',
    by: 'agent',
    summary: `check ${String(n)}`,
    at: 900 + n,
    resultAt: null,
    sourceSession: { harness: 'claude', sid: 's1' },
    workerKind: '',
    actorClaim: '',
    modelDerived: false,
    subject: 'check',
    checkId: '',
    copied: false,
    work: true,
    result: '',
    resultSource: '',
    resultReason: '',
    earlierFailed: false,
    beforeLastChange: false,
    changedAfter: false,
    readIncomplete: false,
    ordinal: null,
    ordinalSub: null,
    source: 'transcript',
    ...extra,
  };
  return {
    entry,
    n: String(n),
    head: { report: toolReportLine(entry), ...toolReportParts(entry) },
    flags,
    source: 'transcript',
    at: `${String(100 - n)}s ago`,
    turn: false,
    add: false,
  };
}

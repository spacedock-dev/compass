import { Card } from '../ui/card';
import type { ReactNode } from 'react';
import type { CapacityWindow, Observed, Row } from '../observed';
import { isRecord } from '../observed';
import { RailHeader } from '../steering/RailHeader';
import { SLOT_LABELS, capacityRows, type CapacityRailRow } from './capacityRows';
import './delegation.css';

/* A window the payload published no clock for still draws its level, and says what is missing in the
   observed model's own words, never a pace it was not given. */
const MISSING = {
  pace: 'Window pace not reported',
  resets: 'Reset time not published',
  clock: 'Window clock not published',
} as const;

function harnessLabel(payload: Row, harness: string): string {
  const labels = new Map<string, string>();
  for (const row of Array.isArray(payload['harnesses']) ? payload['harnesses'] : []) {
    if (!isRecord(row)) continue;
    const key = String(row['key'] || '');
    if (key) labels.set(key, String(row['label'] || key));
  }
  return labels.get(String(harness || '')) || String(harness || '') || 'Source not identified';
}

function WindowRow({
  row,
  window,
  label,
}: {
  readonly row: CapacityRailRow;
  readonly window: CapacityWindow | undefined;
  readonly label: string;
}) {
  const hot = row.paceRatio !== null && row.paceRatio >= 1;
  const usedInk = row.pct >= 80 ? 'amber' : row.pct >= 50 ? 'secondary' : 'primary';
  const paceKnown = window?.paceKnown === true;
  const paceInk = !paceKnown ? 'next-rail-reason' : hot ? 'next-rail-pace--hot' : '';
  const ink =
    row.paceRatio === null
      ? 'unknown'
      : row.paceRatio >= 1.5
        ? 'clay'
        : row.paceRatio >= 1
          ? 'amber'
          : 'accent';
  const clockKnown = window?.clockKnown === true;
  const clockText = window?.clockText ?? MISSING.clock;
  const resetsKnown = window?.resetsKnown === true;
  return (
    <div className="next-rail-capacity-window" data-next-rail-window={`${row.harness}:${row.slot}`}>
      <div className="next-rail-capacity-heading">
        <b>{label}</b>
        <span>{SLOT_LABELS[row.slot]}</span>
        <strong className={`next-rail-used--${usedInk}`}>{`${String(row.pct)}%`}</strong>
      </div>
      <div
        className="next-rail-capacity-bar"
        role="img"
        aria-label={`${String(row.pct)}% used; ${clockText}`}
      >
        <span
          className={`next-rail-capacity-fill next-rail-capacity-fill--${ink}`}
          style={{ width: `${String(row.pct)}%` }}
        />
        {row.elapsed === null ? null : (
          <span
            className="next-rail-capacity-tick"
            style={{ left: `${(row.elapsed * 100).toFixed(2)}%` }}
          />
        )}
      </div>
      {clockKnown ? null : <p className="next-rail-reason">{clockText}</p>}
      <div className="next-rail-capacity-caption">
        <span className={paceInk}>
          {window?.paceText ?? MISSING.pace}
          {paceKnown ? ' pace' : ''}
        </span>
        <span>·</span>
        <span className={resetsKnown ? '' : 'next-rail-reason'}>
          {resetsKnown ? 'resets ' : ''}
          {window?.resetsText ?? MISSING.resets}
        </span>
      </div>
    </div>
  );
}

/* Each quota window on its own clock, ranked by when its budget ends. The consent to fetch the numbers and
   the switch that changes it belong to the capacity step and arrive through `usage`; this panel draws only
   what the payload published and never asks for more. */
export function CapacityPanel({
  payload,
  model,
  usage,
}: {
  readonly payload: Row;
  readonly model: Pick<Observed, 'windows' | 'capacityEmptyText' | 'capacityEmptyNoteText'>;
  /** The usage disclosure and switch, drawn after the windows. Told whether any window is drawn above it. */
  readonly usage?: (windows: boolean) => ReactNode;
}) {
  const windows = new Map(model.windows.map((window) => [window.key, window]));
  const rows = capacityRows(payload);
  return (
    <Card
      as="section"
      variant="rail-panel"
      className="next-rail-panel"
      data-next-rail-panel="capacity"
    >
      <RailHeader label="CAPACITY" note="each window on its own clock" sentence />
      {rows.length ? (
        rows.map((row, index) => (
          <WindowRow
            // Two usage entries can publish one harness; the index keeps their rows apart.
            key={`${row.harness}\u0000${row.slot}\u0000${String(index)}`}
            row={row}
            window={windows.get(`${row.harness}:${row.slot}`)}
            label={harnessLabel(payload, row.harness)}
          />
        ))
      ) : (
        <>
          <p className="next-rail-reason">{model.capacityEmptyText}</p>
          <p className="next-rail-reason">{model.capacityEmptyNoteText}</p>
        </>
      )}
      {usage?.(rows.length > 0)}
    </Card>
  );
}

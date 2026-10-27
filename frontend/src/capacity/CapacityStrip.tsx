import { Card } from '../ui/card';
import { Button } from '../ui/button';
import { Fragment, useEffect, useMemo, type ReactNode } from 'react';
import { nextNumber } from '../api/bootstrap';
import { useFocusKey } from '../controls/useFocusKey';
import type { Row } from '../observed';
import { useDisplayed, useShell } from '../shell/context';
import { heldFor, useSelectedWindow } from './held';
import {
  duration,
  endsOf,
  fillInk,
  harnessLabels,
  projectSpread,
  rowKey,
  selectRows,
  SLOT_LABELS,
  stripRows,
  untimedCount,
  type Spread,
  type StripRow,
} from './model';
import { UsageSwitch } from './UsageConsent';
import './capacity.css';

/* The capacity strip: each quota window the board published as the budget spent against the clock spent,
   ranked by when the budget ends, with the selected window's remaining budget in the unit the decision is
   made in. Nothing here composes a verdict ([DEC-12](docs/design-usage-quota.md#q-12)): the budget's end time
   and the window's reset time sit next to each other and the reader compares them. A window with no clock
   draws no tick and prints its absence, an unmeasured pace is never a zero, and a spent budget says so.

   A pure render of the board being shown, apart from the selected window, which is the reader's and is held
   by vendor and window key for the life of the tab. Nothing here fetches, polls or acts. */

/* Before the first board there is nothing to read, and a constant keeps the memos below from rebuilding. */
const NONE: Row = {};

function Absent({ children }: { readonly children: ReactNode }) {
  return <span className="next-capacity-absent">{children}</span>;
}

function Bar({ row }: { readonly row: StripRow }) {
  if (row.elapsed === null) {
    return (
      <div
        className="next-capacity-noclock"
        role="img"
        aria-label={`${String(row.pct)}% of budget used; this window publishes no clock`}
      />
    );
  }
  const ink = fillInk(row);
  return (
    <div
      className="next-capacity-bar"
      role="img"
      aria-label={`${String(row.pct)}% of budget used, ${String(Math.round(row.elapsed * 100))}% of the window elapsed`}
    >
      <div
        className={`next-capacity-fill${ink === 'ok' ? '' : ` ${ink}`}`}
        style={{ width: `${String(row.pct)}%` }}
      />
      <div className="next-capacity-tick" style={{ left: `${(row.elapsed * 100).toFixed(2)}%` }} />
    </div>
  );
}

function Ends({ row, generated }: { readonly row: StripRow; readonly generated: number | null }) {
  const ends = endsOf(row, generated);
  if (ends.kind === 'spent') return <span className="next-capacity-spent">already spent</span>;
  if (ends.kind === 'not-projected') return <Absent>not projected</Absent>;
  return (
    <>
      {ends.clock}
      {ends.basis === null ? null : (
        <>
          {' '}
          <em>{`based on ${ends.basis} observed`}</em>
        </>
      )}
      {ends.spare === null ? null : (
        <>
          {' '}
          <span className="next-capacity-slack">{`· ~${String(ends.spare)}% spare at reset`}</span>
        </>
      )}
    </>
  );
}

function ModelLine({ row }: { readonly row: StripRow }) {
  if (!row.models.length) return null;
  return (
    <div className="next-capacity-models" data-next-capacity-models={rowKey(row)}>
      <small>WITHIN THIS WEEKLY BUDGET</small>
      {row.models.map((model, index) => (
        <span
          // A label is the vendor's text and two models can share one, so the position keeps them apart.
          key={`${model.label}\u0000${String(index)}`}
          className="next-capacity-model"
        >
          <b>{model.label}</b> {`${String(model.pct)}%`}
        </span>
      ))}
      <i>Per-model sub-limits · these publish no clock, so no pace and no projected end</i>
    </div>
  );
}

function WindowRow({
  row,
  generated,
  selected,
  label,
  onPick,
}: {
  readonly row: StripRow;
  readonly generated: number | null;
  readonly selected: boolean;
  readonly label: string;
  readonly onPick: (key: string) => void;
}) {
  const { controls } = useShell();
  const key = rowKey(row);
  const slotLabel = SLOT_LABELS[row.slot];
  const buttonRef = useFocusKey<HTMLButtonElement>(controls.focusLane, `capacity:${key}`);
  const usedInk = row.pct >= 80 ? ' high' : row.pct >= 50 ? ' mid' : '';
  return (
    // The whole row is a pointer target for its window, as the legacy row was; the button inside it is the
    // one a keyboard and a screen reader reach, and both name the same key.
    <Card
      variant="capacity-band"
      className="next-capacity-row"
      data-next-capacity-row={key}
      data-next-capacity-pick={key}
      onClick={() => onPick(key)}
    >
      <div className="next-capacity-window">
        <Button
          variant="window"
          ref={buttonRef}
          type="button"
          data-next-capacity-pick={key}
          data-next-focus={`capacity:${key}`}
          aria-pressed={selected}
          aria-label={`Read ${label} ${slotLabel} window`}
        >
          <b>{label}</b>
          <i>
            {slotLabel} ·{' '}
            {row.windowSec === null ? (
              <Absent>Window length not published</Absent>
            ) : (
              duration(row.windowSec)
            )}
          </i>
        </Button>
      </div>
      <div className={`next-capacity-pct${usedInk}`}>
        <small>USED</small>
        {`${String(row.pct)}%`}
      </div>
      <Bar row={row} />
      <div
        className={`next-capacity-pace${row.paceRatio !== null && row.paceRatio > 1 ? ' hot' : ''}`}
      >
        <small>PACE</small>
        {row.paceRatio === null ? (
          <Absent>Pace not measured</Absent>
        ) : (
          `${row.paceRatio.toFixed(1)}×`
        )}
      </div>
      <div className="next-capacity-ends">
        <small>BUDGET ENDS</small>
        <Ends row={row} generated={generated} />
      </div>
      <div className="next-capacity-resets">
        <small>RESETS</small>
        {row.remainingSec === null ? (
          <Absent>none published</Absent>
        ) : (
          duration(Math.max(0, row.remainingSec))
        )}
      </div>
    </Card>
  );
}

function SpreadSentence({ spread }: { readonly spread: Spread }) {
  const held = spread.unmeasured;
  return (
    <>
      Sessions in <b>{spread.project}</b> have worked {duration(spread.low)} to{' '}
      {duration(spread.high)}, median <b>{duration(spread.median)}</b>, from {spread.count}{' '}
      observed.
      {held
        ? ` ${String(held)} more ${held === 1 ? 'session has' : 'sessions have'} no closed working interval in the retained window and ${held === 1 ? 'is' : 'are'} not in that figure.`
        : ''}
    </>
  );
}

/* What the remaining budget buys, in the unit the decision is made in. Two measured paces rather than one
   fitted rate with a synthetic band: both ends are observations, and where they disagree that disagreement
   IS the uncertainty. Where only one is measured, one is stated and the other is named as absent. No
   concurrency beside it: "measured while N agents were working" counted every working session on the
   machine, read at render, and stood as the provenance of one vendor's historical window average, so the
   claim is withdrawn rather than narrowed. */
function Prospect({
  row,
  label,
  spread,
}: {
  readonly row: StripRow;
  readonly label: string;
  readonly spread: Spread | null;
}) {
  const parts: ReactNode[] = [];
  if (row.windowMinutesLeft !== null) {
    parts.push(
      <Fragment key="average">
        <b>{duration(row.windowMinutesLeft * 60)}</b> at this window's average pace
      </Fragment>,
    );
  }
  if (row.recentMinutesLeft !== null) {
    parts.push(
      <Fragment key="recent">
        <b>{duration(row.recentMinutesLeft * 60)}</b> at the recent pace
        {row.recentSpanSec === null ? '' : ` (last ${duration(row.recentSpanSec)})`}
      </Fragment>,
    );
  }
  if (!parts.length) return null;
  /* Three states, because two of them are evidence and only one is absence. Keying the caption on the
     derived minutes collapsed a measured zero into "no second reading yet", which the payload contradicts:
     the ring only publishes `recent` once two distinct readings support it. */
  let stale: string | null = null;
  if (row.recentMinutesLeft === null && row.asOf !== null) {
    stale = row.recentFlat
      ? `Recent pace measured at zero: nothing spent across ${duration(row.recentSpanSec)}${
          row.recentSamples === null ? '' : ` and ${String(row.recentSamples)} readings`
        }, so nothing is projected from it.`
      : 'Recent pace not measured: no second reading yet from this vendor.';
  }
  return (
    <Card variant="capacity-prospect" className="next-capacity-prospect">
      <p>
        <span className="next-capacity-scope">{`${label} · ${SLOT_LABELS[row.slot]}`}</span>
      </p>
      <p>
        The remaining {row.left}% buys{' '}
        {parts.map((part, index) => (
          <Fragment key={index}>
            {index > 0 ? ', or ' : ''}
            {part}
          </Fragment>
        ))}
        .
        {row.remainingSec === null ? null : (
          <>
            {' '}
            Resets in <b>{duration(Math.max(0, row.remainingSec))}</b>.
          </>
        )}
      </p>
      {spread ? (
        <p>
          <SpreadSentence spread={spread} />
        </p>
      ) : null}
      {stale === null ? null : <small>{stale}</small>}
    </Card>
  );
}

/* The disclosure that asks before any quota is fetched, the strip, and the switch that changes the answer.
   With no window published there is no panel and no placeholder: a machine whose harnesses publish none has
   nothing withheld from it, and an empty strip reads as a fault. The disclosure can still stand alone, as the
   reason there is no row yet. */
export function CapacityStrip() {
  const { runtime } = useShell();
  const body = useDisplayed((snapshot) => snapshot.data);
  const payload = (body ?? NONE) as Row;
  const rows = useMemo(() => stripRows(payload), [payload]);
  const labels = useMemo(() => harnessLabels(payload), [payload]);
  const key = useSelectedWindow();
  const picked = selectRows(rows, key);
  const lane = heldFor(runtime).selection;
  const selectedKey = picked ? rowKey(picked.selected) : '';
  const read = body !== null;
  /* The selection the board resolved, written back so a fallback holds: held by identity for the life of
     the tab, defaulting to an existing window only when its key is gone, and cleared when none remain. A
     board that has not arrived is not a board with no windows, so it clears nothing. A write after commit
     rather than during render, so StrictMode's second render writes nothing twice. */
  useEffect(() => {
    if (read) lane.set(selectedKey);
  }, [lane, read, selectedKey]);
  if (!picked) {
    return <UsageSwitch />;
  }
  const { selected, shown } = picked;
  const generated = nextNumber(payload['generated']);
  const rest = rows.length - shown.length;
  const untimed = untimedCount(rows, shown);
  const labelOf = (harness: string): string =>
    labels.get(harness) || harness || 'Source not identified';
  const seen = new Map<string, number>();
  return (
    <>
      <section className="next-capacity" data-next-capacity="" aria-label="Capacity">
        {/* Decorative: every cell below carries its own label, which is what keeps the narrow layout readable when this row is hidden. */}
        <div className="next-capacity-head" aria-hidden="true">
          <span>WINDOW</span>
          <span>USED</span>
          <span>BUDGET AGAINST CLOCK</span>
          <span>PACE</span>
          <span>BUDGET ENDS</span>
          <span>RESETS</span>
        </div>
        {shown.map((row) => {
          const id = rowKey(row);
          const occurrence = seen.get(id) ?? 0;
          seen.set(id, occurrence + 1);
          return (
            <Fragment key={`${id}\u0000${String(occurrence)}`}>
              <WindowRow
                row={row}
                generated={generated}
                selected={row === selected}
                label={labelOf(row.harness)}
                onPick={(next) => lane.set(next)}
              />
              <ModelLine row={row} />
            </Fragment>
          );
        })}
        {rest > 0 ? (
          <div className="next-capacity-row next-capacity-more">
            <i>
              {`${String(rest)} more ${rest === 1 ? 'window' : 'windows'}${
                untimed ? `, ${String(untimed)} of them not timed` : ''
              }`}
            </i>
          </div>
        ) : null}
        {/* Scoped to the harness whose budget the paragraph is about. Drawn across every harness it invited a division nobody measured. */}
        <Prospect
          row={selected}
          label={labelOf(selected.harness)}
          spread={projectSpread(payload, selected.harness)}
        />
      </section>
      <UsageSwitch />
    </>
  );
}

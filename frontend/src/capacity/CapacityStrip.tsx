import { Card } from '../ui/card';
import { Button } from '../ui/button';
import { Fragment, useEffect, useMemo, type CSSProperties, type ReactNode } from 'react';
import { nextNumber } from '../api/bootstrap';
import { Disclosure, disclosureKey, useFocusKey } from '../controls';
import { ALLOWANCE_LABEL, EXPLANATIONS } from '../language/glossary';
import type { Row } from '../observed';
import { useDisplayed, useShell } from '../shell/context';
import { heldFor, useConsent, useSelectedWindow, useUsageOffered } from './held';
import {
  allowanceSentence,
  clockWords,
  duration,
  endsOf,
  fillInk,
  harnessLabels,
  projectSpread,
  rowKey,
  selectRows,
  stripRows,
  untimedCount,
  windowLabel,
  type Ends,
  type Spread,
  type StripRow,
} from './model';
import { UsageSwitch } from './UsageConsent';
import './capacity.css';

/* The board publishes the reading. The tab holds the window selection and disclosure state. */
const NONE: Row = {};
const allowanceKey = disclosureKey({ project: null, scope: null, name: 'ai-allowance' });
const allowanceFocusKey = 'capacity:explanation';

const FILL = {
  ok: 'var(--accent)',
  warn: 'var(--amber)',
  crit: 'var(--clay)',
  unknown: 'var(--line)',
} as const;

function Bar({ row, label }: { readonly row: StripRow; readonly label: string }) {
  const used = `${String(row.pct)}% of budget used`;
  const clock =
    row.elapsed === null
      ? 'this window publishes no clock'
      : `${String(Math.round(row.elapsed * 100))}% of the window elapsed`;
  return (
    <div className="next-capacity-bar relative h-2.5 overflow-hidden rounded-pill border border-input bg-muted">
      <progress
        className="block h-full w-full appearance-none border-0 bg-transparent [--allowance-fill:var(--line)] [&::-webkit-progress-bar]:bg-transparent [&::-webkit-progress-value]:rounded-pill [&::-moz-progress-bar]:rounded-pill [&::-webkit-progress-value]:bg-[color:var(--allowance-fill)] [&::-moz-progress-bar]:bg-[color:var(--allowance-fill)]"
        style={{ '--allowance-fill': FILL[fillInk(row)] } as CSSProperties}
        aria-label={`${label} ${windowLabel(row)} allowance used`}
        aria-valuetext={`${used}, ${clock}`}
        value={row.pct}
        max={100}
      />
      {row.elapsed === null ? null : (
        <span
          className="next-capacity-tick pointer-events-none absolute inset-y-0 w-[2px] bg-foreground outline-1 outline-solid outline-[color:var(--panel)]"
          style={{ left: `clamp(0px, ${(row.elapsed * 100).toFixed(2)}%, calc(100% - 2px))` }}
          aria-hidden="true"
        />
      )}
    </div>
  );
}

function ModelLine({ row }: { readonly row: StripRow }) {
  if (!row.models.length) return null;
  return (
    <div
      className="flex flex-wrap gap-x-3 gap-y-1 text-label"
      data-next-capacity-models={rowKey(row)}
    >
      <strong>Within this weekly budget</strong>
      {row.models.map((model, index) => (
        <span key={`${model.label}:${String(index)}`} className="[overflow-wrap:anywhere]">
          <b>{model.label}</b> {String(model.pct)}%
        </span>
      ))}
      <p className="basis-full">
        Per-model sub-limits · these publish no clock, so no pace and no projected end
      </p>
    </div>
  );
}

function WindowChoice({
  row,
  selected,
  label,
  onPick,
}: {
  readonly row: StripRow;
  readonly selected: boolean;
  readonly label: string;
  readonly onPick: (key: string) => void;
}) {
  const { controls } = useShell();
  const key = rowKey(row);
  const window = windowLabel(row);
  const buttonRef = useFocusKey<HTMLButtonElement>(controls.focusLane, `capacity:${key}`, {
    fallback: allowanceFocusKey,
  });
  return (
    <Button
      ref={buttonRef}
      type="button"
      data-next-capacity-row={key}
      data-next-capacity-pick={key}
      data-next-focus={`capacity:${key}`}
      aria-pressed={selected}
      aria-label={`Read ${label} ${window}${window === 'plan window' ? '' : ' window'}`}
      className="aria-pressed:border-2 aria-pressed:border-foreground aria-pressed:bg-accent aria-pressed:text-accent-foreground"
      onClick={() => onPick(key)}
    >
      {label} · {window}
    </Button>
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
function Prospect({ row, spread }: { readonly row: StripRow; readonly spread: Spread | null }) {
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
    <div className="next-capacity-prospect grid gap-2">
      <p>
        The remaining {row.left}% buys{' '}
        {parts.map((part, index) => (
          <Fragment key={index}>
            {index > 0 ? ', or ' : ''}
            {part}
          </Fragment>
        ))}
        .
      </p>
      {spread ? (
        <p>
          <SpreadSentence spread={spread} />
        </p>
      ) : null}
      {stale === null ? null : <small>{stale}</small>}
    </div>
  );
}

function WindowDetails({
  row,
  label,
  ends,
  payload,
}: {
  readonly row: StripRow;
  readonly label: string;
  readonly ends: Ends;
  readonly payload: Row;
}) {
  const generated = nextNumber(payload['generated']);
  const reset = clockWords(row.resetAt, generated, true);
  const asOf = clockWords(row.asOf, generated);
  const facts = [
    ['Pace', row.paceRatio === null ? 'Pace not measured' : `${row.paceRatio.toFixed(1)}×`],
    [
      'Reset time',
      reset ? `${reset}${(row.remainingSec ?? 0) <= 0 ? ' (passed)' : ''}` : 'Not published',
    ],
    [
      'Window',
      `${windowLabel(row)} · ${row.windowSec === null || row.windowSec <= 0 ? 'length not published' : duration(row.windowSec)}`,
    ],
    ['Source', asOf ? `${label} · read at ${asOf}` : label],
    [
      'Projected budget end',
      ends.kind === 'projected'
        ? `${ends.clock}${ends.basis === null ? '' : ` · based on ${ends.basis} observed`}`
        : ends.kind === 'spent'
          ? 'Already spent'
          : 'Not projected',
    ],
  ] as const;
  return (
    <div className="grid gap-3 pb-2 text-body text-muted-foreground">
      <dl className="grid gap-2">
        {facts.map(([name, value]) => (
          <div className="flex flex-wrap gap-x-2" key={name}>
            <dt className="font-semibold">{name}</dt>
            <dd className="m-0">{value}</dd>
          </div>
        ))}
      </dl>
      <ModelLine row={row} />
      <Prospect row={row} spread={projectSpread(payload, row.harness)} />
    </div>
  );
}

export function CapacityStrip() {
  const { runtime } = useShell();
  const body = useDisplayed((snapshot) => snapshot.data);
  const payload = (body ?? NONE) as Row;
  const published = useMemo(() => stripRows(payload), [payload]);
  const labels = useMemo(() => harnessLabels(payload), [payload]);
  const key = useSelectedWindow();
  const offered = useUsageOffered();
  const off = useConsent('usage') === 'declined';
  // The browser switch gates credential fetches. Codex reads disk and Antigravity receives quota locally.
  const rows = off
    ? published.filter(({ harness }) => harness === 'codex' || harness === 'antigravity')
    : published;
  const picked = selectRows(rows, key);
  const cached =
    off && !picked
      ? published.find(({ harness }) => harness === 'claude' || harness === 'cursor')
      : undefined;
  const lane = heldFor(runtime).selection;
  const selectedKey = picked ? rowKey(picked.selected) : '';
  /* A refresh keeps the vendor and window key while it is still published. Before the first
     board arrives there is no evidence on which to replace or clear the held choice. */
  useEffect(() => {
    if (body !== null) lane.set(selectedKey);
  }, [lane, body, selectedKey]);
  if (!picked && !cached && !offered) return null;

  const labelOf = (harness: string): string =>
    labels.get(harness) || harness || 'Source not identified';
  const selected = picked?.selected;
  const label = selected ? labelOf(selected.harness) : '';
  const ends = selected ? endsOf(selected, nextNumber(payload['generated'])) : null;
  const spare =
    ends?.kind === 'projected' && ends.spare !== null
      ? `About ${String(ends.spare)}% left at reset${ends.basis === null ? '' : ` · based on ${ends.basis} observed`}`
      : null;
  const seen = new Map<string, number>();
  return (
    <Card
      as="section"
      className="mb-6 grid min-w-0 gap-3 [overflow-wrap:anywhere]"
      data-next-capacity=""
      aria-labelledby="next-ai-allowance-heading"
    >
      <div className="grid gap-3 min-[761px]:grid-cols-2 min-[761px]:items-center">
        <div className="min-w-0 [overflow-wrap:anywhere]">
          <h2 id="next-ai-allowance-heading" className="m-0 text-value font-semibold">
            {ALLOWANCE_LABEL}
          </h2>
          {selected || cached ? (
            <p className="m-0 mt-1 text-body text-muted-foreground">
              {selected
                ? allowanceSentence(selected, label)
                : cached && `Last cached window: ${labelOf(cached.harness)} ${windowLabel(cached)}`}
            </p>
          ) : null}
        </div>
        {selected ? (
          <div className="min-w-0">
            <div className="mb-2 flex flex-wrap items-baseline justify-between gap-x-2">
              <strong className="text-body tabular-nums">{String(selected.pct)}% used</strong>
              {spare === null ? null : (
                <span className="text-label text-muted-foreground">{spare}</span>
              )}
            </div>
            <Bar row={selected} label={label} />
          </div>
        ) : null}
      </div>
      {picked && picked.shown.length > 1 ? (
        <div
          role="group"
          aria-label="Allowance windows"
          className="flex flex-wrap items-center gap-2"
        >
          {picked.shown.map((row) => {
            const id = rowKey(row);
            const occurrence = seen.get(id) ?? 0;
            seen.set(id, occurrence + 1);
            return (
              <WindowChoice
                key={`${id}\u0000${String(occurrence)}`}
                row={row}
                selected={row === selected}
                label={labelOf(row.harness)}
                onPick={lane.set}
              />
            );
          })}
          {rows.length > picked.shown.length ? (
            <span className="next-capacity-more text-label text-muted-foreground">
              {moreWindows(rows, picked.shown)}
            </span>
          ) : null}
        </div>
      ) : null}
      {selected && ends ? (
        <Disclosure
          explanation
          disclosureKey={allowanceKey}
          summary={EXPLANATIONS.aiAllowance}
          focusKey={allowanceFocusKey}
        >
          <WindowDetails row={selected} label={label} ends={ends} payload={payload} />
        </Disclosure>
      ) : null}
      <UsageSwitch
        offNote={
          selected
            ? 'Quota reading is off for Claude Code and Cursor. Local readings are still shown.'
            : cached
              ? 'Quota reading is off. The last cached read will lapse.'
              : 'Quota reading is off. No window has been read.'
        }
      />
    </Card>
  );
}

function moreWindows(rows: readonly StripRow[], shown: readonly StripRow[]): string {
  const rest = rows.length - shown.length;
  const untimed = untimedCount(rows, shown);
  return `${String(rest)} more ${rest === 1 ? 'window' : 'windows'}${untimed ? `, ${String(untimed)} of them not timed` : ''}`;
}

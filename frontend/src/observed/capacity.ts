import { nextNumber } from '../api/bootstrap';
import { formatDuration } from '../shell/format';
import { pair, records, trimmed, type Pair, type Row } from './values';

export type CapacityWindow = {
  readonly key: string;
  readonly vendor: string;
  readonly slot: string;
  readonly used: number;
  readonly tone: 'ok' | 'want' | 'bad' | 'unknown';
} & Pair<'window'> &
  Pair<'pace'> &
  Pair<'ends'> &
  Pair<'resets'> &
  Pair<'clock'> &
  Pair<'recent'> &
  Pair<'basis'>;

export type CapacitySublimit = {
  readonly within: string;
  readonly label: unknown;
  readonly used: number;
} & Pair<'note'>;

export interface BoardRisk {
  readonly scope: 'board' | 'session';
  readonly kind: string;
  readonly title: string;
  readonly identity: string;
  readonly src: string;
  readonly nowText: string;
  readonly nowKnown: boolean;
  readonly nextText: string;
  readonly nextKnown: boolean;
  readonly tone: string;
  readonly sid?: string;
  readonly harness?: string;
  readonly project?: string;
  readonly delegatedSession?: Row;
  readonly waitAge?: number | null;
}

const SLOTS: readonly (readonly [string, string])[] = [
  ['fiveH', '5-hour'],
  ['week', 'weekly'],
  ['month', 'billing cycle'],
];

/* The vendor quota windows the payload published, with their pace against each window's own clock.
   Ported with the rest of the observed model so the page has one reader of `usage`, though what draws
   from it (the capacity strip, the consent gate) arrives with a later step. A window carries no figure
   it was not given: a missing clock is "Window clock not published", never a zero. */
export function observeCapacity(payload: Row): {
  readonly windows: CapacityWindow[];
  readonly sublimits: CapacitySublimit[];
  readonly risks: BoardRisk[];
} {
  const windows: CapacityWindow[] = [];
  const sublimits: CapacitySublimit[] = [];
  const risks: BoardRisk[] = [];
  const generated = nextNumber(payload['generated']);
  for (const entry of records(payload['usage'])) {
    if (entry['state'] !== 'ok') continue;
    const vendor = trimmed(entry['harness']) || 'Source not identified';
    for (const [slot, label] of SLOTS) {
      const raw = entry[slot as string];
      if (!raw || typeof raw !== 'object' || !Number.isInteger((raw as Row)['pct'])) continue;
      const window = raw as Row;
      const pct = window['pct'] as number;
      const length = nextNumber(window['windowSec']);
      const reset = nextNumber(window['resetAt']);
      const remaining = generated !== null && reset !== null ? reset - generated : null;
      const elapsed =
        length !== null && length > 0 && remaining !== null && remaining > 0
          ? Math.max(0, Math.min(1, (length - remaining) / length))
          : null;
      const pace = elapsed !== null && elapsed > 0 ? pct / (100 * elapsed) : null;
      const minutes =
        pace !== null && pace > 0 && elapsed !== null && length !== null
          ? ((Math.max(0, 100 - pct) / pct) * elapsed * length) / 60
          : null;
      const tone: CapacityWindow['tone'] =
        pace === null ? 'unknown' : pace >= 1.5 ? 'bad' : pace >= 1 ? 'want' : 'ok';
      const recent: Row =
        window['recent'] && typeof window['recent'] === 'object' ? (window['recent'] as Row) : {};
      const recentRate = nextNumber(recent['pctPerMin']);
      const recentSpan = nextNumber(recent['spanSec']);
      const samples = recent['samples'];
      const recentKnown =
        recentRate !== null &&
        recentRate >= 0 &&
        recentSpan !== null &&
        recentSpan > 0 &&
        Number.isInteger(samples) &&
        (samples as number) >= 2 &&
        remaining !== null &&
        remaining > 0;
      const recentBasis = recentKnown
        ? `across ${String(formatDuration(recentSpan))} and ${String(samples)} readings`
        : '';
      const recentText = !recentKnown
        ? ''
        : recentRate === 0
          ? `Measured at zero: nothing spent ${recentBasis}, so nothing is projected from it.`
          : `${String(recentRate)} percentage points per minute ${recentBasis}; ` +
            `${String(formatDuration((Math.max(0, 100 - pct) / (recentRate as number)) * 60))} of budget remaining at that pace.`;
      const row = {
        key: `${vendor}:${slot}`,
        vendor,
        slot,
        used: pct,
        ...pair('window', label, 'Window label not published'),
        ...pair('pace', pace === null ? '' : `${pace.toFixed(1)}×`, 'Window pace not reported'),
        ...pair(
          'ends',
          pct >= 100
            ? 'Already spent'
            : minutes === null
              ? ''
              : `In ${String(formatDuration(minutes * 60))} at this window's average pace`,
          'Budget end not projected',
        ),
        ...pair(
          'resets',
          remaining !== null && remaining > 0 ? formatDuration(remaining) : '',
          remaining !== null && remaining <= 0
            ? 'Published reset has passed'
            : 'Reset time not published',
        ),
        ...pair(
          'clock',
          elapsed === null ? '' : `${String(Math.round(elapsed * 100))}% of window elapsed`,
          'Window clock not published',
        ),
        ...pair('recent', recentText, 'Recent quota pace not measured for a current window'),
        ...pair(
          'basis',
          elapsed !== null && elapsed < 0.1
            ? 'Less than a tenth of this window has elapsed; the projection rests on a short observation.'
            : '',
          'No short-window qualification published',
        ),
        tone,
      } as CapacityWindow;
      windows.push(row);
      const pressure =
        pct >= 70 ||
        ((elapsed ?? 0) >= 0.1 &&
          pct >= 10 &&
          minutes !== null &&
          remaining !== null &&
          remaining > 0 &&
          minutes * 60 < remaining);
      if (pressure) {
        risks.push({
          scope: 'board',
          kind: 'quota',
          title: 'Quota pressure',
          identity: `${vendor} · ${label} window`,
          src: `${vendor} vendor quota`,
          nowText: `${String(pct)}% reported · ${row.paceText}`,
          nowKnown: true,
          nextText: row.resetsText,
          nextKnown: row.resetsKnown,
          tone,
        });
      }
    }
    for (const model of records(entry['models']).slice(0, 8)) {
      if (!trimmed(model['label']) || !Number.isInteger(model['pct'])) continue;
      sublimits.push({
        within: `${vendor} · weekly`,
        label: model['label'],
        used: model['pct'] as number,
        ...pair(
          'note',
          '',
          'Per-model sub-limits publish no clock, so no pace and no projected end.',
        ),
      });
    }
  }
  return { windows, sublimits, risks };
}

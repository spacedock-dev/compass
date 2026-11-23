import type { SettingLimit, SettingsBody } from '../api/types';
import { capacityPreview } from '../api/promptCapacity';

/* Bounds and defaults come from the server in its native integer units. Formatting never
   rounds a stored value into a different stop. */
const COPY: Readonly<Record<string, { label: string; help: string; scale: number; unit: string }>> =
  {
    analyze_prompt_bytes: {
      label: 'Prompt size',
      help: 'The most one progress check may send to the AI, including selected messages and evidence. This does not change the session outline or summary.',
      scale: 1 / 1024,
      unit: 'KB',
    },
    analyze_record_events: {
      label: 'Messages and checks kept',
      help: 'How many messages and checks are kept after reading back to where your goal starts.',
      scale: 1,
      unit: '',
    },
    analyze_listed_checks: {
      label: 'Checks and files listed',
      help: 'How many checks and written files are listed for the AI. The session page itself still lists 12.',
      scale: 1,
      unit: '',
    },
    analyze_scan_megabytes: {
      label: 'Transcript scanned for checks',
      help: 'How much of the session and its helpers Compass scans for checks and files. A larger scan takes longer and uses more memory.',
      scale: 1024,
      unit: 'KB',
    },
  };

export interface Field {
  readonly key: string;
  readonly label: string;
  readonly help?: string;
  readonly unit: string;
  readonly scale: number;
  readonly value: number;
  readonly fallback: number;
  readonly minimum: number;
  readonly maximum: number;
}

const count = new Intl.NumberFormat('en-US', { maximumFractionDigits: 3 });
export const kilobytes = (bytes: number): string => `${count.format(bytes / 1024)} KB`;
export function withUnit(field: Field, value: number): string {
  const formatted = count.format(value * field.scale);
  return field.unit ? `${formatted} ${field.unit}` : formatted;
}

export function fieldsOf(body: SettingsBody): readonly Field[] {
  return body.limits.map(({ key, default: fallback, minimum, maximum }) => ({
    key,
    label: COPY[key]?.label ?? key,
    ...(COPY[key] ? { help: COPY[key].help } : {}),
    unit: COPY[key]?.unit ?? '',
    scale: COPY[key]?.scale ?? 1,
    value: body.values[key] ?? fallback,
    fallback,
    minimum,
    maximum,
  }));
}

/* Doubling and halving around the recommendation gives room to adjust small values on
   ranges that span orders of magnitude. The exact saved value also gets its own stop. */
export function stopsFor({ minimum, maximum, fallback, value }: Field): readonly number[] {
  const stops = new Set([minimum, maximum, fallback, value]);
  for (let stop = fallback; stop > minimum; stop = Math.floor(stop / 2)) stops.add(stop);
  for (let stop = Math.max(1, fallback); stop < maximum; stop *= 2) stops.add(stop);
  return [...stops].sort((left, right) => left - right);
}

function isLimit(value: unknown): value is SettingLimit {
  if (typeof value !== 'object' || value === null) return false;
  const limit = value as Record<string, unknown>;
  return (
    typeof limit['key'] === 'string' &&
    ['default', 'minimum', 'maximum'].every((name) => Number.isSafeInteger(limit[name])) &&
    Number(limit['minimum']) >= 0 &&
    Number(limit['minimum']) <= Number(limit['default']) &&
    Number(limit['default']) <= Number(limit['maximum'])
  );
}

/** An answer the screen can draw from, or null: a body missing either half is not one. */
export function settingsBody(body: unknown): SettingsBody | null {
  if (typeof body !== 'object' || body === null) return null;
  const { values, limits, capacities, update_check } = body as Record<string, unknown>;
  if (typeof values !== 'object' || values === null || Array.isArray(values)) return null;
  if (!Array.isArray(limits) || !limits.every(isLimit)) return null;
  const numbers = values as Record<string, unknown>;
  if (
    !limits.every(({ key, minimum, maximum }) => {
      const value = numbers[key];
      return (
        typeof value === 'number' &&
        Number.isSafeInteger(value) &&
        value >= minimum &&
        value <= maximum
      );
    })
  )
    return null;
  const routes =
    typeof capacities === 'object' && capacities !== null && !Array.isArray(capacities)
      ? (capacities as Record<string, unknown>)
      : {};
  return {
    ...(typeof update_check === 'object' &&
    update_check !== null &&
    typeof (update_check as Record<string, unknown>)['disabled'] === 'boolean' &&
    typeof (update_check as Record<string, unknown>)['default_enabled'] === 'boolean' &&
    typeof (update_check as Record<string, unknown>)['cli_disabled'] === 'boolean'
      ? { update_check: update_check as NonNullable<SettingsBody['update_check']> }
      : {}),
    values: numbers as Record<string, number>,
    limits,
    capacities: {
      claude: capacityPreview(routes['claude']),
      codex: capacityPreview(routes['codex']),
    },
  };
}

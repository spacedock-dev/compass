import { nextNumber } from '../api/bootstrap';

/* The compact duration spelling (`nextFormatDuration`): the two largest units, floored. Null for
   anything that is not a finite non-negative number, so a caller writes an absence rather than a
   figure it cannot support. */
export function formatDuration(seconds: unknown): string | null {
  if (typeof seconds !== 'number' || !Number.isFinite(seconds) || seconds < 0) return null;
  const whole = Math.floor(seconds);
  if (whole < 60) return `${whole}s`;
  if (whole < 3600) return `${Math.floor(whole / 60)}m`;
  if (whole < 86400) return `${Math.floor(whole / 3600)}h ${Math.floor((whole % 3600) / 60)}m`;
  return `${Math.floor(whole / 86400)}d ${Math.floor((whole % 86400) / 3600)}h`;
}
const durationUnits: Readonly<Record<string, string>> = {
  s: 'second',
  m: 'minute',
  h: 'hour',
  d: 'day',
};

/* Also reads the compact duration fields still published by collectors. Pass Compass-generated
   durations or sentences here. User-supplied text keeps its original spelling. */
export function expandDurationUnits(text: string): string {
  return text.replace(/\b(\d+)([smhd])(?: (\d+)([mh]))?\b/g, (_, first, unit, rest, restUnit) => {
    const words = (count: string, key: string) =>
      `${count} ${durationUnits[key]}${count === '1' ? '' : 's'}`;
    return words(first, unit) + (rest && rest !== '0' ? ` ${words(rest, restUnit)}` : '');
  });
}

export function formatDurationWords(seconds: unknown): string | null {
  const compact = formatDuration(seconds);
  return compact === null ? null : expandDurationUnits(compact);
}

function publishedSeconds(stamp: unknown): number | null {
  const seconds = nextNumber(stamp);
  return seconds !== null && seconds > 0 && seconds <= 8_640_000_000_000 ? seconds : null;
}

export function observationAge(generated: unknown, stamp: unknown): number | null {
  const at = publishedSeconds(stamp);
  const clock = publishedSeconds(generated);
  return at !== null && clock !== null && at <= clock ? clock - at : null;
}

/* Use the local calendar's dates to count days, including across a daylight-saving change. */
function calendarDay(date: Date, calendar: Intl.DateTimeFormat) {
  const parts = calendar.formatToParts(date);
  const part = (type: Intl.DateTimeFormatPartTypes) =>
    Number(parts.find((entry) => entry.type === type)?.value);
  const year = part('year');
  return { year, day: Date.UTC(year, part('month') - 1, part('day')) / 86_400_000 };
}

interface TimeFormat {
  readonly locale?: string;
  readonly timeZone?: string;
  readonly style?: 'same-day-relative' | 'clock';
}

/* First-layer time includes any preposition the timestamp needs in a sentence. "Today" and
   "yesterday" are relative to the displayed payload, even when the board has gone stale. */
export function formatTimestamp(
  stamp: unknown,
  generated: unknown,
  { locale, timeZone, style }: TimeFormat = {},
): string | null {
  const at = publishedSeconds(stamp);
  const boardTime = publishedSeconds(generated);
  const clock = style === 'clock';
  if (at === null || (!clock && boardTime === null)) return null;
  const age = boardTime === null ? null : boardTime - at;
  if (age !== null && age < 0 && !clock) return null;
  if (!clock && age !== null && age < 3600) return `${formatDurationWords(age)} ago`;

  const calendar = new Intl.DateTimeFormat('en-US', {
    timeZone,
    year: 'numeric',
    month: 'numeric',
    day: 'numeric',
  });
  const date = new Date(at * 1000);
  const today = boardTime === null ? null : calendarDay(new Date(boardTime * 1000), calendar);
  const observed = calendarDay(date, calendar);
  const daysAgo = today ? today.day - observed.day : null;
  const localTime = () => date.toLocaleTimeString(locale, { timeZone, timeStyle: 'short' });
  if (daysAgo === 0) {
    return style === 'same-day-relative' && age !== null && age < 86400
      ? `${formatDurationWords(age)} ago`
      : `at ${localTime()}`;
  }
  if (daysAgo === 1 && !clock) return 'yesterday';
  const shortDate = date.toLocaleDateString(locale, {
    timeZone,
    month: 'short',
    day: 'numeric',
    year: observed.year === today?.year ? undefined : 'numeric',
  });
  return clock ? `on ${shortDate} at ${localTime()}` : `on ${shortDate}`;
}

/* Compass's existing 1,024-byte scale, with reader-facing units. Exact counts belong in
   technical details. */
export function formatSize(value: unknown, locale?: string): string | null {
  const bytes = nextNumber(value);
  if (bytes === null || bytes < 0) return null;
  const kb = 1024;
  const mb = kb * kb;
  if (bytes > 0 && bytes < kb) return '<1 KB';
  const large = bytes >= mb;
  const amount = Math.abs(bytes) / (large ? mb : kb);
  return `${amount.toLocaleString(locale, { maximumFractionDigits: large ? 1 : 0 })} ${large ? 'MB' : 'KB'}`;
}

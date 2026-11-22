import { describe, expect, it, vi } from 'vitest';
import * as format from './format';

const { formatDuration } = format;

describe('a duration reads in its two largest units', () => {
  it.each([
    [0, '0s'],
    [59.9, '59s'],
    [60, '1m'],
    [3599, '59m'],
    [3600, '1h 0m'],
    [3661, '1h 1m'],
    [86399, '23h 59m'],
    [86400, '1d 0h'],
    [90061, '1d 1h'],
  ])('%s seconds is %s', (seconds, expected) => {
    expect(formatDuration(seconds)).toBe(expected);
  });

  it('is null for what is not a duration, so a caller states an absence rather than a figure', () => {
    for (const value of [-1, Number.NaN, Number.POSITIVE_INFINITY, '5', null, undefined]) {
      expect(formatDuration(value)).toBeNull();
    }
  });
});

const generated = Date.UTC(2026, 10, 23, 4) / 1000;
const local = { locale: 'en-US', timeZone: 'America/Los_Angeles' };

describe('a reader sees time relative to the board or in their own time zone', () => {
  it.each([
    [generated - 360, '6 minutes ago'],
    [Date.UTC(2026, 10, 23, 2, 43) / 1000, 'at 6:43 PM'],
    [Date.UTC(2026, 10, 22, 2) / 1000, 'yesterday'],
    [Date.UTC(2026, 10, 20, 20) / 1000, 'on Nov 20'],
    [Date.UTC(2025, 10, 20, 20) / 1000, 'on Nov 20, 2025'],
  ])('reads %s as %s', (stamp, words) => {
    expect(format.formatTimestamp(stamp, generated, local)).toBe(words);
  });

  it('reads today in the reader’s locale and zone, including a scheduled time', () => {
    expect(
      format.formatTimestamp(generated + 3600, generated, { locale: 'de-DE', timeZone: 'UTC' }),
    ).toBe('at 05:00');
  });

  it('leaves missing and invalid clocks or observations blank', () => {
    for (const value of [null, NaN, Infinity, -Infinity, Number.MAX_VALUE]) {
      expect(format.formatTimestamp(value, generated, local)).toBeNull();
      expect(format.formatTimestamp(generated, value, local)).toBeNull();
    }
  });

  it('gives the same words when the system clock moves 400 days', () => {
    vi.useFakeTimers();
    try {
      vi.setSystemTime(generated * 1000);
      const before = format.formatTimestamp(generated - 360, generated, local);
      vi.setSystemTime((generated + 400 * 86400) * 1000);
      expect(format.formatTimestamp(generated - 360, generated, local)).toBe(before);
      expect(before).toBe('6 minutes ago');
    } finally {
      vi.useRealTimers();
    }
  });

  it('spells out waits and same-day ends in the Needs you examples', () => {
    expect(format.formatDurationWords(360)).toBe('6 minutes');
    expect(format.formatDurationWords(61)).toBe('1 minute');
    expect(format.formatDurationWords(null)).toBeNull();
    const relative = { ...local, style: 'same-day-relative' } as const;
    expect(format.formatTimestamp(generated - 1500, generated, relative)).toBe('25 minutes ago');
    expect(format.formatTimestamp(generated - 7200, generated, relative)).toBe('2 hours ago');
    expect(format.formatTimestamp(generated - 10800, generated, relative)).toBe('3 hours ago');
  });
});

describe('a reader sees a size in KB or MB', () => {
  it.each([
    [0, '0 KB'],
    [1, '<1 KB'],
    [16384, '16 KB'],
    [1_048_575, '1,024 KB'],
    [1_048_576, '1 MB'],
    [1_572_864, '1.5 MB'],
    [null, null],
    [NaN, null],
    [-1, null],
  ])('reads %s as %s', (bytes, words) => {
    expect(format.formatSize(bytes, 'en-US')).toBe(words);
  });
});

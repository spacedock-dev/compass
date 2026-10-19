import { screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { check, fact, json, mountDrift, press, openActivity } from './testing';

/* The server numbers a message by its rank in the session and a check or file by the message it follows
   and its place after it, so a number is the entry's, not the page's: it does not move when a check
   displaces another, when a check runs again, or when Show more loads an older page. */
const path = '/api/session-record';
const session = { annotation_window_start: 1, annotation_goal_saved_at: 1 };
const message = (n: number) => fact(`m${String(n)}`, n, { ordinal: n });
const page = (from: number, count: number) =>
  Array.from({ length: count }, (_, i) => message(from - i));
const body = (extra: Record<string, unknown> = {}) => ({
  session: { harness: 'claude', sid: 's1' },
  entries: page(100, 50),
  next: 'older',
  reached_start: false,
  bound: null,
  scanned_bytes: 65536,
  kinds: ['user_message', 'agent_message'],
  state: 'ok',
  ...extra,
});
const rows = () => [...document.querySelectorAll<HTMLElement>('[data-next-entry-id]')];
const numberOf = (id: string) =>
  document.querySelector<HTMLElement>(`[data-next-entry-id="${id}"]`)?.dataset['nextEntry'];
const more = () => screen.getByRole('button', { name: 'Show 50 older entries' });
const failed = (id: string, at: number, ordinal: number, sub: number) =>
  check(id, at, 'failed', { ordinal, ordinal_sub: sub });

describe('a reader whose entries carry the server numbers', () => {
  it('sees each entry keep its number when Show more loads an older page', async () => {
    const mounted = mountDrift({
      session,
      facts: [message(100), failed('c1', 100.5, 100, 1)],
      routes: {
        [path]: (r) =>
          json(
            r.url.includes('before=')
              ? body({ entries: page(50, 50), next: 'oldest', reached_start: true })
              : body(),
          ),
      },
    });
    await mounted.settle();
    await openActivity();
    const before = Object.fromEntries(
      rows().map((row) => [row.dataset['nextEntryId'], row.dataset['nextEntry']]),
    );
    expect(before['m100']).toBe('100');
    expect(before['m51']).toBe('51');
    expect(before['c1']).toBe('100.1');
    expect(screen.queryByText('Numbers count from the oldest entry loaded.')).toBeNull();
    await press(more());
    expect(rows()).toHaveLength(101);
    for (const [id, label] of Object.entries(before)) expect(numberOf(id)).toBe(label);
    expect(numberOf('m50')).toBe('50');
    expect(numberOf('m1')).toBe('1');
    expect(screen.queryByText('Numbers count from the oldest entry loaded.')).toBeNull();
  });

  it('draws a message the server published no number for, without a wrong one', async () => {
    const mounted = mountDrift({
      session,
      facts: [message(5), fact('gate', 6, { type: 'gate_decision' })],
    });
    await mounted.settle();
    await openActivity();
    expect(numberOf('m5')).toBe('5');
    expect(rows().some((row) => row.dataset['nextEntryId'] === 'gate')).toBe(true);
    expect(numberOf('gate')).toBeUndefined();
  });
});

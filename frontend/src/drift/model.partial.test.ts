import { describe, expect, it } from 'vitest';
import { createHeld } from '../intent/held';
import { createAnnouncer } from '../shell/announcer';
import { EMPTY_RECORD, type RecordEntry } from '../store/board';
import { createFakeClock } from '../transport/testing';
import { buildModel } from './model';

const fact = (at: number, id: string) =>
  ({
    fact_id: id,
    at,
    type: 'user_message',
    ordinal: null,
    source_session: { harness: 'claude', sid: 's1' },
  }) as unknown as RecordEntry['entries'][number];

function modelFor(record: RecordEntry) {
  return buildModel({
    record,
    session: { harness: 'claude', sid: 's1', annotation_window_start: 100 } as never,
    payload: { annotate: true, generated_at: 1000 } as never,
    base: {} as never,
    project: 'p',
    projectKey: 'p',
    contexts: new Map(),
    held: createHeld({ clock: createFakeClock(), announcer: createAnnouncer() }),
    liveOn: false,
  });
}

describe('the entry count is a floor while older pages are unread', () => {
  it('stays a floor when the record already reaches back past the intent window', () => {
    const record: RecordEntry = {
      ...EMPTY_RECORD,
      status: 'loaded',
      pages: 1,
      next: 'older',
      reachedStart: false,
      entries: [fact(500, 'a'), fact(300, 'b'), fact(50, 'c')],
    };
    const model = modelFor(record);
    expect(model.windowCount).toBe(2);
    expect(model.entriesPartial).toBe(true);
  });

  it('is exact once the record has reached its start', () => {
    const record: RecordEntry = {
      ...EMPTY_RECORD,
      status: 'loaded',
      pages: 1,
      next: null,
      reachedStart: true,
      entries: [fact(500, 'a'), fact(50, 'c')],
    };
    expect(modelFor(record).entriesPartial).toBe(false);
  });
});

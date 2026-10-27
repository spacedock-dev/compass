import { describe, expect, it } from 'vitest';
import { readingCoverage } from './shape';

const OLD = {
  tail_truncated: false,
  tail_start: 100,
  unlisted: 0,
  unread_checks: 0,
  goal_source: 'typed',
};

describe('a stored reading is held to one of two coverage shapes', () => {
  it('keeps a reading stored before the command counts, with no counts added', () => {
    expect(readingCoverage(OLD)).toEqual(OLD);
  });

  it('keeps a reading that carries both counts', () => {
    const counted = { ...OLD, other_commands: 7, read_only_commands: 4 };
    expect(readingCoverage(counted)).toEqual(counted);
  });

  it('refuses a lone, malformed or impossible count rather than reading it as zero', () => {
    for (const patch of [
      { other_commands: 7 },
      { read_only_commands: 4 },
      { other_commands: '7', read_only_commands: 4 },
      { other_commands: -1, read_only_commands: 0 },
      { other_commands: 1.5, read_only_commands: 0 },
      { other_commands: null, read_only_commands: null },
      { other_commands: 3, read_only_commands: 4 },
    ]) {
      expect(readingCoverage({ ...OLD, ...patch }), JSON.stringify(patch)).toBeNull();
    }
  });
});

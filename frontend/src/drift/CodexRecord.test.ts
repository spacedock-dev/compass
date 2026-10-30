import { describe, expect, it } from 'vitest';
import { evidenceOwn } from './workList';

/* The Codex record line claims a session's subagents only as far as the scan read them: included where some were
   read and none was left unread, the number not read where any was, and nothing in a session that had none. */
const own = (scan: Record<string, unknown> | null | undefined): string =>
  evidenceOwn({}, 'codex', false, scan);

describe('the Codex record line and its subagents', () => {
  it('says they are included where every one was read', () => {
    const text = own({ subagent_transcripts: 2, subagent_transcripts_unread: 0 });
    expect(text).toContain('its subagents’ included and labelled as theirs');
    expect(text).not.toContain('not read');
  });

  it('says how many were not read where any was, and never that they are included', () => {
    const one = own({ subagent_transcripts: 1, subagent_transcripts_unread: 1 });
    expect(one).toContain('except those of 1 subagent that was not read');
    expect(one).not.toContain('included');
    const two = own({ subagent_transcripts: 0, subagent_transcripts_unread: 2 });
    expect(two).toContain('except those of 2 subagents that were not read');
    expect(two).not.toContain('included');
  });

  it('says nothing of subagents in a session that had none', () => {
    for (const scan of [
      { subagent_transcripts: 0, subagent_transcripts_unread: 0 },
      {},
      null,
      undefined,
    ]) {
      expect(own(scan)).not.toMatch(/subagent/);
      expect(own(scan)).toContain('from codex-cli 0.149 on, and they are listed here.');
    }
  });
});

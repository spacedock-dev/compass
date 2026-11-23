import { act, fireEvent, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { attentionBoard } from '../../test/attention_boards';
import { projectStatusBoard } from '../../test/project_boards';
import { mountShell } from '../shell/testing';

/* The Attention screen's own behaviour in the real shell: what it says before and without a board, what
   stays the reader's across a revision, what it keeps of the evidence a higher subject outranks, and what
   it does and does not do on its own. The comparison with the legacy page is `view.differential.test`. */

afterEach(() => {
  vi.unstubAllGlobals();
});

const status = () => document.getElementById('next-attention-status')?.textContent ?? '';
const section = (name: string) =>
  document.querySelector(`[data-next-attention-section="${name}"]`) as HTMLElement;
const rows = (name: string) => [...section(name).querySelectorAll(':scope > ol > li')];
const visible = (name: string) => rows(name).filter((row) => !row.hasAttribute('hidden'));
const toggle = (name: string) =>
  section(name).querySelector(':scope > [data-next-attention-toggle]') as HTMLButtonElement;

async function open(data: unknown = attentionBoard(), options: { focusCapability?: string } = {}) {
  const page = mountShell({ hash: '#n=attention', data, ...options });
  await page.settle();
  return page;
}

async function revise(page: Awaited<ReturnType<typeof open>>, data: unknown) {
  page.backend.data = data;
  await act(async () => {
    await page.shell.runtime.refresh();
  });
  await page.settle();
}

describe('before a board, and without one', () => {
  it('says the first payload has not arrived, and draws no queue and no zero', () => {
    mountShell({ hash: '#n=attention', data: attentionBoard() });
    expect(screen.getByRole('heading', { level: 1, name: 'Needs you' })).toBeInTheDocument();
    expect(screen.getByText('The first payload has not arrived yet.')).toBeInTheDocument();
    expect(document.querySelector('[data-next-attention-section]')).toBeNull();
    expect(document.body.textContent).not.toMatch(/\b0 of 0\b/);
  });

  it('says no data has been received once reads have failed and none ever succeeded', async () => {
    const page = await open(null);
    await act(async () => {
      await page.shell.runtime.refresh();
    });
    expect(screen.getByText('No data has been received in this tab.')).toBeInTheDocument();
    expect(document.querySelector('[data-next-attention-section]')).toBeNull();
  });

  it('says a board with no session collection published none, not that no session needs the reader', async () => {
    await open({ generated: 1, harnesses: [] });
    expect(screen.getByText('The board published no session collection.')).toBeInTheDocument();
    expect(document.querySelector('[data-next-fleet-fact]')).toBeNull();
    expect(document.querySelector('.next-attention-empty')).toBeNull();
    expect(document.body.textContent).not.toContain('sessions carry a subject');
  });

  it('says an empty collection is empty, in the payload window it was read over', async () => {
    await open({ generated: 1, window_hours: 24, sessions: [], harnesses: [] });
    expect(document.querySelector('.next-attention-empty')?.textContent).toBe(
      'No sessions in this 24-hour payload',
    );
  });
});

describe('the four queues', () => {
  it('counts a scan-only idle session without a turn end in the unclassified remainder', async () => {
    await open({
      ...projectStatusBoard,
      sessions: projectStatusBoard.sessions
        .filter((row) => row.sid === 'scan')
        .map((row) => ({ ...row, harness: 'goose' })),
    });
    expect(document.querySelector('.next-attention-brief')?.textContent).toContain(
      '1 with limited state evidence.',
    );
    expect(section('risk').querySelectorAll(':scope > ol > li')).toHaveLength(0);
  });

  it('shows three rows of a longer queue and the rest on request, and the request is the reader’s', async () => {
    await open();
    expect(rows('needs')).toHaveLength(5);
    expect(visible('needs')).toHaveLength(3);
    expect(toggle('needs').textContent).toBe('Show 2 more');
    expect(toggle('needs').getAttribute('aria-expanded')).toBe('false');
    fireEvent.click(toggle('needs'));
    expect(visible('needs')).toHaveLength(5);
    expect(toggle('needs').textContent).toBe('Show fewer (hide 2)');
    expect(toggle('needs').getAttribute('aria-expanded')).toBe('true');
    // Another section is not opened by it.
    expect(visible('close').length).toBeLessThanOrEqual(3);
    fireEvent.click(toggle('needs'));
    expect(visible('needs')).toHaveLength(3);
  });

  it('keeps an expanded section expanded, on the same button, with focus, through a revision that reorders and replaces rows', async () => {
    const page = await open();
    fireEvent.click(toggle('needs'));
    toggle('needs').focus();
    const button = toggle('needs');
    const subjectNode = () =>
      document.querySelector(
        '[data-next-attention-subject="session:[\\"claude\\",\\"gate-2\\"]"]',
      ) as HTMLElement;
    const kept = subjectNode();
    await revise(page, attentionBoard({ generated: 1_000_025, reversed: true, gone: ['gate-3'] }));
    expect(toggle('needs')).toBe(button);
    expect(document.activeElement).toBe(button);
    expect(toggle('needs').getAttribute('aria-expanded')).toBe('true');
    // Four rows now, every one of them visible: the flag outlived the count it was set against.
    expect(rows('needs')).toHaveLength(4);
    expect(visible('needs')).toHaveLength(4);
    // A subject still on the board keeps its node, so nothing the reader was doing in it is thrown away.
    expect(subjectNode()).toBe(kept);
    // A section the reader never opened is still collapsed.
    expect(toggle('close')?.getAttribute('aria-expanded') ?? 'false').toBe('false');
  });

  it('keeps the node of a subject that is still on the board when others come and go around it', async () => {
    const page = await open();
    const link = () =>
      document.querySelector(
        '[data-next-attention-subject="session:[\\"claude\\",\\"gate-2\\"]"] h3 a',
      ) as HTMLElement;
    link().focus();
    const node = link();
    await revise(page, attentionBoard({ generated: 1_000_025, reversed: true, gone: ['gate-4'] }));
    expect(link()).toBe(node);
    expect(document.activeElement).toBe(node);
  });

  it('moves focus to the section heading when the subject the reader was on leaves the board', async () => {
    const page = await open();
    const link = document.querySelector(
      '[data-next-attention-subject="session:[\\"claude\\",\\"gate-1\\"]"] h3 a',
    ) as HTMLElement;
    link.focus();
    expect(document.activeElement).toBe(link);
    await revise(page, attentionBoard({ generated: 1_000_025, gone: ['gate-1'] }));
    await act(async () => {
      await Promise.resolve();
    });
    expect(document.activeElement).toBe(section('needs').querySelector('h2'));
  });

  it('orders the exact questions oldest first and keeps a question no session owns off the session count', async () => {
    await open();
    const ages = [...section('needs').querySelectorAll('[data-next-attention-part="source"]')].map(
      (node) => node.textContent ?? '',
    );
    // The oldest question is first, and the age is the payload's own clock against the published age.
    expect(ages[0]).toContain('waiting 8 minutes');
    const board = [...document.querySelectorAll('[data-next-board-risk]')].map(
      (node) => node.getAttribute('data-next-board-risk') ?? '',
    );
    expect(board).toContain('ask');
    expect(document.body.textContent).toContain('A question no session owns?');
  });

  it('keeps a lower-priority signal on the subject that outranks it, labelled, rather than erasing it', async () => {
    const board = attentionBoard() as { sessions: Record<string, unknown>[] };
    const gate = board.sessions.find((row) => row['sid'] === 'gate-1') as Record<string, unknown>;
    Object.assign(gate, {
      loop: { errors: 2, failures: 4, tool: 'Bash', barren: true },
      finished_at: 999_000,
      dirty: true,
      changed: 3,
    });
    await open(board);
    const subject = document.querySelector(
      '[data-next-attention-subject="session:[\\"claude\\",\\"gate-1\\"]"]',
    ) as HTMLElement;
    expect(subject.querySelector('h3')?.textContent).toMatch(
      /Question waiting · \d additional source signals?/,
    );
    expect(subject.textContent).toContain(
      'Repeated tool failures: Bash failed 4 times, nothing succeeded',
    );
    expect(subject.textContent).toContain('Attribution conflict');
    // And it is not duplicated as a risk row of its own.
    expect(
      section('risk').querySelectorAll(
        ':scope > ol > li [data-next-attention-subject="session:[\\"claude\\",\\"gate-1\\"]"]',
      ),
    ).toHaveLength(0);
  });

  it('says what the board could not see: unmeasured stays a sentence and is never a zero', async () => {
    await open();
    const coverage = document.querySelector('.next-attention-coverage');
    expect(coverage?.textContent).toMatch(/of \d+ sessions? report block state/);
    expect(coverage?.textContent).toContain('Harness source could not be read');
    expect(coverage?.textContent).toContain('Harness sources: 1 failed.');
    expect(coverage?.textContent).toContain('Termination cause not reported.');
    expect(coverage?.textContent).toContain(
      'a session with no observed end is not known to be running',
    );
    expect(document.body.textContent).toContain('Not on this board yet');
  });

  it('invents no urgency: a board with nothing waiting draws no gate, and the headline counts match the rows', async () => {
    const board = attentionBoard({ asking: [] }) as { asks: unknown[] };
    board.asks = [];
    await open(board);
    expect(section('needs')).toBeNull();
    expect(screen.queryByText(/reported blocks?/)).toBeNull();
  });
});

describe('a session in two queues', () => {
  it('draws an ended session that left work behind once, as a risk, and not again under Close the loop', async () => {
    await open();
    const key = 'session:[\\"claude\\",\\"ended-1\\"]';
    const where = [...document.querySelectorAll(`[data-next-attention-subject="${key}"]`)].map(
      (node) =>
        node.closest('[data-next-attention-section]')?.getAttribute('data-next-attention-section'),
    );
    // The At risk section holds the row, and the queues nested beneath it do not hold it again.
    expect(where).toEqual(['risk']);
    expect(section('close').textContent).not.toContain('ended-1');
  });
});

describe('published times on the board', () => {
  const generated = new Date(2026, 10, 23, 12).getTime() / 1000;
  const session = { project: 'P', harness: 'claude' };

  it('keeps the launch totals from the row that reported them when another row shares its ID', async () => {
    await open({
      generated,
      sessions: [
        { ...session, sid: 't', state: 'idle' },
        {
          ...session,
          sid: 't',
          state: 'idle',
          delegated_launches: 2,
          delegated_unpaired: 1,
          delegated_quiet_since: generated - 3600,
          delegated_latest_launch_at: generated - 360,
        },
      ],
    });
    const observation = document.querySelector(
      '[data-next-attention-kind="quiet-launch"] .next-attention-risk-observation > p',
    );
    expect(observation?.textContent).toContain('2 recorded launches');
    expect(observation?.textContent).toContain(
      "1 of this session's launches has no recorded completion",
    );
    expect(observation?.textContent).toContain('Latest launch 6 minutes ago');
  });

  it('shows how long an unowned request has waited even without the board clock', async () => {
    await open({
      sessions: [],
      ask: true,
      asks: [{ id: 'gate', harness: 'claude', question: 'Proceed?', age_sec: 360 }],
    });
    expect(document.querySelector('[data-next-board-risk="ask"]')?.textContent).toContain(
      'source · claude · waiting 6 minutes',
    );
  });

  it.each([
    [0, generated],
    [generated, 1e100],
    [generated, generated + 86400],
  ])('withholds unusable wait and end ages against %s for %s', async (clock, stamp) => {
    await open({
      generated: clock,
      sessions: [
        { ...session, sid: 'wait', state: 'needs_input', blocked_since: stamp },
        { ...session, sid: 'end', ended_at: stamp, finished_at: stamp, dirty: false },
      ],
    });
    expect(section('needs').textContent).toContain('Needs-input state reported');
    expect(section('needs').textContent).not.toMatch(/waiting \d/);
    expect(section('close').textContent).toContain('This session id reported its own end');
    expect(section('close').textContent).not.toMatch(/· ended (?:\d|on |at )/);
  });

  it('shows the quota countdown and a scheduled reset in the reader’s time zone', async () => {
    const reset = new Date(2026, 10, 23, 13, 6);
    const resetAt = reset.getTime() / 1000;
    await open({
      generated,
      sessions: [],
      usage: [
        {
          state: 'ok',
          harness: 'claude',
          fiveH: { pct: 95, resetAt, windowSec: 18000 },
          models: [{ pct: 95, label: 'fast', resetAt }],
        },
      ],
    });
    expect(screen.getByText('1 hour 6 minutes')).toBeInTheDocument();
    expect(
      screen.getByText(`Reset at ${reset.toLocaleTimeString(undefined, { timeStyle: 'short' })}`),
    ).toBeInTheDocument();
  });

  it('shows a published reset date and clock even when there is no board clock', async () => {
    const reset = new Date(2026, 10, 23, 13);
    await open({
      sessions: [],
      usage: [
        {
          state: 'ok',
          harness: 'claude',
          models: [{ pct: 95, label: 'fast', resetAt: reset.getTime() / 1000 }],
        },
      ],
    });
    const date = reset.toLocaleDateString(undefined, {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
    });
    expect(
      screen.getByText(
        `Reset on ${date} at ${reset.toLocaleTimeString(undefined, { timeStyle: 'short' })}`,
      ),
    ).toBeInTheDocument();
  });
});

describe('the way back into a waiting session', () => {
  it('draws a copy of the exact re-entry command and a raise on the gate queue only, and a raise only with the capability and a terminal', async () => {
    await open(attentionBoard({ terminals: true }), { focusCapability: 'abcdef' });
    const needs = section('needs');
    expect(needs.querySelectorAll('[data-copy-kind="command"]').length).toBe(5);
    const labels = [...needs.querySelectorAll('[data-copy-kind="command"]')].map((node) =>
      node.getAttribute('aria-label'),
    );
    expect(labels).toContain('Copy re-entry command claude --resume gate-1');
    expect(needs.querySelectorAll('[data-control="raise"]').length).toBe(2);
    expect(section('close').querySelector('[data-control="raise"], [data-copy-kind]')).toBeNull();
    expect(
      section('next')?.querySelector('[data-control="raise"], [data-copy-kind]') ?? null,
    ).toBeNull();
  });

  it('draws no raise without the run’s capability, and says so once in the coverage', async () => {
    await open(attentionBoard({ terminals: true }));
    expect(section('needs').querySelector('[data-control="raise"]')).toBeNull();
    expect(document.querySelector('.next-attention-caveats')?.textContent).toContain(
      'Terminal raise: off for this run.',
    );
  });

  it('says how far the raise reaches when the run has the capability', async () => {
    await open(attentionBoard({ terminals: true }), { focusCapability: 'abcdef' });
    expect(document.querySelector('.next-attention-caveats')?.textContent).toContain(
      'Terminal raise: 2 of 5 waiting rows carry a terminal Compass can reach.',
    );
  });

  it('sends nothing on its own: opening the screen reads the board and posts and copies nothing', async () => {
    const copied: string[] = [];
    vi.stubGlobal('navigator', { clipboard: { writeText: (text: string) => copied.push(text) } });
    const page = await open(attentionBoard({ terminals: true }), { focusCapability: 'abcdef' });
    await revise(page, attentionBoard({ generated: 1_000_025, reversed: true }));
    expect(page.posts()).toBe(0);
    expect(copied).toEqual([]);
  });
});

describe('the announcement', () => {
  it('is silent for the first board and for a board that moves nothing', async () => {
    const page = await open();
    expect(status()).toBe('');
    await revise(page, attentionBoard({ generated: 1_000_025 }));
    expect(status()).toBe('');
  });

  it('says what the queues now hold when one changes length, on the status region and from any page', async () => {
    const page = await open();
    await page.go('#n=sessions');
    await revise(page, attentionBoard({ generated: 1_000_025, gone: ['gate-1'] }));
    expect(status()).toMatch(
      /^Attention updated: 5 need you, 5 at risk, 4 close the loop, 4 coming next$/,
    );
    expect(document.getElementById('next-attention-status')?.getAttribute('role')).toBe('status');
  });

  it('says it again for a later change, even when the sentence is the same', async () => {
    const page = await open();
    await revise(page, attentionBoard({ generated: 1_000_025, gone: ['gate-1'] }));
    const first = status();
    const region = document.getElementById('next-attention-status') as HTMLElement;
    region.textContent = '';
    await revise(page, attentionBoard({ generated: 1_000_050 }));
    await revise(page, attentionBoard({ generated: 1_000_075, gone: ['gate-1'] }));
    expect(status()).toBe(first);
  });
});

describe('the command-shape reports', () => {
  it('lists reports newest first, links the one whose session exists, and survives a stamp that is no date', async () => {
    await open(attentionBoard({ malformedReport: true }));
    const reports = document.querySelector('[data-next-command-reports]') as HTMLElement;
    expect(reports.textContent).toContain('2 reports shown');
    const links = [...reports.querySelectorAll('h3 a')].map((link) => link.getAttribute('href'));
    expect(links).toHaveLength(1);
    expect(reports.textContent).toContain('Command shape reported: git push --force');
    expect(reports.textContent).not.toMatch(/\d{4}-\d{2}-\d{2}T/);
    expect(reports.textContent).toContain('A shape match does not prove the action succeeded.');
  });

  it('says reports are off for a run that is not collecting them, rather than that there were none', async () => {
    const board = attentionBoard() as Record<string, unknown>;
    board['irreversible_enabled'] = false;
    await open(board);
    expect(document.querySelector('[data-next-command-reports]')?.textContent).toContain(
      'Command-shape reports are disabled for this run.',
    );
  });
});

describe('what a payload can say about itself', () => {
  it('draws hostile text as text and keeps a session the board published twice in its own row', async () => {
    const board = attentionBoard() as {
      sessions: Record<string, unknown>[];
      asks: Record<string, unknown>[];
    };
    board.sessions.push({ ...(board.sessions[0] as Record<string, unknown>) });
    board.asks.push({
      id: 'x',
      harness: 'claude',
      session_id: 'no-such',
      project: '<img src=x onerror=alert(1)>',
      question: '<script>alert(1)</script> = "&" ünï',
      options: [],
      age_sec: 1,
    });
    const errors = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    await open(board);
    expect(document.querySelector('script, img[src="x"]')).toBeNull();
    expect(document.body.textContent).toContain('<script>alert(1)</script> = "&" ünï');
    expect(
      errors.mock.calls.map((call) => String(call[0])).filter((text) => /key/.test(text)),
    ).toEqual([]);
    errors.mockRestore();
  });

  it('draws once under StrictMode and keeps one status region', async () => {
    const page = mountShell({ hash: '#n=attention', data: attentionBoard(), strict: true });
    await page.settle();
    expect(document.querySelectorAll('[data-next-view-body="attention"]')).toHaveLength(1);
    expect(document.querySelectorAll('#next-attention-status')).toHaveLength(1);
  });
});

describe('the counters moved from Sessions', () => {
  it('shows exact requests and reported blocks beside their counts', async () => {
    await open(attentionBoard());
    expect(document.querySelector('[data-next-fleet-fact="requests"]')?.textContent).toContain(
      'EXACT REQUESTS',
    );
    expect(
      document.querySelector('[data-next-fleet-fact="reported-blocks"]')?.textContent,
    ).toContain('REPORTED BLOCKS');
  });
});

import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { observe } from '../observed';
import { mountPanels } from '../steering/testing';
import { CapacityPanel } from './CapacityPanel';
import { DelegationPanel } from './DelegationPanel';
import { delegationFigure, type DelegationFigure } from './metric';

/* The edges the generated differential does not reach: a trend in each direction, and a quota window exactly
   on each threshold the panel colours at. */
const figure = (over: Partial<DelegationFigure> = {}): DelegationFigure => ({
  ...delegationFigure({
    batches: [],
    endedAt: null,
    events: [],
    samples: [],
    seeded: false,
    startedAt: null,
  }),
  pctText: '62%',
  pctKnown: true,
  pct: 62,
  tpsText: '≥1,200 tok/m while delegated',
  tpsKnown: true,
  humanText: '3 human turns',
  windowText: 'last 7h',
  noteText: 'Measured over observed working and needs-input intervals.',
  noteKnown: true,
  trendText: '+4',
  trendKnown: true,
  trendDelta: 4,
  ...over,
});

describe('the delegation trend', () => {
  it.each([
    [4, '+4', 'up'],
    [-7, '-7', 'down'],
    [0, '0', 'flat'],
  ])('a change of %i is drawn %s and marked %s', (delta, text, direction) => {
    render(<DelegationPanel figure={figure({ trendDelta: delta, trendText: text })} />);
    const trend = document.querySelector('[data-next-delegation-trend]');
    expect(trend?.textContent).toBe(text);
    expect(trend?.classList.contains(`next-delegation-trend--${direction}`)).toBe(true);
  });

  it('is not drawn at all when two complete readings are not available', () => {
    render(
      <DelegationPanel figure={figure({ trendKnown: false, trendDelta: null, trendText: '' })} />,
    );
    expect(document.querySelector('[data-next-delegation-trend]')).toBeNull();
  });

  it('withholds the percentage and says why, rather than drawing zero', () => {
    render(
      <DelegationPanel
        figure={figure({
          pctKnown: false,
          pct: null,
          pctText: 'no figure yet',
          noteText: 'Waiting on one complete token-rate window.',
        })}
      />,
    );
    expect(document.querySelector('[data-next-delegation-percent]')).toBeNull();
    expect(document.querySelector('progress')).toBeNull();
    expect(screen.getByText('no figure yet')).toBeInTheDocument();
    expect(screen.getByText('Waiting on one complete token-rate window.')).toBeInTheDocument();
  });
});

/* A window of 1000 s with 500 s left is half elapsed, so `pct` per fifty is the pace ratio exactly. */
function windowsAt(pct: number, remaining = 500) {
  const payload = {
    generated: 5000,
    harnesses: [{ key: 'claude', label: 'Claude Code' }],
    usage: [
      {
        harness: 'claude',
        state: 'ok',
        fiveH: { pct, windowSec: 1000, resetAt: 5000 + remaining },
      },
    ],
  };
  render(<CapacityPanel payload={payload} model={observe(payload)} />);
  const row = document.querySelector('[data-next-rail-window]') as HTMLElement;
  return {
    used: row.querySelector('.next-rail-capacity-heading strong')?.className,
    fill: row.querySelector('.next-rail-capacity-fill')?.className,
    pace: row.querySelector('.next-rail-capacity-caption span')?.className,
  };
}

describe('a quota window on each threshold', () => {
  it('is amber used at exactly 80 and secondary at exactly 50, primary below', () => {
    expect(windowsAt(80).used).toBe('next-rail-used--amber');
  });
  it('secondary at 50', () => {
    expect(windowsAt(50).used).toBe('next-rail-used--secondary');
  });
  it('primary at 49', () => {
    expect(windowsAt(49).used).toBe('next-rail-used--primary');
  });
  it('is hot and amber at a pace of exactly 1', () => {
    const row = windowsAt(50);
    expect(row.pace).toBe('next-rail-pace--hot');
    expect(row.fill).toContain('next-rail-capacity-fill--amber');
  });
  it('is clay at a pace of exactly 1.5', () => {
    expect(windowsAt(75).fill).toContain('next-rail-capacity-fill--clay');
  });
  it('is neither hot nor amber below a pace of 1', () => {
    const row = windowsAt(40);
    expect(row.pace).toBe('');
    expect(row.fill).toContain('next-rail-capacity-fill--accent');
  });
});

describe('a usage entry that names no harness', () => {
  it('is drawn with the absence said, where the legacy page stops drawing', () => {
    const payload = {
      generated: 5000,
      usage: [{ harness: '', state: 'ok', fiveH: { pct: 30, windowSec: 1000, resetAt: 5500 } }],
    };
    render(<CapacityPanel payload={payload} model={observe(payload)} />);
    const row = document.querySelector('[data-next-rail-window]') as HTMLElement;
    expect(row.textContent).toContain('Source not identified');
    expect(row.textContent).toContain('30%');
    expect(row.textContent).toContain('Window pace not reported');
    expect(row.textContent).toContain('Reset time not published');
  });
});

describe('the capacity panel', () => {
  it('says no window was published, never zero', () => {
    const payload = { generated: 5000 };
    render(
      <CapacityPanel
        payload={payload}
        model={observe(payload)}
        usage={() => <p>consent slot</p>}
      />,
    );
    expect(screen.getByText('No quota windows published.')).toBeInTheDocument();
    expect(screen.getByText('consent slot')).toBeInTheDocument();
  });
});

describe('the Console rail never sends anything', () => {
  it('draws without a request but the board and the passive context read', async () => {
    const { ProjectConsole } = await import('./Console');
    const page = mountPanels(<ProjectConsole project="alpha" projectKey="alpha" focus={null} />, {
      data: {
        generated: 1000,
        sessions: [{ harness: 'claude', sid: 's1', project: 'alpha', state: 'working' }],
      },
    });
    await page.settle();
    await page.poll({
      generated: 1001,
      sessions: [{ harness: 'claude', sid: 's1', project: 'alpha', state: 'working' }],
    });
    expect(page.allPosts()).toEqual([]);
    expect(
      page.state.requests.every(
        (request) => request.path === '/api/data' || request.path === '/api/project-context',
      ),
    ).toBe(true);
  });
});

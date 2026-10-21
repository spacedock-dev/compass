import { act, render } from '@testing-library/react';
import { StrictMode } from 'react';
import { describe, expect, it } from 'vitest';
import { ControlsProvider } from '../controls';
import { testControls } from '../controls/testControls';
import { genPayload } from '../observed/generate.test.helper';
import { loadLegacyViews } from '../observed/legacy.test.helper';
import type { Row } from '../observed';
import { DelegatedWorkLine, UnaskedDepartureBody } from './DepartureParts';
import { retractSessionCopies } from '../../test/sessionCopyDeviation';
import { maskRevisionWords } from '../../test/revisionWordDeviation';

/* The departure rows, the way back beside them and the delegated-work line, held to the legacy page's own
   functions over every session a generated payload carries. The comparison is the rendered text, plus the
   accessible names of the controls, because a missing way back is exactly what a text-only comparison would
   miss. */

const legacy = loadLegacyViews();
const CASES = 40;
const norm = (node: Element | null): string =>
  node ? (node.textContent ?? '').replace(/\s+/g, ' ').trim() : '';

function sessionsOf(seed: number): Row[] {
  const payload = genPayload(seed, { wellFormed: true });
  return (Array.isArray(payload['sessions']) ? (payload['sessions'] as Row[]) : []).filter(
    (row) => typeof row['sid'] === 'string' || typeof row['sid'] === 'number',
  );
}

function labels(root: ParentNode): string[] {
  return [...root.querySelectorAll('button')].map(
    (button) => button.getAttribute('aria-label') ?? '',
  );
}

describe('the departure rows read as the legacy rows do', () => {
  for (const capability of [false, true]) {
    it(`agrees over generated sessions${capability ? ', with a terminal-raise capability' : ''}`, () => {
      legacy.setFocusCapability(capability ? 'minted' : '');
      let compared = 0;
      let withRows = 0;
      for (let seed = 1; seed <= CASES; seed += 1) {
        for (const session of sessionsOf(seed)) {
          legacy.setData(genPayload(seed, { wellFormed: true }));
          const html = legacy.call<string>('nextUnaskedDepartureBody', session);
          const template = document.createElement('template');
          template.innerHTML = html;
          retractSessionCopies(template.content);
          const kit = testControls(capability ? {} : { focus: null });
          const view = render(
            <StrictMode>
              <ControlsProvider controls={kit.controls}>
                <div data-root>
                  <UnaskedDepartureBody session={session} />
                </div>
              </ControlsProvider>
            </StrictMode>,
          );
          const root = view.container.querySelector('[data-root]') as Element;
          expect({ seed, sid: session['sid'], text: maskRevisionWords(norm(root)) }).toEqual({
            seed,
            sid: session['sid'],
            text: maskRevisionWords(norm(template.content as unknown as Element)),
          });
          // `norm` of a fragment is its text; the controls are compared by what they are called.
          expect({ seed, controls: labels(root) }).toEqual({
            seed,
            controls: labels(template.content),
          });
          compared += 1;
          if (html) withRows += 1;
          view.unmount();
        }
      }
      expect(compared).toBeGreaterThan(100);
      expect(withRows).toBeGreaterThan(10);
    });
  }

  it('draws nothing for a session with no departure and no sentence about why', () => {
    const kit = testControls();
    const view = render(
      <ControlsProvider controls={kit.controls}>
        <div data-root>
          <UnaskedDepartureBody session={{ harness: 'claude', sid: 's' }} />
        </div>
      </ControlsProvider>,
    );
    expect(view.container.querySelector('[data-root]')?.innerHTML).toBe('');
  });

  it('writes nothing to the clipboard and raises nothing on mount', async () => {
    const kit = testControls();
    render(
      <StrictMode>
        <ControlsProvider controls={kit.controls}>
          <UnaskedDepartureBody
            session={{
              harness: 'claude',
              sid: 's',
              resume_id: 'abc-1',
              focusable: true,
              departures: [{ at: 100, revision: 1, constraint: 'goal', reading: 'r' }],
            }}
          />
        </ControlsProvider>
      </StrictMode>,
    );
    await act(() => Promise.resolve());
    expect(kit.written).toEqual([]);
    expect(kit.raised).toEqual([]);
  });
});

describe('the delegated-work line reads as the legacy line does', () => {
  it('agrees on the sentence, the drawing rule and the check, for every generated session at several clocks', () => {
    for (let seed = 1; seed <= CASES; seed += 1) {
      for (const session of sessionsOf(seed)) {
        for (const now of [1000, 5000, 1e7]) {
          const work = legacy.call<{ draw: boolean; risky: boolean; text: string }>(
            'nextDelegatedWork',
            session,
            now,
          );
          const view = render(<DelegatedWorkLine session={session} now={now} />);
          const lines = [...view.container.querySelectorAll('p')].map((node) => node.textContent);
          expect(lines).toEqual(
            work.draw
              ? work.risky
                ? [
                    work.text,
                    'Is the work this session launched still running? Show its process and latest output.',
                  ]
                : [work.text]
              : [],
          );
          view.unmount();
        }
      }
    }
  });
});

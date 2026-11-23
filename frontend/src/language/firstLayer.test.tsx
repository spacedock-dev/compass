import { render, within } from '@testing-library/react';
import { expect, it } from 'vitest';
import states from '../../test/fixtures/client-contract/data-session-states.json';
import focused from '../../test/fixtures/client-contract/data-focused-drift.json';
import { fragmentForRoute } from '../router/grammar';
import { mountShell } from '../shell/testing';
import { FIRST_LAYER_EXCEPTIONS, FIRST_LAYER_RETIREMENTS } from './glossary';

const OUTSIDE_FIRST_LAYER = '[data-layer="technical"], [data-authored], script, style';
const ATTRIBUTES = ['aria-label', 'title', 'placeholder'] as const;

function violations(root: Element, retired: readonly RegExp[] = FIRST_LAYER_RETIREMENTS) {
  const matches: string[] = [];
  for (const element of [root, ...root.querySelectorAll('*')]) {
    if (element.closest(OUTSIDE_FIRST_LAYER)) continue;
    const location = `<${element.localName}${element.id ? ` id="${element.id}"` : ''}>`;
    const inspect = (text: string, source: string) => {
      const words = FIRST_LAYER_EXCEPTIONS.reduce(
        (copy, exception) => copy.replace(exception, ' '),
        text,
      ).trim();
      if (retired.some((pattern) => pattern.test(words)))
        matches.push(`${location} ${source} ${JSON.stringify(text.trim())}`);
    };
    for (const attribute of ATTRIBUTES) {
      const value = element.getAttribute(attribute);
      if (value) inspect(value, attribute);
    }
    for (const node of element.childNodes) {
      if (node.nodeType === Node.TEXT_NODE && node.textContent?.trim())
        inspect(node.textContent, 'text');
    }
  }
  return matches;
}

// Add later pages here with their recorded client-contract board and a route that reaches the view.
it.each([states, focused])(
  'keeps Compass copy on Sessions and the Session page current over $name',
  async ({ response }) => {
    const data = response.body;
    const page = mountShell({ data });
    await page.settle();
    expect(
      within(page.container).getByRole('link', { name: 'Sessions', current: 'page' }),
    ).toBeVisible();
    expect(violations(page.container)).toEqual([]);
    for (const row of data.sessions) {
      if (!row.sid || !row.harness) continue;
      await page.go(
        fragmentForRoute({
          view: 'session',
          project: row.project ?? '',
          harness: row.harness,
          session: row.sid,
        }),
      );
      const article = page.container.querySelector('[data-next-session-detail]');
      expect(article, row.sid).not.toBeNull();
      expect(violations(page.container), row.sid).toEqual([]);
    }
  },
);

it('names the text, attribute and element for planted Compass copy', () => {
  const { container } = render(
    <div>
      <h2 id="planted-label">Intent</h2>
      <button type="button" aria-label="Analyze drift">
        Read
      </button>
      <p title="Pause model calls">Pause</p>
      <input placeholder="Mark as inaccurate" />
    </div>,
  );
  expect(violations(container)).toEqual([
    '<h2 id="planted-label"> text "Intent"',
    '<button> aria-label "Analyze drift"',
    '<p> title "Pause model calls"',
    '<input> placeholder "Mark as inaccurate"',
  ]);
});

it('allows authored words, technical evidence, product names and pull request numbers', () => {
  const { container } = render(
    <div>
      <h2 data-authored title="Intent">
        Intent for a drift check
      </h2>
      <blockquote data-authored>
        <span aria-label="Intent">Compare drift</span>
      </blockquote>
      <section data-layer="technical">
        <p>Live monitor · Haiku · revision 2 · entry #8 · [7]</p>
      </section>
      <p title="Claude Code">Review #482 in Claude Code</p>
    </div>,
  );
  expect(violations(container)).toEqual([]);
});

it('allows the same wording in the mounted session title and goal', async () => {
  const board = states.response.body;
  const one = board.sessions[0];
  if (!one) throw new Error('The recorded board has no session');
  const title = 'Intent and drift for #482';
  const goal = 'Trace drift in the Intent parser';
  const page = mountShell({
    hash: fragmentForRoute({
      view: 'session',
      project: one.project ?? '',
      harness: one.harness,
      session: one.sid,
    }),
    data: {
      ...board,
      sessions: [
        {
          ...one,
          title,
          annotation_goal: goal,
          annotation_revision: 1,
          annotation_at: board.generated - 60,
        },
      ],
    },
  });
  await page.settle();
  const view = within(page.container);
  expect(view.getByRole('heading', { name: title })).toBeVisible();
  expect(view.getByText(goal)).toBeVisible();
  expect(violations(page.container)).toEqual([]);
});

it('applies a retirement added to the glossary rules without a change to the walk', () => {
  const { container } = render(<button type="button">Legacy action</button>);
  expect(violations(container)).toEqual([]);
  expect(violations(container, [...FIRST_LAYER_RETIREMENTS, /\blegacy action\b/i])).toEqual([
    '<button> text "Legacy action"',
  ]);
});

import { act } from '@testing-library/react';
import { withoutCodexRecordedStops } from '../../test/codexRecordedStop';
import { describe, expect, it } from 'vitest';
import { genPayload } from '../observed/generate.test.helper';
import { mountShell } from '../shell/testing';
import { expansionFor } from './expansion';
import { loadLegacyAttention } from './legacy.test.helper';

/* The Attention screen, held to the legacy page by what a reader can read. The legacy `nextAttentionView`
   runs unchanged over a generated payload, and this screen renders the same payload in the real shell;
   both are reduced to the same shape (each section, each row in order, its text, its routes and the
   controls it carries) and compared. A difference is a bug here unless it is named in DEVIATIONS with its
   reason. Two states of the page are compared: sections as first drawn (three rows, the rest hidden) and
   every section expanded by the reader. The terminal raise is compared with and without the run's
   capability, because the coverage line and the controls both depend on it. */

const legacy = loadLegacyAttention();

interface Item {
  readonly hidden: boolean;
  readonly subject: string;
  readonly subjectKey: string;
  readonly kind: string;
  readonly tone: string;
  readonly board: string;
  readonly text: string;
  readonly links: readonly (readonly [string, string])[];
  readonly buttons: readonly (string | null)[];
}

interface Summary {
  readonly heading: string;
  readonly brief: string;
  readonly empty: string | null;
  readonly coverageRows: readonly string[];
  readonly caveats: readonly string[];
  readonly projectsLink: readonly [string, string] | null;
  readonly sections: readonly {
    readonly name: string;
    readonly heading: string;
    readonly note: string;
    readonly toggle: readonly [string, string, string] | null;
    readonly items: readonly Item[];
  }[];
  readonly reports: string;
  readonly reportLinks: readonly (readonly [string, string])[];
  readonly open: readonly string[];
}

const norm = (node: Element | null): string =>
  node ? (node.textContent ?? '').replace(/\s+/g, ' ').trim() : '';

const links = (node: Element): [string, string][] =>
  [...node.querySelectorAll('a')].map(
    (link) =>
      [link.getAttribute('href') ?? '', link.getAttribute('data-next-route') ?? ''] as [
        string,
        string,
      ],
  );

function summarize(root: ParentNode): Summary {
  const attention = root.querySelector('[data-next-view-body="attention"]');
  if (!attention) throw new Error('No Attention view was drawn.');
  const section = (element: Element) => ({
    name: element.getAttribute('data-next-attention-section') ?? '',
    heading: norm(
      element.querySelector(':scope > h2, :scope > .next-attention-section-heading h2'),
    ),
    note: norm(element.querySelector(':scope > .next-attention-section-heading p')),
    toggle: ((): readonly [string, string, string] | null => {
      const button = element.querySelector(':scope > button[data-next-attention-toggle]');
      return button
        ? [
            norm(button),
            button.getAttribute('aria-expanded') ?? '',
            button.getAttribute('aria-controls') ?? '',
          ]
        : null;
    })(),
    items: [...element.querySelectorAll(':scope > ol > li')].map((li) => {
      const article = li.querySelector('article') as HTMLElement;
      return {
        hidden: li.hasAttribute('hidden'),
        subject: article.dataset['nextAttentionSubject'] ?? '',
        subjectKey: article.dataset['nextSubjectKey'] ?? '',
        kind: article.dataset['nextAttentionKind'] ?? '',
        tone: article.dataset['tone'] ?? '',
        board: article.dataset['nextBoardRisk'] ?? '',
        text: norm(article),
        links: links(article),
        buttons: [...article.querySelectorAll('button')].map((button) =>
          button.getAttribute('aria-label'),
        ),
      };
    }),
  });
  const reports = attention.querySelector('[data-next-command-reports]');
  const projectsLink = attention.querySelector('.next-attention-projects-link');
  return {
    heading: norm(attention.querySelector('.next-attention-heading')),
    brief: norm(attention.querySelector('.next-attention-brief > p')),
    empty: norm(attention.querySelector('.next-attention-empty')) || null,
    coverageRows: [...attention.querySelectorAll('[data-next-coverage-harness]')].map(
      (row) =>
        `${row.getAttribute('data-next-coverage-harness')}|${norm(row)}|${[...row.querySelectorAll('[data-known]')].map((square) => square.getAttribute('data-known')).join(',')}`,
    ),
    caveats: [...attention.querySelectorAll('.next-attention-caveats p')].map((p) => norm(p)),
    projectsLink: projectsLink
      ? [
          projectsLink.getAttribute('href') ?? '',
          projectsLink.getAttribute('data-next-route') ?? '',
        ]
      : null,
    sections: [...attention.querySelectorAll('section[data-next-attention-section]')]
      .filter((element) => element.getAttribute('data-next-attention-section') !== 'open')
      .map(section),
    reports: norm(reports),
    reportLinks: reports ? links(reports) : [],
    open: [...attention.querySelectorAll('[data-next-open]')].map((row) => norm(row)),
  };
}

function legacySummary(payload: unknown, expanded: readonly string[], capability: string): Summary {
  legacy.setFocusCapability(capability);
  const template = document.createElement('template');
  template.innerHTML = legacy.attentionHtml(payload, expanded);
  return summarize(template.content);
}

async function reactSummary(
  payload: unknown,
  expanded: readonly string[],
  capability: string,
): Promise<Summary> {
  const page = mountShell({
    hash: '#n=attention',
    data: payload,
    strict: false,
    ...(capability ? { focusCapability: capability } : {}),
  });
  await page.settle();
  await act(async () => {
    for (const name of expanded) expansionFor(page.shell.controls).toggle(name);
  });
  const result = summarize(page.container);
  page.unmount();
  return result;
}

/* Named differences, each with its reason. */
const DEVIATIONS: readonly {
  readonly seed: number;
  readonly path: string;
  readonly reason: string;
}[] = [];

function firstDifference(left: string, right: string): string {
  let at = 0;
  while (left[at] === right[at]) at += 1;
  return `near ${JSON.stringify(left.slice(Math.max(0, at - 90), at + 160))} vs ${JSON.stringify(right.slice(Math.max(0, at - 90), at + 160))}`;
}

const CASES = 40;
const SEEDS = CASES;

describe('the Attention screen reads as the legacy screen does, over generated payloads', () => {
  it(`agrees on ${String(SEEDS)} seeds, collapsed and expanded, with and without the terminal raise`, async () => {
    const failures: string[] = [];
    let controls = 0;
    let hiddenRows = 0;
    let boardRows = 0;
    for (let seed = 1; seed <= SEEDS && failures.length < 3; seed += 1) {
      const payload = genPayload(seed, { wellFormed: true });
      const arms: [readonly string[], string][] = [
        [[], ''],
        [['needs', 'close', 'next'], 'abcdef'],
      ];
      for (const [expanded, capability] of arms) {
        const old = legacySummary(payload, expanded, capability);
        const mine = await reactSummary(withoutCodexRecordedStops(payload), expanded, capability);
        const left = JSON.stringify(old);
        const right = JSON.stringify(mine);
        if (left !== right && !DEVIATIONS.some((d) => d.seed === seed)) {
          failures.push(
            `seed ${String(seed)} (${expanded.length ? 'expanded' : 'collapsed'}, capability ${capability || 'none'}): ${firstDifference(left, right)}`,
          );
          break;
        }
        for (const section of old.sections)
          for (const item of section.items) {
            if (item.buttons.length) controls += 1;
            if (item.hidden) hiddenRows += 1;
            if (item.board) boardRows += 1;
          }
      }
    }
    expect(failures).toEqual([]);
    // Agreement over empty screens would prove nothing.
    expect(controls).toBeGreaterThan(0);
    expect(hiddenRows).toBeGreaterThan(0);
    expect(boardRows).toBeGreaterThan(0);
  }, 240_000);
});

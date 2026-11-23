import { act } from '@testing-library/react';
import { withoutCodexRecordedStops } from '../../test/codexRecordedStop';
import { describe, expect, it } from 'vitest';
import { genPayload } from '../observed/generate.test.helper';
import { sessionKey } from '../observed';
import { attentionSelectionFor } from './select';
import { mountShell } from '../shell/testing';
import { expansionFor } from './expansion';
import { loadLegacyAttention } from './legacy.test.helper';
import {
  maskQuotaDuration,
  maskReportTime,
  maskSourceTime,
  maskTimePhrases,
} from './timing.test.helper';

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
      const content = article.cloneNode(true) as HTMLElement;
      // Replacement location cards change following indices; the array still checks row order.
      content.querySelector('.next-attention-index')?.remove();
      // The recording suppressed the native wait on a row with an exact question.
      if (content.dataset['nextAttentionKind'] === 'ask') {
        const input = [...content.querySelectorAll('.next-attention-now-value')].find((line) =>
          / · Input signal observed:/.test(norm(line)),
        );
        const label = content.querySelector('.next-attention-why a');
        if (input && label) {
          input.remove();
          label.textContent = norm(label).replace(
            / · (\d+) additional source signals?$/,
            (_, count: string) => {
              const previous = Number(count) - 1;
              return previous > 0
                ? ` · ${String(previous)} additional source signal${previous === 1 ? '' : 's'}`
                : '';
            },
          );
        }
      }
      content.querySelector('[data-next-native-wait]')?.remove();
      const source = content.querySelector(
        '[data-next-attention-part="source"] > span:last-child',
      )?.firstChild;
      if (source?.nodeType === Node.TEXT_NODE)
        source.textContent = maskSourceTime(source.textContent ?? '');
      if (article.dataset['nextBoardRisk'] === 'ask') {
        // Request identifiers are still available in the technical layer.
        content.querySelector('.next-attention-risk-identity > span')?.remove();
        content.querySelector('.technical-details')?.remove();
        const source = content.querySelector('.next-attention-risk-source > span:last-child');
        if (source) source.textContent = maskSourceTime(norm(source));
      }
      if (article.dataset['nextAttentionKind'] === 'quota') {
        const next = content.querySelector('.next-attention-risk-next');
        if (next) next.textContent = maskQuotaDuration(norm(next));
      }
      return {
        hidden: li.hasAttribute('hidden'),
        subject: article.dataset['nextAttentionSubject'] ?? '',
        subjectKey: article.dataset['nextSubjectKey'] ?? '',
        kind: article.dataset['nextAttentionKind'] ?? '',
        tone: article.dataset['tone'] ?? '',
        board: article.dataset['nextBoardRisk'] ?? '',
        text: maskTimePhrases(norm(content)),
        links: links(article),
        buttons: [...content.querySelectorAll('button')].map((button) =>
          button.getAttribute('aria-label'),
        ),
      };
    }),
  });
  const reports = attention.querySelector('[data-next-command-reports]');
  const reportsText = reports?.cloneNode(true) as HTMLElement | undefined;
  for (const source of reportsText?.querySelectorAll('.next-attention-risk-source') ?? []) {
    source.textContent = maskReportTime(norm(source));
  }
  const projectsLink = attention.querySelector('.next-attention-projects-link');
  return {
    heading: norm(attention.querySelector('.next-attention-heading')),
    brief: norm(attention.querySelector('.next-attention-brief > p')),
    empty:
      norm(attention.querySelector('.next-attention-empty')).replace(
        /^(No sessions in this [\d.-]+)h payload$/,
        '$1-hour payload',
      ) || null,
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
    reports: norm(reportsText ?? null),
    reportLinks: reports ? links(reports) : [],
    open: [...attention.querySelectorAll('[data-next-open]')].map((row) => norm(row)),
  };
}

function legacySummary(payload: unknown, expanded: readonly string[], capability: string): Summary {
  legacy.setFocusCapability(capability);
  const template = document.createElement('template');
  template.innerHTML = legacy.attentionHtml(payload, expanded);
  const summary = summarize(template.content);
  return {
    ...summary,
    coverageRows: summary.coverageRows.map((row) =>
      row.replace('Harness does not report blocks', 'Waits not reported'),
    ),
  };
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

function unchangedView(summary: Summary, restored: Set<string>): Summary {
  // The 2026-11-23 redesign replaces the three session card layouts and moves Coming next.
  // Compare their exact session membership above. Keep coverage, command reports and the unchanged
  // off-count evidence against the recording after masking their new container and locations.
  const sections = summary.sections.flatMap((section) => {
    if (section.name !== 'board-risk') return [];
    const items = section.items.filter(
      ({ kind, subjectKey }) =>
        kind !== 'collision' &&
        kind !== 'checkout' &&
        kind !== 'quota' &&
        !restored.has(subjectKey),
    );
    return items.length ? [{ ...section, heading: '', items }] : [];
  });
  return {
    ...summary,
    heading: summary.heading.replace(/ ?what is observed, and what the board could not see$/, ''),
    brief: '',
    caveats: summary.caveats.filter((text) => text !== 'No shared display label observed'),
    sections,
  };
}

function selectedQueues(summary: Summary, payload: object) {
  const selection = attentionSelectionFor(payload);
  if (!selection) throw new Error('Expected selection for a generated board');
  for (const [name, rows] of [
    ['needs', selection.waitingOnYou],
    ['risk', [...selection.worthALook.keys()]],
    ['close', selection.readyToWrapUp],
  ] as const) {
    const items = summary.sections.find((section) => section.name === name)?.items ?? [];
    expect(items.map(({ subjectKey }) => subjectKey).sort(), name).toEqual(
      rows.map(sessionKey).sort(),
    );
  }
}

const CASES = 40;
const SEEDS = CASES;

describe('the Attention screen reads as the legacy screen does, over generated payloads', () => {
  it(`agrees on ${String(SEEDS)} seeds, collapsed and expanded, with and without the terminal raise`, async () => {
    const failures: string[] = [];
    let controls = 0;
    let hiddenRows = 0;
    let boardRows = 0;
    for (let seed = 1; seed <= SEEDS; seed += 1) {
      const payload = genPayload(seed, { wellFormed: true });
      const arms: [readonly string[], string][] = [
        [[], ''],
        [['needs', 'close', 'next'], 'abcdef'],
      ];
      for (const [expanded, capability] of arms) {
        const old = legacySummary(payload, expanded, capability);
        const board = withoutCodexRecordedStops(payload) as object;
        const mine = await reactSummary(board, expanded, capability);
        selectedQueues(mine, board);
        const existing = new Set(
          old.sections.flatMap((section) => section.items.map(({ subjectKey }) => subjectKey)),
        );
        const labels = new Map<string, Record<string, unknown>[]>();
        for (const row of payload['sessions'] as Record<string, unknown>[]) {
          const label = String(row['project'] ?? '');
          if (label.trim()) labels.set(label, [...(labels.get(label) ?? []), row]);
        }
        const restored = new Set(
          [...labels.values()]
            .filter((rows) => rows.length > 1)
            .flatMap((rows) => rows.map(sessionKey).filter((key) => !existing.has(key))),
        );
        const left = JSON.stringify(
          unchangedView(
            { ...old, heading: old.heading.replace(/^Attention/, 'Needs you') },
            restored,
          ),
        );
        const right = JSON.stringify(unchangedView(mine, restored));
        if (left !== right && !DEVIATIONS.some((d) => d.seed === seed)) {
          failures.push(
            `seed ${String(seed)} (${expanded.length ? 'expanded' : 'collapsed'}, capability ${capability || 'none'}): ${firstDifference(left, right)}`,
          );
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

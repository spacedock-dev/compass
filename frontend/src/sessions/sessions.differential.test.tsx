import { disclosureReadings, normalizeDisclosures } from '../../test/disclosures';
import { describe, expect, it } from 'vitest';
import { genPayload } from '../observed/generate.test.helper';
import { loadLegacyViews } from '../observed/legacy.test.helper';
import { mountShell } from '../shell/testing';
import { retractSessionCopies } from '../../test/sessionCopyDeviation';
import { projectRecordedRowOpener } from '../../test/recordedCommandOpener';
import { maskRevisionWords } from '../../test/revisionWordDeviation';

/* The Sessions screen, held to the legacy page by what a reader can read. The legacy `nextSessionsView`
   runs unchanged over a generated payload and this screen renders the same payload in the real shell;
   both are reduced to the same shape (each group, each row in order, its text, its route, its tone) and
   compared. A difference is a bug here unless it is named in DEVIATIONS with its reason.

   Two things are outside the comparison on purpose, both because a later step owns them: the capacity strip
   that follows the groups, and the note this screen adds above them when a harness's store could not be
   read (the legacy page says nothing there). */

const legacy = loadLegacyViews();

interface RowSummary {
  readonly harness: string;
  readonly sid: string;
  readonly history: boolean;
  readonly tone: string;
  readonly href: string | null;
  readonly aria: string | null;
  readonly text: string;
  readonly copyLabels: readonly (string | null)[];
}

interface Summary {
  readonly header: string;
  readonly fleet: readonly (readonly [string, string])[];
  readonly groups: readonly {
    readonly kind: string;
    readonly header: string;
    readonly disclosures: ReturnType<typeof disclosureReadings>;
    readonly empty: string | null;
    readonly rows: readonly RowSummary[];
  }[];
}

const norm = (node: Element | null): string =>
  node ? (node.textContent ?? '').replace(/\s+/g, ' ').trim() : '';

function summarize(source: Element | DocumentFragment): Summary {
  const root = normalizeDisclosures(source);
  return {
    header: (() => {
      const header = root.querySelector('.next-operations-header');
      const howto = [...(header?.querySelectorAll('details') ?? [])].find(
        (node) => node.querySelector('summary')?.textContent === 'How Intent and drift works',
      );
      if (howto) {
        const bodies = [...howto.querySelectorAll('.next-why-body')];
        howto.replaceWith(...bodies);
      }
      return norm(header);
    })(),
    fleet: [...root.querySelectorAll('[data-next-fleet-fact]')].map(
      (node) => [(node as HTMLElement).dataset['nextFleetFact'] ?? '', norm(node)] as const,
    ),
    groups: [...root.querySelectorAll('[data-next-operation-group]')].map((group) => ({
      kind: (group as HTMLElement).dataset['nextOperationGroup'] ?? '',
      header: norm(group.querySelector(':scope > header')),
      disclosures: disclosureReadings(group),
      empty: group.querySelector('.next-sessions-empty')
        ? norm(group.querySelector('.next-sessions-empty'))
        : null,
      rows: [...group.querySelectorAll('article.next-operation-row')].map((row) => {
        const route = row.querySelector('a.next-operation-route');
        const data = (row as HTMLElement).dataset;
        return {
          harness: data['nextHarness'] ?? '',
          sid: data['nextSession'] ?? '',
          history: data['nextOperationHistory'] === 'true',
          tone: [...row.classList].find((name) => name.startsWith('next-operation-row--')) ?? '',
          href: route?.getAttribute('href') ?? null,
          aria: route?.getAttribute('aria-label') ?? null,
          text: norm(row),
          copyLabels: [...row.querySelectorAll('button')].map((button) =>
            button.getAttribute('aria-label'),
          ),
        };
      }),
    })),
  };
}

function legacySummary(payload: unknown, raw?: (html: string) => void): Summary {
  const template = document.createElement('template');
  template.innerHTML = legacy.sessionsHtml(payload);
  projectRecordedRowOpener(template.content, payload);
  raw?.(template.innerHTML);
  retractSessionCopies(template.content);
  const header = template.content.querySelector('.next-operations-header');
  header?.querySelector(':scope > span')?.remove();
  header?.querySelectorAll('summary').forEach((node) => node.remove());
  const data = payload as Record<string, unknown>;
  const routes = data['reading_routes'];
  const canAnalyze =
    data['annotate'] === true &&
    !data['annotate_unreadable'] &&
    routes &&
    typeof routes === 'object' &&
    Object.values(routes).some((route) => route && typeof route === 'object' && route['provider']);
  const unchecked = header?.querySelector(':scope > p');
  const orientation = document.createElement('p');
  orientation.textContent = canAnalyze
    ? 'Open a session, set its goal and press Analyze drift to see how far it moved from it.' +
      (unchecked ? ` ${unchecked.textContent}` : '')
    : 'Open a session to see what it is doing and where it stands.';
  unchecked?.remove();
  header?.querySelector('h1')?.after(orientation);
  template.content
    .querySelectorAll('[data-next-fleet-fact="requests"],[data-next-fleet-fact="reported-blocks"]')
    .forEach((node) => node.remove());
  template.content.querySelectorAll('.next-operation-assignment').forEach((node) => {
    node.textContent = node.textContent?.replace(/^ASSIGNMENT · /, 'Current task · ') ?? '';
  });
  /* Deviation (2026-10-20, docs/design-frontend-migration.md#sessions-session-detail-the-timeline-and-the-terminal):
     ACTIVE NOW counts the cards listed under Active now, recorded drift included. The legacy count left drift
     out, so it read 0 above a listed drift card. */
  const counted = template.content.querySelectorAll(
    '[data-next-operation-group="active"] article.next-operation-row',
  ).length;
  const active = template.content.querySelector('[data-next-fleet-fact="active"] strong');
  if (active) active.textContent = String(counted);
  /* Deviation (2026-10-20, docs/design-frontend-migration.md#held-to-recorded-answers): each row leads with
     one state word in place of the SESSION label, NOW · <state> and the QUIET or ENDED tag, and WHERE is the
     project label alone, without "Exact location not published". The state word is compared in
     SessionsView.test; here the legacy row is read as the page now words the rest. */
  template.content
    .querySelectorAll('.next-operation-identity > .next-operation-local-label')
    .forEach((node) => node.remove());
  template.content.querySelectorAll('[data-next-operation-fact="now"] > small').forEach((node) => {
    node.textContent = 'NOW';
  });
  template.content.querySelectorAll('.next-operation-state').forEach((node) => {
    node.textContent = '';
  });
  template.content.querySelectorAll('[data-next-operation-fact="where"]').forEach((node) => {
    const project = node.querySelector('em')?.textContent ?? '';
    node.innerHTML = '';
    const label = document.createElement('small');
    label.textContent = 'PROJECT';
    const value = document.createElement('strong');
    value.textContent = project;
    node.append(label, value);
  });
  return summarize(template.content);
}

async function reactSummary(payload: unknown): Promise<Summary> {
  const page = mountShell({ hash: '#n=sessions', data: payload, strict: false });
  await page.settle();
  const root = page.container.querySelector('[data-next-view-body="sessions"]');
  if (!root) throw new Error('The Sessions screen did not draw.');
  const states = [...root.querySelectorAll('[data-next-row-state]')].map(norm);
  const levels = [...root.querySelectorAll('[data-next-row-drift-level]')].map(norm);
  const drawn = summarize(root);
  page.unmount();
  /* The departures above: the state word is not in the legacy row, and the drift chip's level is a word the
     legacy chip never had (SessionsView.test holds both). */
  const result: Summary = {
    ...drawn,
    groups: drawn.groups.map((group) => ({
      ...group,
      rows: group.rows.map((row) => {
        let text = row.text;
        const state = states.find((word) => text.startsWith(word));
        if (state) text = text.slice(state.length).trimStart();
        for (const level of levels) text = text.replace(level, 'Drift');
        return { ...row, text };
      }),
    })),
  };
  return result;
}

/* The header explanations now share the how-to and two counters live on Attention.
   Their words and every row fact still compare; the first-step controls are asserted in SessionsView.test. */
const DEVIATIONS: readonly {
  readonly seed: number;
  readonly path: string;
  readonly reason: string;
}[] = [];

describe('the Sessions screen reads as the legacy screen does, over generated payloads', () => {
  const CASES = 60;
  const SEEDS = CASES;
  it(`agrees on ${String(SEEDS)} seeds, group by group and row by row`, async () => {
    const failures: string[] = [];
    for (let seed = 1; seed <= SEEDS; seed += 1) {
      const payload = genPayload(seed, { wellFormed: true });
      const old = legacySummary(payload);
      const mine = await reactSummary(payload);
      for (const [index, group] of old.groups.entries()) {
        const other = mine.groups[index];
        if (
          JSON.stringify(group.rows.map((row) => [row.harness, row.sid, row.history])) !==
          JSON.stringify(other?.rows.map((row) => [row.harness, row.sid, row.history]))
        ) {
          failures.push(`seed ${String(seed)} ${group.kind}: membership or order differs`);
        }
      }
      if (
        maskRevisionWords(JSON.stringify(old)) !== maskRevisionWords(JSON.stringify(mine)) &&
        !DEVIATIONS.some((d) => d.seed === seed)
      ) {
        const left = JSON.stringify(old);
        const right = JSON.stringify(mine);
        let at = 0;
        while (left[at] === right[at]) at += 1;
        failures.push(
          `seed ${String(seed)}: differs near ${JSON.stringify(left.slice(Math.max(0, at - 90), at + 160))} vs ${JSON.stringify(right.slice(Math.max(0, at - 90), at + 160))}`,
        );
      }
      if (failures.length >= 3) break;
    }
    expect(failures).toEqual([]);
  }, 120_000);

  it('reaches both groups, ended rows, held requests, drift marks and shared labels, so agreement means something', async () => {
    const seen = {
      active: 0,
      history: 0,
      ended: 0,
      asked: 0,
      drift: 0,
      shared: 0,
      goalTyped: 0,
      annotationsOff: 0,
    };
    for (let seed = 1; seed <= SEEDS; seed += 1) {
      let html = '';
      const text = JSON.stringify(
        legacySummary(genPayload(seed, { wellFormed: true }), (drawn) => {
          html = drawn;
        }),
      );
      seen.active += (text.match(/"kind":"active"/g) ?? []).length;
      seen.history += (text.match(/"kind":"history"/g) ?? []).length;
      seen.ended += (html.match(/NOW · ENDED/g) ?? []).length;
      seen.asked += (text.match(/BLOCKED · /g) ?? []).length;
      seen.drift += (text.match(/Drift · /g) ?? []).length;
      seen.shared += (text.match(/share this display label/g) ?? []).length;
      seen.goalTyped += (text.match(/GOAL · YOUR WORDS|GOAL · FROM YOUR PROMPT/g) ?? []).length;
      seen.annotationsOff += (text.match(/Annotations off/g) ?? []).length;
    }
    for (const [name, count] of Object.entries(seen)) expect(count, name).toBeGreaterThan(5);
  });
});

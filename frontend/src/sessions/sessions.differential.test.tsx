import { restateRecordedLocationNotes } from '../../test/location_departure';
import { disclosureReadings, normalizeDisclosures } from '../../test/disclosures';
import { withoutCodexRecordedStops } from '../../test/codexRecordedStop';
import { describe, expect, it } from 'vitest';
import { payloadSessionRows, sessionKey } from '../observed';
import { genPayload } from '../observed/generate.test.helper';
import { loadLegacyViews } from '../observed/legacy.test.helper';
import { mountShell } from '../shell/testing';
import { retractSessionCopies } from '../../test/sessionCopyDeviation';
import { projectRecordedRowOpener } from '../../test/recordedCommandOpener';
import { maskRevisionWords } from '../../test/revisionWordDeviation';
import { maskSessionRowPresentation } from '../../test/sessionRowDeviation';
import { attentionSelectionFor } from '../attention/select';

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

const DEVIATIONS = {
  // 2026-11-22, docs/design-frontend-migration.md#held-to-recorded-answers
  rowPresentation: maskSessionRowPresentation,
  // 2026-11-22, docs/design-frontend-migration.md#held-to-recorded-answers
  liveMarks: (root: DocumentFragment) => {
    for (const mark of root.querySelectorAll('.next-operation-live-glyph'))
      if (mark.textContent?.trim() === '●') mark.remove();
  },
  // 2026-11-22, docs/design-frontend-migration.md#held-to-recorded-answers
  outcomeMarks: (root: DocumentFragment) => {
    for (const outcome of root.querySelectorAll('.next-operation-outcome')) {
      const lead = outcome.firstChild;
      if (lead?.nodeType === Node.TEXT_NODE)
        lead.textContent = lead.textContent?.replace(/^\s*[△✓◦]\s*/, '') ?? '';
    }
  },
};

// The list heading and group counts have a separate story. Keep the recorded history-window comparison.
function maskGroupHeader(group: Element): string {
  return group.getAttribute('data-next-operation-group') === 'active'
    ? ''
    : norm(group.querySelector(':scope > header h2'));
}

function summarize(source: Element | DocumentFragment): Summary {
  restateRecordedLocationNotes(source);
  // The flag has its own reason and membership proofs.
  source.querySelectorAll('[data-next-row-worth-a-look]').forEach((flag) => flag.remove());
  const root = normalizeDisclosures(source);
  return {
    // The old heading and fleet counters were retired. The new summary has its own story and count tests.
    groups: [...root.querySelectorAll('[data-next-operation-group]')].map((group) => ({
      kind: (group as HTMLElement).dataset['nextOperationGroup'] ?? '',
      header: maskGroupHeader(group),
      disclosures: disclosureReadings(group),
      empty: group.querySelector('.next-sessions-empty')
        ? norm(group.querySelector('.next-sessions-empty'))
        : null,
      rows: [...group.querySelectorAll('article.next-operation-row')].map((row) => {
        const route = row.querySelector('a.next-operation-route');
        const data = (row as HTMLElement).dataset;
        const now = row.querySelector('[data-next-operation-fact="now"]');
        for (const value of now?.querySelectorAll('strong, em') ?? []) {
          // The recorded page used compact units only in these generated Now labels.
          if (/^(?:last active|run finished|ended) /.test(value.textContent ?? '')) {
            value.textContent =
              value.textContent?.replace(
                / ([\d]+[smhd](?: \d+[mh])?|\d+ (?:seconds?|minutes?|hours?|days?)(?: \d+ (?:minutes?|hours?))?) ago$/,
                ' <duration> ago',
              ) ?? '';
          }
        }
        const caution = row.querySelector('[data-next-operation-fact="blocked"] em');
        if (
          caution?.textContent ===
          'Unconfirmed: no positive observation in 5m; prompt may still be standing'
        ) {
          caution.textContent =
            'Unconfirmed: no positive observation in 5 minutes; prompt may still be standing';
        }
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
  restateRecordedLocationNotes(template.content);
  retractSessionCopies(template.content);
  DEVIATIONS.outcomeMarks(template.content);
  // A flagged dirty end moved from Now to the flag. Keep all other recorded outcomes in the comparison.
  const selection = attentionSelectionFor(payload as object);
  const moved = new Set(
    [...(selection?.worthALook.keys() ?? [])]
      .filter((session) => session.outcomeIcon === 'worth-a-look')
      .map(sessionKey),
  );
  for (const row of template.content.querySelectorAll<HTMLElement>('article[data-next-session]')) {
    if (
      !moved.has(
        sessionKey({ harness: row.dataset['nextHarness'], sid: row.dataset['nextSession'] }),
      )
    )
      continue;
    for (const outcome of row.querySelectorAll('.next-operation-outcome--bad')) {
      if (outcome.firstChild?.textContent?.trim() === 'Session ended with uncommitted work')
        outcome.remove();
    }
  }
  DEVIATIONS.liveMarks(template.content);
  DEVIATIONS.rowPresentation(template.content, true);
  const history = template.content.querySelector('[data-next-operation-group="history"] > header');
  history?.querySelectorAll('details').forEach((node) => node.remove());
  const data = payload as Record<string, unknown>;
  const hours = data['window_hours'];
  const heading = history?.querySelector('h2');
  if (heading) {
    heading.textContent =
      data['show_all'] === true
        ? 'Session history'
        : typeof hours === 'number' && hours > 0
          ? `Earlier in the last ${String(hours)} ${hours === 1 ? 'hour' : 'hours'}`
          : 'Recently active';
  }
  template.content.querySelectorAll('.next-operation-assignment').forEach((node) => {
    node.textContent = node.textContent?.replace(/^ASSIGNMENT · /, 'Current task · ') ?? '';
  });
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
  // The retired page clamped future observations to zero. Project just those recorded ages.
  const generated = data['generated'];
  if (typeof generated === 'number') {
    const sources = new Map(payloadSessionRows(data).map((source) => [sessionKey(source), source]));
    for (const row of template.content.querySelectorAll<HTMLElement>(
      'article.next-operation-row',
    )) {
      const source = sources.get(
        sessionKey({
          harness: row.dataset['nextHarness'],
          sid: row.dataset['nextSession'],
        }),
      );
      const at = source?.['last_activity'];
      const end = source?.['ended_at'];
      const values = row.querySelectorAll('[data-next-operation-fact="now"] :is(strong, em)');
      for (const value of values) {
        if (value.textContent === 'ended 0s ago' && typeof end === 'number' && end > generated) {
          value.remove();
        }
        if (
          value.textContent === 'last active 0s ago' &&
          typeof at === 'number' &&
          at > generated
        ) {
          value.textContent = String(source?.['state_detail'] ?? '').trim()
            ? 'quiet'
            : 'Activity not published';
        }
      }
    }
  }
  return summarize(template.content);
}

async function reactSummary(payload: unknown): Promise<Summary> {
  const page = mountShell({ hash: '#n=sessions', data: payload, strict: false });
  await page.settle();
  const root = page.container.querySelector('[data-next-view-body="sessions"]');
  if (!root) throw new Error('The Sessions screen did not draw.');
  DEVIATIONS.rowPresentation(root);
  root.querySelector('[data-next-operation-group="history"] > [data-explanation]')?.remove();
  for (const text of root.querySelectorAll('[data-next-operation-fact="now"] strong')) {
    if (text.textContent === 'No recent activity') text.textContent = 'quiet';
  }
  const drawn = summarize(root);
  page.unmount();
  return drawn;
}

describe('the Sessions screen reads as the legacy screen does, over generated payloads', () => {
  it('renders status and outcome marks as icons over generated sessions', async () => {
    const payload = genPayload(1, { wellFormed: true });
    const page = mountShell({ hash: '#n=sessions', data: payload, strict: false });
    await page.settle();
    const view = page.container.querySelector('[data-next-view-body="sessions"]');
    expect(view?.querySelectorAll('[data-next-session]').length).toBeGreaterThan(0);
    // Session titles are reader data and can contain any character.
    const rendered = view?.cloneNode(true) as Element;
    rendered.querySelectorAll('.next-operation-route strong').forEach((title) => title.remove());
    expect(rendered.textContent).not.toMatch(/[●○△◦◇✓▸▾▴]/);
    page.unmount();
  });

  const CASES = 60;
  const SEEDS = CASES;
  it(`agrees on ${String(SEEDS)} seeds, group by group and row by row`, async () => {
    const failures: string[] = [];
    for (let seed = 1; seed <= SEEDS; seed += 1) {
      const payload = genPayload(seed, { wellFormed: true });
      const old = legacySummary(payload);
      const mine = await reactSummary(withoutCodexRecordedStops(payload));
      for (const [index, group] of old.groups.entries()) {
        const other = mine.groups[index];
        if (
          JSON.stringify(group.rows.map((row) => [row.harness, row.sid, row.history])) !==
          JSON.stringify(other?.rows.map((row) => [row.harness, row.sid, row.history]))
        ) {
          failures.push(`seed ${String(seed)} ${group.kind}: membership or order differs`);
        }
      }
      if (maskRevisionWords(JSON.stringify(old)) !== maskRevisionWords(JSON.stringify(mine))) {
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
      seen.drift += (html.match(/class="next-operation-drift"/g) ?? []).length;
      seen.shared += (html.match(/sessions share this display label/g) ?? []).length;
      seen.goalTyped += (text.match(/GOAL · YOUR WORDS|GOAL · FROM YOUR PROMPT/g) ?? []).length;
      seen.annotationsOff += (text.match(/Annotations off/g) ?? []).length;
    }
    for (const [name, count] of Object.entries(seen)) expect(count, name).toBeGreaterThan(5);
  });
});

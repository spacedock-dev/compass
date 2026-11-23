import { readFileSync } from 'node:fs';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { ControlsProvider } from '../controls';
import { createShell } from '../shell/createShell';
import { ShellContext } from '../shell/context';
import { createFakeEnvironment } from '../transport/testing';
import { SettingsView } from './SettingsView';

function mount(port?: number, clipboardFails = false) {
  const writeText = vi.fn(async () => {
    if (clipboardFails) throw new Error('Clipboard refused');
  });
  const fetch = vi.fn(
    async (url: string) =>
      new Response(JSON.stringify(url === '/api/health' ? { port } : { limits: [], values: {} })),
  );
  const shell = createShell({
    env: createFakeEnvironment(),
    fetch,
    clipboard: () => ({ writeText }),
  });
  const view = render(
    <ShellContext.Provider value={shell}>
      <ControlsProvider controls={shell.controls}>
        <SettingsView />
      </ControlsProvider>
    </ShellContext.Provider>,
  );
  return {
    fetch,
    writeText,
    close() {
      view.unmount();
      shell.runtime.dispose();
      shell.display.dispose();
    },
  };
}

const open = () => {
  const card = within(screen.getByRole('region', { name: 'Your data' }));
  fireEvent.click(card.getByRole('button', { name: 'Forget everything' }));
  return card;
};

const items = (list: HTMLElement) =>
  within(list)
    .getAllByRole('listitem')
    .map((item) => item.textContent);

describe('Forget everything in Settings', () => {
  it('names each store the terminal command deletes or keeps, including dismissals', async () => {
    const cli = readFileSync('compass/skills/compass/compass_runtime/cli.py', 'utf8');
    const manual = readFileSync('MANUAL.md', 'utf8');
    const forget = cli.slice(cli.indexOf('def _forget_stores'), cli.indexOf('def _forget(config'));
    const contract = [
      ['Observation history', 'history.forget(config)'],
      ['Recorded session ends', 'ends.forget(config)'],
      ['Launcher parent declarations', 'declared_parent_store.forget(config)'],
      ['Stored session summaries', 'summary_store.forget(config)'],
      ['Copied-correction digests', 'copied_corrections.forget(config)'],
      ['Discard records', 'annotation_store.forget(config)'],
      ['Reading permission', 'reading_policy.forget(config)'],
    ];
    for (const [, source] of contract) expect(forget).toContain(source);
    expect(forget).toContain('unexpired spend timestamps remain');
    expect(forget).not.toContain('dismissals.forget(config)');
    const manualRow = manual.match(/^\| `--forget` .*$/m)?.[0];
    expect(manualRow).toContain('the words and group labels you typed');
    expect(manualRow).toContain('compass-typed-presses.json');

    const page = mount(6226);
    try {
      const card = open();
      await card.findByRole('button', { name: 'Copy' });
      expect(items(card.getByRole('list', { name: 'Deletes' }))).toEqual(
        contract.map(([label]) => label),
      );
      expect(items(card.getByRole('list', { name: 'Keeps' }))).toEqual([
        'Typed goals, outcome lines, readings and group labels',
        'Dismissals and read choices (Dismiss and Mark as read)',
        'Unexpired AI spend timestamps',
        'Records of typed commands that have already used AI',
      ]);
      expect(
        card.getByText(
          'AI use stays paused until you choose Resume AI use. Summaries stay off until you turn them on again.',
        ),
      ).toBeVisible();
    } finally {
      page.close();
    }
  });

  it('copies stop then forget for the serving port without making a request or completing a reset', async () => {
    const page = mount(6226);
    try {
      const requested = page.fetch.mock.calls.slice();
      const card = open();
      fireEvent.click(await card.findByRole('button', { name: 'Copy' }));
      expect(await card.findByText('Commands copied.')).toBeVisible();
      expect(page.writeText).toHaveBeenCalledExactlyOnceWith(
        'spacedock-compass --port 6226 --stop\nspacedock-compass --port 6226 --forget',
      );
      expect(page.fetch.mock.calls).toEqual(requested);
      expect(card.queryByRole('button', { name: 'Done' })).toBeNull();
      expect(
        document.querySelector('[role="dialog"], [role="alertdialog"], [aria-modal]'),
      ).toBeNull();
    } finally {
      page.close();
    }
  });

  it('leaves both commands available to select when the clipboard refuses the copy', async () => {
    const page = mount(6226, true);
    try {
      const card = open();
      fireEvent.click(await card.findByRole('button', { name: 'Copy' }));
      expect(
        await card.findByText('Could not copy. Select the commands above to copy them.'),
      ).toBeVisible();
      expect(card.queryByText('Commands copied.')).toBeNull();
      expect(card.getByText('spacedock-compass --port 6226 --forget')).toBeVisible();
    } finally {
      page.close();
    }
  });

  it('withholds commands when the serving port is unavailable', async () => {
    const page = mount();
    try {
      const card = open();
      expect(
        await card.findByText(
          'Compass could not read the dashboard port. Use the port you started it with.',
        ),
      ).toBeVisible();
      expect(card.queryByRole('button', { name: 'Copy' })).toBeNull();
      expect(card.queryByText('Commands copied.')).toBeNull();
    } finally {
      page.close();
    }
  });
});

import { openSelect } from '../../test/select';
import { userEvent } from 'storybook/test';
import { Select, SelectTrigger, SelectContent, SelectItem, SelectValue } from '../ui/select';
import { act, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { REGION_IDS } from './announcer';
import { LOOPBACK_ONLY } from './Notices';
import { BOARD, flush, mountShell } from './testing';

const region = (name: keyof typeof REGION_IDS) =>
  document.getElementById(REGION_IDS[name])?.textContent;

describe('the shell wires the runtime, the announcer and the controls to one another', () => {
  it('says a slow pending control’s start sentence in the polite region, once, and again for the next press', async () => {
    const page = mountShell({ data: BOARD });
    await page.settle();
    const first = page.shell.runtime.pending.start('save:goal', 'Saving', 'Saving the goal.');
    act(() => page.clock.advance(400));
    expect(region('cue')).toBe('Saving the goal.');
    act(() => {
      page.shell.runtime.pending.end('save:goal', first);
    });
    // The guard was forgotten with the entry, so the next press's sentence is spoken, not suppressed.
    act(() => {
      const cue = document.getElementById(REGION_IDS.cue);
      if (cue) cue.textContent = '';
    });
    page.shell.runtime.pending.start('save:goal', 'Saving', 'Saving the goal.');
    act(() => page.clock.advance(400));
    expect(region('cue')).toBe('Saving the goal.');
  });

  it('says nothing for a pending control that answers inside the cue delay', async () => {
    const page = mountShell({ data: BOARD });
    await page.settle();
    const token = page.shell.runtime.pending.start('save:goal', 'Saving', 'Saving the goal.');
    act(() => page.clock.advance(399));
    page.shell.runtime.pending.end('save:goal', token);
    act(() => page.clock.advance(1000));
    expect(region('cue')).toBe('');
  });

  it('sends a copy or raise control’s sentence to its own region and anything else to the guarded cue region', async () => {
    const page = mountShell({ data: BOARD });
    await page.settle();
    act(() => {
      page.shell.controls.announce('copy:id:claude:s#1', 'Copied session ID s');
      page.shell.controls.announce('raise:claude:s#2', 'Raise requested');
      page.shell.controls.announce('briefing:p#3', 'Copied the project briefing');
    });
    expect(region('copy')).toBe('Copied session ID s');
    expect(region('raise')).toBe('Raise requested');
    expect(region('cue')).toBe('Copied the project briefing');
    expect(region('attention')).toBe('');
    expect(region('alert')).toBe('');
  });

  it('offers a terminal raise only when the served document carries the run’s capability', async () => {
    const off = mountShell({ data: BOARD });
    await off.settle();
    expect(off.shell.controls.focus).toBeNull();
    off.unmount();
    const on = mountShell({ data: BOARD, focusCapability: 'abcdef' });
    await on.settle();
    expect(on.shell.controls.focus).not.toBeNull();
    expect(on.posts()).toBe(0);
  });

  it('shows a board only through the display gate, so a paint the runtime asks for is the one the reader sees', async () => {
    const page = mountShell({ data: BOARD });
    expect(page.shell.display.getSnapshot().data).toBeNull();
    await page.settle();
    expect(page.shell.display.getSnapshot().data).not.toBeNull();
    expect(page.shell.display.getSnapshot().acceptedCount).toBe(
      page.shell.runtime.store.getSnapshot().acceptedCount,
    );
  });

  it('starts exactly one runtime and releases it when the page leaves, whatever StrictMode did meanwhile', async () => {
    const page = mountShell({ data: BOARD, strict: true });
    await page.settle();
    expect(page.shell.runtime.store.subscriberCount()).toBeGreaterThan(0);
    page.unmount();
    await act(async () => {
      page.clock.advance(1);
    });
    expect(page.env.openStreams()).toBe(0);
  });
});

describe('a disclosure the reader just toggled holds a background paint for its motion', () => {
  it('keeps the shown board for the 220 ms a disclosure eases, then shows the newest one', async () => {
    const page = mountShell({ data: BOARD });
    await page.settle();
    const shown = () => page.shell.display.getSnapshot().data?.generated;
    expect(shown()).toBe(1000);
    // The shared controls tell the gate through the same call a Disclosure makes on its summary's click.
    page.shell.controls.noteToggle();
    page.backend.data = { ...BOARD, generated: 2000 };
    void page.shell.runtime.refresh();
    await act(async () => void (await flush()));
    expect(page.shell.runtime.store.getSnapshot().data?.generated).toBe(2000);
    expect(shown()).toBe(1000);
    await act(async () => {
      page.clock.advance(219);
      await flush();
    });
    expect(shown()).toBe(1000);
    await act(async () => {
      page.clock.advance(1);
      await flush();
    });
    expect(shown()).toBe(2000);
  });
});

function Choice() {
  return (
    <Select items={{ one: 'One', two: 'Two' }}>
      <SelectTrigger aria-label="Shell choice">
        <SelectValue placeholder="Choose" />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value="one">One</SelectItem>
        <SelectItem value="two">Two</SelectItem>
      </SelectContent>
    </Select>
  );
}

describe('an open list holds a poll paint, and closing it shows the board', () => {
  it('keeps the shown board while a popup from the page is open, then catches up on Escape', async () => {
    const page = mountShell({ data: BOARD });
    await page.settle();
    const slot = document.createElement('div');
    document.getElementById('app')?.append(slot);
    const choice = render(<Choice />, { container: slot });
    const user = userEvent.setup();
    await openSelect(screen.getByRole('combobox'));
    expect(screen.getByRole('combobox').getAttribute('aria-expanded')).toBe('true');
    page.backend.data = { ...BOARD, generated: 2000 };
    await act(async () => {
      await page.shell.runtime.refresh();
    });
    expect(page.shell.runtime.store.getSnapshot().data?.generated).toBe(2000);
    expect(page.shell.display.getSnapshot().data?.generated).toBe(1000);
    await user.keyboard('{Escape}');
    await page.settle();
    expect(page.shell.display.getSnapshot().data?.generated).toBe(2000);
    choice.unmount();
  });

  it('does not hold a poll for a popup outside the page, which cannot be the reader’s choice', async () => {
    const page = mountShell({ data: BOARD });
    await page.settle();
    const choice = render(<Choice />);
    await openSelect(screen.getByRole('combobox'));
    page.backend.data = { ...BOARD, generated: 2000 };
    await act(async () => {
      await page.shell.runtime.refresh();
    });
    expect(page.shell.display.getSnapshot().data?.generated).toBe(2000);
    choice.unmount();
  });
});

describe('an action refused because it needs the computer running Compass', () => {
  const loopbackOnly = () =>
    new Response(
      JSON.stringify({ ok: false, reason: 'loopback-only', message: 'server text, not shown' }),
      { status: 403 },
    );

  it('explains the refusal in fixed words and keeps it through refresh and navigation', async () => {
    const page = mountShell({ data: BOARD, postResponse: loopbackOnly });
    await page.settle();
    expect(screen.queryByText(LOOPBACK_ONLY)).toBeNull();
    await act(async () => {
      await page.shell.runtime.client.postDismiss({ harness: 'claude', sid: 'shared-sid' });
    });
    expect(screen.getByText(LOOPBACK_ONLY)).toBeVisible();
    expect(screen.queryByText('server text, not shown')).toBeNull();
    expect(screen.queryByText(/For an ssh -L tunnel, the local port/)).toBeNull();
    await act(async () => {
      await page.shell.runtime.refresh();
    });
    await page.go('#n=projects');
    expect(screen.getByText(LOOPBACK_ONLY)).toBeVisible();
    expect(page.posts()).toBe(1);
  });

  it('does not explain an unrelated refusal or a different status this way', async () => {
    for (const [status, reason] of [
      [403, 'admission-refused'],
      [503, 'loopback-only'],
    ] as const) {
      const page = mountShell({
        data: BOARD,
        postResponse: () => new Response(JSON.stringify({ reason }), { status }),
      });
      await page.settle();
      await act(async () => {
        await page.shell.runtime.client.postDismiss({ harness: 'claude', sid: 'shared-sid' });
      });
      expect(screen.queryByText(LOOPBACK_ONLY)).toBeNull();
      page.unmount();
    }
  });
});

describe('an action refused through a different-port SSH tunnel', () => {
  it('shows the same-port instruction after the refusal and keeps it through refresh and navigation', async () => {
    const page = mountShell({
      data: BOARD,
      postResponse: () =>
        new Response(
          JSON.stringify({
            ok: false,
            reason: 'tunnel-port-mismatch',
            message: "For an ssh -L tunnel, the local port must match the Compass server's port.",
          }),
          { status: 403 },
        ),
    });
    await page.settle();
    const sentence = "For an ssh -L tunnel, the local port must match the Compass server's port.";
    expect(screen.queryByText(sentence)).toBeNull();
    await act(async () => {
      await page.shell.runtime.client.postDismiss({ harness: 'claude', sid: 'shared-sid' });
    });
    expect(screen.getByText(sentence)).toBeVisible();
    await act(async () => {
      await page.shell.runtime.refresh();
    });
    await page.go('#n=projects');
    expect(screen.getByText(sentence)).toBeVisible();
    expect(page.posts()).toBe(1);
  });

  it('does not diagnose a tunnel from unrelated errors or an untrusted message field', async () => {
    for (const [status, response] of [
      [403, { reason: 'forbidden', message: '<img src=x onerror=alert(1)>' }],
      [503, { reason: 'tunnel-port-mismatch' }],
    ] as const) {
      const page = mountShell({
        data: BOARD,
        postResponse: () => new Response(JSON.stringify(response), { status }),
      });
      await page.settle();
      await act(async () => {
        await page.shell.runtime.client.postDismiss({ harness: 'claude', sid: 'shared-sid' });
      });
      expect(screen.queryByText(/For an ssh -L tunnel/)).toBeNull();
      expect(document.querySelector('img[src="x"]')).toBeNull();
      page.unmount();
    }
  });
});

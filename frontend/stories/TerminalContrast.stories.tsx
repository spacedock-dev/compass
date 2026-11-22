import type { Meta, StoryObj } from '@storybook/react-vite';
import { useEffect, useRef } from 'react';
import { expect, waitFor } from 'storybook/test';
import rendererCss from '../../compass/skills/compass/compass_runtime/web/vendor/xterm.css?raw';
import rendererScript from '../../compass/skills/compass/compass_runtime/web/vendor/xterm.js?raw';
import { createTerminalOwner } from '../src/terminal/owner';
import { FakeSocket } from '../src/terminal/testing';
import type { XtermLike, XtermOptions } from '../src/terminal/xterm';
import { createFakeClock } from '../src/transport/testing';
import { contrastOf, rgbOf } from './a11y.audit';

interface SelectableTerminal extends XtermLike {
  focus(): void;
  blur(): void;
  select(column: number, row: number, length: number): void;
  clearSelection(): void;
}

const identity = { harness: 'claude', sid: 'terminal-contrast' } as const;
const codes = [30, 31, 32, 33, 34, 35, 36, 37, 90, 91, 92, 93, 94, 95, 96, 97];
const swatches = 'ABCDEFGHIJKLMNOP';
const output = codes.map((code, index) => `\x1b[${code}m${swatches[index]}\x1b[0m `).join('');
const terminals = new WeakMap<Element, SelectableTerminal>();

function loadRenderer(): new (options: XtermOptions) => SelectableTerminal {
  const browser = window as unknown as {
    Terminal?: new (options: XtermOptions) => SelectableTerminal;
  };
  if (!browser.Terminal) {
    const script = document.createElement('script');
    // The vendored classic script publishes Terminal. Its source map is not shipped.
    script.textContent = rendererScript.replace(/\n\/\/# sourceMappingURL=.*$/m, '');
    document.head.append(script);
    script.remove();
  }
  if (!browser.Terminal) throw new Error('Vendored xterm did not publish its renderer');
  return browser.Terminal;
}

function TerminalExample() {
  const viewport = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!viewport.current) return;
    const host: HTMLDivElement = viewport.current;
    const owner = createTerminalOwner({
      document,
      clock: createFakeClock(),
      client: {
        getInteractionOrigin: async () => ({
          kind: 'ok',
          status: 200,
          revision: '',
          body: { state: 'registered' },
        }),
      },
      loader: {
        async load() {
          const Renderer = loadRenderer();
          return class extends Renderer {
            constructor(options: XtermOptions) {
              super(options);
              terminals.set(host, this);
            }
          };
        },
      },
      streamUrl: () => '',
      openSocket: () => {
        const socket = new FakeSocket();
        queueMicrotask(() =>
          socket.deliver({ state: 'streamed', sequence: 1, cols: 80, rows: 3, data: output }),
        );
        return socket;
      },
    });
    const key = 'claude:terminal-contrast';
    owner.lookup(identity, 1);
    void Promise.resolve().then(() => {
      owner.open(key);
      owner.attach(host, key);
    });
    return () => {
      owner.dispose();
      terminals.delete(host);
    };
  }, []);
  return (
    <>
      <style>{rendererCss}</style>
      <div data-terminal-contrast ref={viewport} style={{ background: 'var(--sunk)' }} />
    </>
  );
}

const meta = { title: 'Terminal/Contrast', component: TerminalExample } satisfies Meta<
  typeof TerminalExample
>;
export default meta;
type Story = StoryObj<typeof meta>;

export const ANSIAndSelection: Story = {
  play: async ({ canvasElement }) => {
    const host = canvasElement.querySelector('[data-terminal-contrast]');
    if (!host) throw new Error('Expected a terminal viewport');
    const cells = () =>
      [...host.querySelectorAll('.xterm-rows span')].filter((cell) =>
        /[A-P]/.test(cell.textContent),
      );
    await waitFor(() =>
      expect(
        cells()
          .map((cell) => cell.textContent.trim())
          .join(''),
      ).toBe(swatches),
    );
    const terminal = terminals.get(host);
    if (!terminal) throw new Error('Expected a live xterm renderer');
    let surface = cells()[0];
    while (surface && getComputedStyle(surface).backgroundColor === 'rgba(0, 0, 0, 0)') {
      surface = surface.parentElement ?? undefined;
    }
    if (!surface) throw new Error('Expected xterm to have a painted background');
    const ground = rgbOf(getComputedStyle(surface).backgroundColor);
    for (const cell of cells()) {
      await expect(
        contrastOf(rgbOf(getComputedStyle(cell).color), ground),
        `ANSI foreground ${cell.textContent}`,
      ).toBeGreaterThanOrEqual(4.5);
    }
    try {
      terminal.focus();
      terminal.select(0, 0, swatches.length * 2);
      for (const focused of [true, false]) {
        if (!focused) terminal.blur();
        await expect(host.ownerDocument.activeElement === terminal.textarea).toBe(focused);
        const state = focused ? 'focused' : 'blurred';
        await waitFor(async () => {
          const selection = host.querySelector('.xterm-selection div');
          if (!selection) throw new Error('Expected xterm to paint the selection');
          const background = rgbOf(getComputedStyle(selection).backgroundColor);
          await expect(
            contrastOf(background, ground),
            `${state} selection cue`,
          ).toBeGreaterThanOrEqual(3);
          await expect(
            cells()
              .map((cell) => cell.textContent)
              .join('')
              .replaceAll(' ', ''),
          ).toBe(swatches);
          for (const cell of cells()) {
            await expect(
              contrastOf(rgbOf(getComputedStyle(cell).color), background),
              `${state} selected text ${cell.textContent}`,
            ).toBeGreaterThanOrEqual(4.5);
          }
        });
      }
    } finally {
      terminal.clearSelection();
      await waitFor(() => expect(host.querySelector('.xterm-selection div')).toBeNull());
    }
  },
};

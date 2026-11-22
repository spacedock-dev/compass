import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect } from 'storybook/test';
import { auditCalm } from './calm.audit';

const meta = { title: 'Accessibility/First-layer audit' } satisfies Meta;
export default meta;
type Story = StoryObj<typeof meta>;

export const DetectsRegressions: Story = {
  render: () => (
    <section aria-label="Audit example">
      <p>A session title</p>
      <p>Reading finished</p>
      <p>Current activity</p>
      <p>Recorded at 1795327749000</p>
      <p>Entry 1f4b8cd9</p>
      <p>Entry deadbeef</p>
      <p>Supported by [3]</p>
      <p data-authored>Preserve 1795327749000 and 1f4b8cd9</p>
      <div data-layer="technical">
        <code>1795327749000 1f4b8cd9 [3]</code>
      </div>
      <p hidden>Hidden data 1795327749000</p>
      <input aria-label="Weak search border" style={{ border: '1px solid #7b8794' }} />
      <input aria-label="Strong search border" style={{ border: '1px solid #7b8794' }} />
    </section>
  ),
  play: async ({ canvas, canvasElement }) => {
    const styles = [
      [canvas.getByText('A session title'), { fontFamily: 'ui-monospace, monospace' }],
      [canvas.getByText('Reading finished'), { textTransform: 'uppercase' }],
      [canvas.getByText('Current activity'), { letterSpacing: '0.1em' }],
      [canvas.getByLabelText('Weak search border'), { border: '1px solid #ddd' }],
    ] as const;
    for (const [element, style] of styles) Object.assign(element.style, style);
    await expect(auditCalm(canvasElement)).toEqual([
      expect.stringMatching(/monospace.*A session title/),
      expect.stringMatching(/uppercase.*Reading finished/),
      expect.stringMatching(/letter-spacing.*Current activity/),
      expect.stringMatching(/epoch.*Recorded at 1795327749000/),
      expect.stringMatching(/hex.*Entry 1f4b8cd9/),
      expect.stringMatching(/hex.*Entry deadbeef/),
      expect.stringMatching(/citation.*Supported by \[3\]/),
      expect.stringMatching(/3:1.*Weak search border/),
    ]);
    for (const [element] of styles) element.removeAttribute('style');
    canvas.getByLabelText('Weak search border').style.border = '1px solid #7b8794';
    for (const text of [
      'Recorded at 1795327749000',
      'Entry 1f4b8cd9',
      'Entry deadbeef',
      'Supported by [3]',
    ]) {
      canvas.getByText(text).hidden = true;
    }
    await expect(auditCalm(canvasElement)).toEqual([]);
  },
};

export const PaintedBorder: Story = {
  render: () => (
    <section style={{ backgroundColor: '#aaa', padding: '10px' }}>
      <input
        aria-label="Border over fill"
        style={{ border: '4px solid rgb(0 0 0 / 50%)', backgroundColor: '#fff' }}
      />
      <input
        aria-label="Border outside fill"
        style={{
          border: '4px solid rgb(0 0 0 / 50%)',
          backgroundColor: '#fff',
          backgroundClip: 'padding-box',
        }}
      />
    </section>
  ),
  play: async ({ canvasElement }) => {
    const control = canvasElement.querySelector<HTMLInputElement>('input');
    try {
      expect(auditCalm(canvasElement)).toEqual([
        'control border 1.72:1 < 3:1 on input "Border over fill"',
      ]);
    } finally {
      control?.style.setProperty('background-clip', 'padding-box');
    }
  },
};

export const VisibleTextKeepsItsOrigin: Story = {
  render: () => (
    <section>
      <p>Source [{3}]</p>
      <p>
        With <span>source [</span>
        <b>4</b>]
      </p>
      <p>SESSION SUMMARY</p>
      <p>AI and ID</p>
      <p>KB</p>
      <p>
        Source [<span data-authored>5</span>]
      </p>
      <p>
        <span data-authored>DEADBEEF [6]</span> Source [7]
      </p>
      <p
        data-authored
        style={{
          fontFamily: 'ui-monospace, monospace',
          textTransform: 'uppercase',
          letterSpacing: '.12em',
        }}
      >
        Run 1795327749000 [8]
      </p>
      <style>{'.calm-placeholder::placeholder { font-family: ui-monospace, monospace; }'}</style>
      <input className="calm-placeholder" placeholder="Find a session" style={{ border: '0' }} />
      <input
        className="calm-placeholder"
        placeholder="Filled search"
        defaultValue="Query"
        style={{ border: '0' }}
      />
      <p hidden>HIDDEN LABEL [9]</p>
    </section>
  ),
  play: async ({ canvasElement }) => {
    try {
      expect(auditCalm(canvasElement)).toEqual([
        expect.stringMatching(/citation.*Source \[3\]/),
        expect.stringMatching(/citation.*With source \[4\]/),
        expect.stringMatching(/all-capital.*SESSION SUMMARY/),
        expect.stringMatching(/citation.*Source \[7\]/),
        expect.stringMatching(/monospace.*Run 1795327749000/),
        expect.stringMatching(/uppercase.*Run 1795327749000/),
        expect.stringMatching(/letter-spacing.*Run 1795327749000/),
        expect.stringMatching(/monospace.*Find a session/),
      ]);
    } finally {
      const fixture = canvasElement.querySelector('section');
      if (fixture) fixture.hidden = true;
    }
  },
};

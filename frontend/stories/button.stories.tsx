import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, userEvent, within } from 'storybook/test';
import { useState } from 'react';
import { Button } from '../src/ui/button';
import { contrastOf, rgbOf } from './a11y.audit';
import { settledRect } from './settled-layout';
const meta = { title: 'UI/Button', component: Button } satisfies Meta<typeof Button>;
export default meta;
type Story = StoryObj<typeof meta>;

const emphasis = {
  primary: ['rgb(47, 125, 91)', 'rgb(47, 125, 91)', 'rgb(255, 255, 255)'],
  secondary: ['rgb(255, 255, 255)', 'rgb(123, 135, 148)', 'rgb(31, 41, 51)'],
  quiet: ['rgba(0, 0, 0, 0)', 'rgba(0, 0, 0, 0)', 'rgb(47, 125, 91)'],
  danger: ['rgb(255, 255, 255)', 'rgb(154, 52, 18)', 'rgb(154, 52, 18)'],
  'danger-solid': ['rgb(154, 52, 18)', 'rgb(154, 52, 18)', 'rgb(255, 255, 255)'],
} as const;

function emphasisStory(kind: keyof typeof emphasis, label: string): Story {
  return {
    args: { emphasis: kind, children: label },
    render: (args) => (
      <>
        <div style={{ background: 'var(--panel)', padding: 8 }}>
          <Button {...args} />
        </div>
        <div style={{ background: 'var(--bg)', padding: 8 }}>
          <Button {...args} />
        </div>
      </>
    ),
    play: async ({ canvasElement }) => {
      const [backgroundColor, borderColor, color] = emphasis[kind];
      for (const button of within(canvasElement).getAllByRole('button', { name: label })) {
        await expect(button).toHaveStyle({ backgroundColor, borderColor, color });
        const { height, width } = button.getBoundingClientRect();
        await expect(height).toBeGreaterThanOrEqual(44);
        await expect(width).toBeGreaterThanOrEqual(44);
        const style = getComputedStyle(button);
        const surface = getComputedStyle(button.parentElement as HTMLElement).backgroundColor;
        const fill = kind === 'quiet' ? surface : style.backgroundColor;
        await expect(contrastOf(rgbOf(style.color), rgbOf(fill))).toBeGreaterThanOrEqual(4.5);
        if (kind === 'secondary' || kind === 'danger') {
          await expect(style.borderTopWidth).toBe('1px');
          await expect(style.borderTopStyle).toBe('solid');
          await expect(
            contrastOf(rgbOf(style.borderTopColor), rgbOf(surface)),
          ).toBeGreaterThanOrEqual(3);
        }
      }
    },
  };
}

/* The canvas `.btn` (owner, 2026-11-24): the 12 px control radius, a 600-weight 15 px label, 18 px either side and
   8 px between a glyph and its words, in every weight. */
export const CanvasButtonShape: Story = {
  render: () => (
    <>
      <Button emphasis="primary">Check progress</Button>
      <Button emphasis="secondary">Edit goal</Button>
      <Button>Undo changes</Button>
      <Button variant="primary">Save</Button>
    </>
  ),
  play: async ({ canvasElement }) => {
    for (const button of within(canvasElement).getAllByRole('button')) {
      const style = getComputedStyle(button);
      await expect(style.borderTopLeftRadius).toBe('12px');
      await expect(style.fontWeight).toBe('600');
      await expect(style.fontSize).toBe('15px');
      await expect(style.paddingInlineStart).toBe('18px');
      await expect(style.columnGap).toBe('8px');
      await expect(button.getBoundingClientRect().height).toBeGreaterThanOrEqual(44);
    }
  },
};

export const PrimaryEmphasis = emphasisStory('primary', 'Check progress');
export const Secondary = emphasisStory('secondary', 'Edit goal');
export const QuietEmphasis = emphasisStory('quiet', 'Not now');
export const Danger = emphasisStory('danger', 'Remove item');
export const DangerSolid = emphasisStory('danger-solid', 'Delete item');

export const DefaultModifiers: Story = {
  render: () => (
    <>
      <Button tone="muted">Save draft</Button>
      <Button size="consent">Allow</Button>
      <Button strongBorder>Strong border</Button>
      <Button accentBorder>Accent border</Button>
    </>
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole('button', { name: 'Save draft' })).toHaveStyle({
      color: 'rgb(82, 96, 109)',
    });
    await expect(canvas.getByRole('button', { name: 'Allow' })).toHaveStyle({
      paddingBlockStart: '6px',
      paddingBlockEnd: '6px',
    });
    await expect(canvas.getByRole('button', { name: 'Strong border' })).toHaveStyle({
      borderWidth: '2px',
    });
    await expect(canvas.getByRole('button', { name: 'Accent border' })).toHaveStyle({
      borderColor: 'rgb(47, 125, 91)',
    });
  },
};

export const UnavailableEmphasis: Story = {
  render: () => (
    <>
      <Button emphasis="primary" disabled>
        Check progress
      </Button>
      <Button emphasis="quiet" aria-disabled>
        Clear filters
      </Button>
    </>
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const native = canvas.getByRole('button', { name: 'Check progress' });
    const focusable = canvas.getByRole('button', { name: 'Clear filters' });
    await expect(native).toBeDisabled();
    await expect(focusable).toHaveAttribute('aria-disabled', 'true');
    /* Calm, not hatched (owner, 2026-11-24): the muted fill, a solid outline and muted ink, still a button. */
    for (const button of [native, focusable]) {
      const style = getComputedStyle(button);
      await expect(style.backgroundImage).toBe('none');
      await expect(style.borderTopStyle).toBe('solid');
      await expect(style.borderTopColor).toBe('rgb(123, 135, 148)');
      await expect(style.backgroundColor).toBe('rgb(238, 241, 244)');
      await expect(style.color).toBe('rgb(92, 105, 118)');
      await expect(contrastOf(rgbOf(style.color), rgbOf(style.backgroundColor))).toBeGreaterThan(
        4.5,
      );
      await expect(
        contrastOf(rgbOf(style.borderTopColor), rgbOf(style.backgroundColor)),
      ).toBeGreaterThan(3);
    }
    focusable.focus();
    await expect(focusable).toHaveFocus();
  },
};

function SessionActionsExample() {
  const [steering, setSteering] = useState(false);
  return (
    <section aria-label="Session actions">
      <p>
        <Button emphasis="primary">Check progress again</Button> Uses AI
      </p>
      <p>
        <Button
          emphasis="secondary"
          aria-expanded={steering}
          onClick={() => setSteering(!steering)}
        >
          Steer back
        </Button>{' '}
        <Button emphasis="quiet">Update my goal instead</Button>{' '}
        <Button emphasis="quiet">This reading looks wrong</Button>
      </p>
      {steering && <Button emphasis="secondary">Copy message</Button>}
    </section>
  );
}

export const SessionActions: Story = {
  render: () => <SessionActionsExample />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole('button', { name: 'Steer back' }));
    await expect(canvas.getByText('Uses AI')).toBeVisible();
    const filled = canvas
      .getAllByRole('button')
      .filter((button) => getComputedStyle(button).backgroundColor === 'rgb(47, 125, 91)');
    await expect(filled).toEqual([canvas.getByRole('button', { name: 'Check progress again' })]);
    await expect(canvas.getByRole('button', { name: 'Copy message' })).toBeVisible();
  },
};
export const Default: Story = {
  args: { variant: 'default', children: 'Button default' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const node = canvas.getByRole('button', { name: args.children as string });
    await expect(node).toBeVisible();
    await expect(node.getBoundingClientRect().height).toBeGreaterThanOrEqual(44);
    await userEvent.hover(node);
    node.focus();
    await expect(node).toHaveFocus();
  },
};
export const Retry: Story = {
  args: { variant: 'retry', children: 'Button retry' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const node = canvas.getByRole('button', { name: args.children as string });
    await expect(node).toBeVisible();
    await expect(node.getBoundingClientRect().height).toBeGreaterThanOrEqual(44);
    await userEvent.hover(node);
    node.focus();
    await expect(node).toHaveFocus();
  },
};
export const Answer: Story = {
  args: { variant: 'answer', children: 'Button answer' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const node = canvas.getByRole('button', { name: args.children as string });
    await expect(node).toBeVisible();
    await expect(node.getBoundingClientRect().height).toBeGreaterThanOrEqual(44);
    await userEvent.hover(node);
    node.focus();
    await expect(node).toHaveFocus();
  },
};
export const Primary: Story = {
  args: { variant: 'primary', children: 'Check progress' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const node = canvas.getByRole('button', { name: args.children as string });
    await expect(node).toBeVisible();
    await expect(node).toHaveStyle({
      backgroundColor: 'rgb(47, 125, 91)',
      color: 'rgb(255, 255, 255)',
    });
    await expect(node.getBoundingClientRect().height).toBeGreaterThanOrEqual(44);
    await userEvent.hover(node);
    node.focus();
    await expect(node).toHaveFocus();
  },
};
export const Quiet: Story = {
  args: { variant: 'quiet', children: 'Button quiet' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const node = canvas.getByRole('button', { name: args.children as string });
    await expect(node).toBeVisible();
    await expect(node.getBoundingClientRect().height).toBeGreaterThanOrEqual(44);
    await userEvent.hover(node);
    node.focus();
    await expect(node).toHaveFocus();
  },
};
export const Bare: Story = {
  args: { variant: 'bare', children: 'Button bare' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const node = canvas.getByRole('button', { name: args.children as string });
    await expect(node).toBeVisible();
    await expect(node.getBoundingClientRect().height).toBeGreaterThanOrEqual(44);
    await userEvent.hover(node);
    node.focus();
    await expect(node).toHaveFocus();
  },
};
export const Window: Story = {
  args: { variant: 'window', children: 'Button window' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const node = canvas.getByRole('button', { name: args.children as string });
    await expect(node).toBeVisible();
    await expect(node.getBoundingClientRect().height).toBeGreaterThanOrEqual(44);
    await userEvent.hover(node);
    node.focus();
    await expect(node).toHaveFocus();
  },
};
export const Menu: Story = {
  args: { variant: 'menu', children: 'Button menu' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const node = canvas.getByRole('button', { name: args.children as string });
    await expect(node).toBeVisible();
    await expect(node.getBoundingClientRect().height).toBeGreaterThanOrEqual(44);
    await userEvent.hover(node);
    node.focus();
    await expect(node).toHaveFocus();
  },
};
export const ContextAdd: Story = {
  args: { variant: 'context-add', children: 'Button context-add' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const node = canvas.getByRole('button', { name: args.children as string });
    await expect(node).toBeVisible();
    await expect(node.getBoundingClientRect().height).toBeGreaterThanOrEqual(44);
    await userEvent.hover(node);
    node.focus();
    await expect(node).toHaveFocus();
  },
};
export const Native: Story = {
  args: { variant: 'native', children: 'Button native' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const node = canvas.getByRole('button', { name: args.children as string });
    await expect(node).toBeVisible();
    await expect(node.getBoundingClientRect().height).toBeGreaterThanOrEqual(44);
    await userEvent.hover(node);
    node.focus();
    await expect(node).toHaveFocus();
  },
};
export const FilterChip: Story = {
  args: {
    variant: 'filter-chip',
    'aria-label': 'Remove Project: compass',
    children: 'Project: compass',
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const node = canvas.getByRole('button', { name: 'Remove Project: compass' });
    await expect(node).toBeVisible();
    await expect(node).toHaveTextContent('Project: compass');
    await expect(node.getBoundingClientRect().height).toBeGreaterThanOrEqual(44);
    node.focus();
    await expect(node).toHaveFocus();
  },
};
export const Copy: Story = {
  args: { variant: 'copy', children: 'Button copy' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const node = canvas.getByRole('button', { name: args.children as string });
    await expect(node).toBeVisible();
    await expect(node.getBoundingClientRect().height).toBeGreaterThanOrEqual(44);
    await userEvent.hover(node);
    node.focus();
    await expect(node).toHaveFocus();
  },
};
export const Raise: Story = {
  args: { variant: 'raise', children: 'Button raise' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const node = canvas.getByRole('button', { name: args.children as string });
    await expect(node).toBeVisible();
    await expect(node.getBoundingClientRect().height).toBeGreaterThanOrEqual(44);
    await userEvent.hover(node);
    node.focus();
    await expect(node).toHaveFocus();
  },
};
export const RaisePrimary: Story = {
  args: { variant: 'raise-primary', children: 'Button raise-primary' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const node = canvas.getByRole('button', { name: args.children as string });
    await expect(node).toBeVisible();
    await expect(node).toHaveStyle({
      backgroundColor: 'rgb(47, 125, 91)',
      color: 'rgb(255, 255, 255)',
    });
    await expect(node.getBoundingClientRect().height).toBeGreaterThanOrEqual(44);
    await userEvent.hover(node);
    node.focus();
    await expect(node).toHaveFocus();
  },
};
export const Terminal: Story = {
  args: { variant: 'terminal', children: 'Button terminal' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const node = canvas.getByRole('button', { name: args.children as string });
    await expect(node).toBeVisible();
    await expect(node.getBoundingClientRect().height).toBeGreaterThanOrEqual(44);
    await userEvent.hover(node);
    node.focus();
    await expect(node).toHaveFocus();
  },
};
export const Disabled: Story = {
  args: { disabled: true, children: 'Unavailable action' },
  play: async ({ canvasElement }) => {
    await expect(
      within(canvasElement).getByRole('button', { name: 'Unavailable action' }),
    ).toBeDisabled();
  },
};
export const Long: Story = {
  args: { children: 'Save the long intent that explains every expected outcome to the reader' },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole('button')).toBeVisible();
  },
};
export const Pending: Story = {
  render: () => <PendingExample />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const button = canvas.getByRole('button', { name: 'Save' });
    const { width } = await settledRect(button);
    await userEvent.click(button);
    await expect(button).toHaveAccessibleName('Saving…');
    await expect(button).toHaveAttribute('aria-busy', 'true');
    await expect(button).toHaveAttribute('aria-disabled', 'true');
    await expect(button).toHaveStyle({
      backgroundColor: 'rgb(47, 125, 91)',
      color: 'rgb(255, 255, 255)',
    });
    await expect(button).toHaveFocus();
    await expect((await settledRect(button)).width).toBe(width);
    await userEvent.keyboard('{Enter} ');
    await userEvent.click(button);
    await expect(canvas.getByRole('status')).toHaveTextContent('1 request');
  },
};
function PendingExample() {
  const [requests, setRequests] = useState(0);
  return (
    <>
      <Button
        variant="primary"
        reserve="Saving the intent…"
        busyLabel="Saving…"
        aria-busy={requests > 0}
        onClick={() => setRequests(requests + 1)}
      >
        Save
      </Button>
      <output role="status">{requests} request</output>
    </>
  );
}
export const CopyCopied: Story = {
  args: { variant: 'copy', 'data-copy-state': 'copied', children: 'copied' } as NonNullable<
    Story['args']
  >,
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole('button', { name: 'copied' })).toBeVisible();
  },
};
export const CopyFailed: Story = {
  args: { variant: 'copy', 'data-copy-state': 'failed', children: 'failed' } as NonNullable<
    Story['args']
  >,
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole('button', { name: 'failed' })).toBeVisible();
  },
};
export const RaiseSending: Story = {
  render: () => (
    <Button variant="raise" data-raise-state="sending" aria-busy={true}>
      RAISE sending
    </Button>
  ),
  play: async ({ canvasElement }) => {
    await expect(
      within(canvasElement).getByRole('button', { name: 'RAISE sending' }),
    ).toBeVisible();
  },
};
export const RaiseSent: Story = {
  render: () => (
    <Button variant="raise" data-raise-state="sent" aria-busy={false}>
      RAISE sent
    </Button>
  ),
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole('button', { name: 'RAISE sent' })).toBeVisible();
  },
};
export const RaiseDeclined: Story = {
  render: () => (
    <Button variant="raise" data-raise-state="declined" aria-busy={false}>
      RAISE declined
    </Button>
  ),
  play: async ({ canvasElement }) => {
    await expect(
      within(canvasElement).getByRole('button', { name: 'RAISE declined' }),
    ).toBeVisible();
  },
};
export const PrimaryRaiseDeclined: Story = {
  render: () => (
    <Button variant="raise-primary" data-raise-state="declined">
      RAISE declined
    </Button>
  ),
  play: async ({ canvasElement }) => {
    const button = within(canvasElement).getByRole('button', { name: 'RAISE declined' });
    await expect(button).toHaveStyle({
      backgroundColor: 'rgb(238, 241, 244)',
      color: 'rgb(82, 96, 109)',
    });
  },
};
export const RaiseFailed: Story = {
  render: () => (
    <Button variant="raise" data-raise-state="failed" aria-busy={false}>
      RAISE failed
    </Button>
  ),
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole('button', { name: 'RAISE failed' })).toBeVisible();
  },
};
export const RaiseThrottled: Story = {
  render: () => (
    <Button variant="raise" data-raise-state="throttled" aria-busy={false}>
      RAISE throttled
    </Button>
  ),
  play: async ({ canvasElement }) => {
    await expect(
      within(canvasElement).getByRole('button', { name: 'RAISE throttled' }),
    ).toBeVisible();
  },
};
export const RaiseStale: Story = {
  render: () => (
    <Button variant="raise" data-raise-state="stale" aria-busy={false}>
      RAISE stale
    </Button>
  ),
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole('button', { name: 'RAISE stale' })).toBeVisible();
  },
};
export const Muted: Story = {
  args: { tone: 'muted', children: 'Muted' },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole('button', { name: 'Muted' })).toBeVisible();
  },
};
export const Consent: Story = {
  args: { size: 'consent', children: 'Consent' },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole('button', { name: 'Consent' })).toBeVisible();
  },
};
export const AccentBorder: Story = {
  args: { accentBorder: true, children: 'AccentBorder' },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole('button', { name: 'AccentBorder' })).toBeVisible();
  },
};
export const StrongBorder: Story = {
  args: { strongBorder: true, children: 'StrongBorder' },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole('button', { name: 'StrongBorder' })).toBeVisible();
  },
};
export const RetryUnavailable: Story = {
  args: { variant: 'retry', 'aria-disabled': true, children: 'RetryUnavailable' },
  play: async ({ canvasElement }) => {
    await expect(
      within(canvasElement).getByRole('button', { name: 'RetryUnavailable' }),
    ).toBeVisible();
  },
};

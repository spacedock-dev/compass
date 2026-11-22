import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, userEvent, within } from 'storybook/test';
import { useState } from 'react';
import { createApiClient } from '../src/api/client';
import { ControlsProvider } from '../src/controls/ControlsProvider';
import { RaiseControl } from '../src/controls/RaiseControl';
import { testControls } from '../src/controls/testControls';

const restart = 'Raise refused: the dashboard restarted. Reload the page.';
const tunnel = "For an ssh -L tunnel, the local port must match the Compass server's port.";
const admission =
  'Compass refused this request: board actions require direct loopback access from the same origin.';

function RefusedRaise({
  reason,
  message,
  primary = false,
}: {
  readonly reason: string;
  readonly message: string;
  readonly primary?: boolean;
}) {
  const [kit] = useState(() => {
    const client = createApiClient({
      fetch: async () => new Response(JSON.stringify({ reason, message }), { status: 403 }),
    });
    return testControls({
      focus: (identity) => client.focus({ identity, capability: 'synthetic' }),
    });
  });
  return (
    <ControlsProvider controls={kit.controls}>
      <RaiseControl harness="claude" sid="refused" focusable primary={primary} />
    </ControlsProvider>
  );
}
const meta = { title: 'Controls/Raise refusal', component: RefusedRaise } satisfies Meta<
  typeof RefusedRaise
>;
export default meta;
type Story = StoryObj<typeof meta>;

const check =
  (sentence: string, stale = false): NonNullable<Story['play']> =>
  async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const button = canvas.getByRole('button', {
      name: 'Raise the terminal this session is running in',
    });
    await userEvent.click(button);
    await expect(button).toHaveAccessibleDescription(sentence);
    await expect(button).toHaveAttribute('data-raise-state', stale ? 'stale' : 'refused');
    if (!stale) {
      const cue = canvas.getByText(sentence);
      await expect(cue).toBeVisible();
      await expect(getComputedStyle(cue).clipPath).toBe('none');
      await expect(cue.getBoundingClientRect().height).toBeGreaterThan(10);
      await expect(cue.getBoundingClientRect().width).toBeGreaterThan(100);
      await expect(canvas.queryByText(restart)).toBeNull();
    }
  };
export const TunnelPortRefusal: Story = {
  args: { reason: 'tunnel-port-mismatch', message: tunnel },
  play: check(tunnel),
};
export const AdmissionRefusal: Story = {
  args: { reason: 'admission-refused', message: admission },
  play: check(admission),
};
export const RestartedDashboard: Story = {
  args: { reason: 'stale-capability', message: restart },
  play: check(restart, true),
};

export const PrimaryAdmissionRefusal: Story = {
  args: { reason: 'admission-refused', message: admission, primary: true },
  play: async (context) => {
    await check(admission)(context);
    const button = within(context.canvasElement).getByRole('button');
    await expect(getComputedStyle(button).borderColor).toBe('rgb(146, 64, 14)');
    await expect(getComputedStyle(button).color).toBe('rgb(82, 96, 109)');
  },
};

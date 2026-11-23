import { useState } from 'react';
import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, userEvent, waitFor, within } from 'storybook/test';
import { UpdateNotice } from '../src/shell/UpdateNotice';
import { ControlsProvider } from '../src/controls';
import { testControls } from '../src/controls/testControls';
import { SettingsScreen } from '../src/settings/SettingsView';
import { createLegacyStorage } from '../src/storage';
import { createApiClient } from '../src/api/client';
import { fakeBackend } from '../test/storage_backends';
import { Button } from '../src/ui/button';

function NoticeExample() {
  const [fake] = useState(fakeBackend);
  const [storage] = useState(() => createLegacyStorage(() => fake));
  const [version, setVersion] = useState('2.9.0');
  const [revision, setRevision] = useState(0);
  return (
    <>
      <UpdateNotice key={revision} storage={storage} update={{ version, checked_at: revision }} />
      <Button onClick={() => setRevision((value) => value + 1)}>Refresh and remount</Button>
      <Button onClick={() => setVersion('2.10.0')}>Next release</Button>
    </>
  );
}

function SettingsExample() {
  const [kit] = useState(testControls);
  const [revision, setRevision] = useState(0);
  const [client] = useState(() => {
    let disabled = false;
    return createApiClient({
      fetch: async (_url, init) => {
        if (init?.method === 'POST') {
          const body = JSON.parse(String(init.body)) as { values: { no_update_check: boolean } };
          disabled = body.values.no_update_check;
        }
        return new Response(
          JSON.stringify({
            values: {},
            limits: [],
            update_check: {
              disabled,
              default_enabled: true,
              cli_disabled: false,
            },
          }),
          { status: 200 },
        );
      },
    });
  });
  return (
    <>
      <ControlsProvider controls={kit.controls}>
        <SettingsScreen key={revision} client={client} />
      </ControlsProvider>
      <Button onClick={() => setRevision((value) => value + 1)}>Reopen settings</Button>
    </>
  );
}

const meta = { title: 'Shell/Update check' } satisfies Meta;
export default meta;
type Story = StoryObj<typeof meta>;

export const DismissesOneRelease: Story = {
  render: () => <NoticeExample />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const banner = within(canvas.getByRole('status', { name: 'Compass update' }));
    await expect(banner.getByText('Compass 2.9.0 is available')).toBeVisible();
    await expect(banner.getByRole('link', { name: 'View release' })).toBeVisible();
    await expect(canvas.getByRole('status', { name: 'Compass update' })).toHaveStyle({
      backgroundColor: 'rgb(230, 242, 236)',
    });
    await userEvent.click(canvas.getByRole('button', { name: 'Dismiss update notice' }));
    await expect(canvas.queryByText('Compass 2.9.0 is available')).toBeNull();
    await userEvent.click(canvas.getByRole('button', { name: 'Refresh and remount' }));
    await expect(canvas.queryByText('Compass 2.9.0 is available')).toBeNull();
    await userEvent.click(canvas.getByRole('button', { name: 'Next release' }));
    await expect(canvas.getByText('Compass 2.10.0 is available')).toBeVisible();
  },
};

export const SavesTheOffSwitch: Story = {
  render: () => <SettingsExample />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const name = 'Look for new versions once a day';
    const switchInForce = () => canvas.getByRole('switch', { name });
    const control = await canvas.findByRole('switch', { name });
    await expect(control).toBeChecked();
    await expect(canvas.getByText('Asks spacedock.md at most once a day.')).toBeVisible();
    await userEvent.click(control);
    await waitFor(() => expect(control).not.toBeChecked());
    await expect(canvas.getByText('Update checks are off.')).toBeVisible();
    await userEvent.click(canvas.getByRole('button', { name: 'Reopen settings' }));
    await expect(await canvas.findByRole('switch', { name })).not.toBeChecked();
    await expect(canvas.getByText('Update checks are off.')).toBeVisible();
    await userEvent.click(switchInForce());
    await waitFor(() => expect(switchInForce()).toBeChecked());
    await expect(canvas.queryByText('Update checks are off.')).toBeNull();
  },
};

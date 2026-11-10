import { useState } from 'react';
import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, userEvent, waitFor, within } from 'storybook/test';
import { UpdateNotice } from '../src/shell/UpdateNotice';
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
      <SettingsScreen key={revision} client={client} />
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
    await expect(canvas.getByText('Compass 2.9.0 is available')).toBeVisible();
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
    const checkbox = await canvas.findByRole('checkbox', { name: 'Turn off daily update checks' });
    await expect(checkbox).not.toBeChecked();
    await expect(canvas.queryByText('Update checks are off by default in this build.')).toBeNull();
    await userEvent.click(checkbox);
    await waitFor(() => expect(checkbox).toBeChecked());
    await userEvent.click(canvas.getByRole('button', { name: 'Reopen settings' }));
    await expect(
      await canvas.findByRole('checkbox', { name: 'Turn off daily update checks' }),
    ).toBeChecked();
    await userEvent.click(canvas.getByRole('checkbox', { name: 'Turn off daily update checks' }));
    await waitFor(() =>
      expect(
        canvas.getByRole('checkbox', { name: 'Turn off daily update checks' }),
      ).not.toBeChecked(),
    );
  },
};

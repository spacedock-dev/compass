import type { Meta, StoryObj } from '@storybook/react-vite';
import { useState } from 'react';
import { expect, userEvent, waitFor, within } from 'storybook/test';
import { ControlsProvider } from '../src/controls/ControlsProvider';
import { TechnicalDetails } from '../src/controls/TechnicalDetails';
import { testControls } from '../src/controls/testControls';

const meta = { title: 'Controls/Technical details' } satisfies Meta;
export default meta;
type Story = StoryObj<typeof meta>;

function Example() {
  const [kit] = useState(() => testControls());
  const [revision, setRevision] = useState(0);
  return (
    <ControlsProvider controls={kit.controls}>
      <TechnicalDetails
        key={revision}
        disclosureKey="project:technical-details"
        tabs={[
          { id: 'activity', label: 'Activity log', content: <p>Recorded activity</p> },
          { id: 'reports', label: 'Reports', content: <p>Project reports</p> },
        ]}
      />
      <button type="button" onClick={() => setRevision((value) => value + 1)}>
        Remount project details
      </button>
    </ControlsProvider>
  );
}

export const ProjectDetails: Story = {
  render: () => <Example />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const show = () => canvas.getByRole('button', { name: 'Show technical details' });
    const hide = () => canvas.getByRole('button', { name: 'Hide technical details' });
    await expect(show()).toHaveAttribute('aria-expanded', 'false');
    await userEvent.click(show());
    const activity = canvas.getByRole('tab', { name: 'Activity log', selected: true });
    activity.focus();
    await userEvent.keyboard('{ArrowRight}');
    const reports = canvas.getByRole('tab', { name: 'Reports', selected: true });
    await expect(reports).toHaveFocus();
    const panel = canvas.getByRole('tabpanel', { name: 'Reports' });
    await expect(reports).toHaveAttribute('aria-controls', panel.id);
    await expect(panel).toHaveAttribute('aria-labelledby', reports.id);
    await expect(panel).toHaveTextContent('Project reports');
    await userEvent.click(canvas.getByRole('button', { name: 'Remount project details' }));
    await expect(hide()).toHaveAttribute('aria-expanded', 'true');
    await expect(canvas.getByRole('tabpanel', { name: 'Reports' })).toBeVisible();
    await userEvent.click(hide());
    await expect(show()).toHaveAttribute('aria-expanded', 'false');
    await userEvent.click(canvas.getByRole('button', { name: 'Remount project details' }));
    await expect(show()).toHaveAttribute('aria-expanded', 'false');
    await userEvent.click(show());
    await waitFor(() =>
      expect(canvas.getByRole('tab', { name: 'Reports', selected: true })).toBeVisible(),
    );
  },
};

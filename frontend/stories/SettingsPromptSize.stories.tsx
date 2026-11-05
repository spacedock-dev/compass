import type { Meta, StoryObj } from '@storybook/react-vite';
import { useState } from 'react';
import { expect, userEvent, waitFor, within } from 'storybook/test';
import { createApiClient } from '../src/api/client';
import { SettingsScreen } from '../src/settings/SettingsView';
import { Button } from '../src/ui/button';

const LIMIT = {
  key: 'analyze_prompt_bytes',
  default: 524288,
  minimum: 16384,
  maximum: 2097152,
};
const ESTIMATE = {
  kind: 'capacity-preview',
  policy: 'analyze-context-v1',
  maximum_prompt_bytes: 524288,
  window_tokens: null,
  window_source: 'unknown',
  generation_reserve_tokens: 128000,
  cli_reserve_tokens: 16384,
  estimated_system_tokens: 0,
  estimate_method: 'legacy-byte-cap',
  fit_verified: false,
  policy_verified: false,
  configuration_reason: '',
  reason: 'estimated',
  can_lower_prompt_setting: true,
};
type Scenario = 'estimated' | 'legacy' | 'malformed' | 'blocked' | 'dynamic' | 'tiny';

function capacities(scenario: Scenario): unknown {
  switch (scenario) {
    case 'estimated':
      return { claude: ESTIMATE, codex: ESTIMATE };
    case 'legacy':
      return undefined;
    case 'malformed':
      return {
        claude: { ...ESTIMATE, fit_verified: true },
        codex: { ...ESTIMATE, kind: 'actual-input', reason: 'private sentinel' },
      };
    case 'blocked':
    case 'dynamic':
      return {
        claude: {
          ...ESTIMATE,
          maximum_prompt_bytes: 0,
          can_lower_prompt_setting: false,
          reason: scenario === 'dynamic' ? 'context-dynamic' : 'context-config',
          configuration_reason: scenario === 'dynamic' ? 'dynamic-policy' : 'context-config',
        },
        codex: null,
      };
    case 'tiny':
      return {
        claude: {
          ...ESTIMATE,
          maximum_prompt_bytes: 1,
          window_tokens: 144443,
          window_source: 'configured',
          estimate_method: 'utf8-bytes-div-3',
          can_lower_prompt_setting: false,
        },
        codex: null,
      };
  }
}

/* A stateful response fixture, not an alternate Settings implementation. Leaving unmounts the real
   screen; reopening reads the stored response again through the real API client. */
function PromptSizeExample({ scenario }: { readonly scenario: Scenario }) {
  const [open, setOpen] = useState(true);
  const [client] = useState(() => {
    let value = scenario === 'estimated' ? LIMIT.default : LIMIT.maximum;
    return createApiClient({
      fetch: async (_url, init) => {
        if (init?.method === 'POST') {
          const body = JSON.parse(String(init.body)) as { values: Record<string, number | null> };
          if (Object.hasOwn(body.values, LIMIT.key))
            value = body.values[LIMIT.key] ?? LIMIT.default;
        }
        return new Response(
          JSON.stringify({
            values: { [LIMIT.key]: value },
            limits: [LIMIT],
            capacities: capacities(scenario),
          }),
          { status: 200 },
        );
      },
    });
  });
  return (
    <div className="flex flex-col gap-4">
      <Button onClick={() => setOpen((current) => !current)}>
        {open ? 'Leave Settings' : 'Open Settings'}
      </Button>
      {open ? <SettingsScreen client={client} /> : <p>Settings closed.</p>}
    </div>
  );
}

const meta = {
  title: 'Views/Settings prompt size',
  component: PromptSizeExample,
  args: { scenario: 'estimated' },
} satisfies Meta<typeof PromptSizeExample>;
export default meta;
type Story = StoryObj<typeof meta>;

const allowance = (canvasElement: HTMLElement) =>
  within(within(canvasElement).getByRole('region', { name: 'Estimated prompt allowances' }));
const prompt = (canvasElement: HTMLElement) =>
  within(canvasElement).findByRole('spinbutton', { name: 'Prompt size (KB)' });

export const AReaderSavesTwoMiBAndReopensTheSamePreference: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const input = await prompt(canvasElement);
    await expect(input).toHaveValue(512);
    await expect(input).toHaveAttribute('min', '16');
    await expect(input).toHaveAttribute('max', '2048');
    await expect(input).toHaveAccessibleDescription(
      expect.stringContaining('Default 512 KB. Allowed 16 to 2,048 KB.'),
    );
    await expect(canvas.getByText(/one Analyze drift prompt/)).toBeVisible();
    await expect(canvas.getByText(/outline.*Summary.*source coverage/)).toBeVisible();
    await expect(allowance(canvasElement).getAllByText(/Estimated allowance: 512 KB/)).toHaveLength(
      2,
    );
    await expect(
      allowance(canvasElement).getAllByText(
        /above this allowance is refused before a model call; it is not automatically shortened/,
      ),
    ).toHaveLength(2);
    await expect(
      allowance(canvasElement).getByText(
        /do not confirm model availability or that a prompt will fit/,
      ),
    ).toBeVisible();
    await userEvent.clear(input);
    await userEvent.type(input, '2048');
    await userEvent.click(canvas.getByRole('button', { name: 'Save' }));
    await expect(
      await canvas.findByText('Saved. The next Analyze drift press reads with these limits.'),
    ).toBeVisible();
    await expect(input).toHaveAccessibleDescription(expect.stringContaining('In force: 2,048 KB.'));
    await userEvent.click(canvas.getByRole('button', { name: 'Leave Settings' }));
    await expect(canvas.queryByRole('spinbutton')).toBeNull();
    await userEvent.click(canvas.getByRole('button', { name: 'Open Settings' }));
    const reopened = await prompt(canvasElement);
    await expect(reopened).toHaveValue(2048);
    await expect(allowance(canvasElement).getAllByText(/Estimated allowance: 512 KB/)).toHaveLength(
      2,
    );
    await expect(
      allowance(canvasElement).getByText(
        /saved limit stays the same when the reading route changes/,
      ),
    ).toBeVisible();
    await userEvent.click(canvas.getByRole('button', { name: 'Restore default (512 KB)' }));
    await waitFor(() => expect(reopened).toHaveValue(512));
  },
};

const unknownAllowance: Story['play'] = async ({ canvasElement }) => {
  const canvas = within(canvasElement);
  const input = await prompt(canvasElement);
  await expect(input).toHaveValue(2048);
  await expect(allowance(canvasElement).getAllByText(/Allowance unknown/)).toHaveLength(2);
  await expect(allowance(canvasElement).queryByText(/Estimated allowance:/)).toBeNull();
  await expect(allowance(canvasElement).queryByText(/before a model call/)).toBeNull();
  await expect(canvas.queryByText(/private sentinel|0 KB/)).toBeNull();
  await userEvent.clear(input);
  await userEvent.type(input, '512');
  await userEvent.click(canvas.getByRole('button', { name: 'Save' }));
  await expect(
    await canvas.findByText('Saved. The next Analyze drift press reads with these limits.'),
  ).toBeVisible();
  await expect(input).toHaveValue(512);
};

export const AReaderCanSaveWithAnOlderServerAndUnknownAllowance: Story = {
  args: { scenario: 'legacy' },
  play: unknownAllowance,
};
export const AReaderSeesUnknownForMalformedEstimates: Story = {
  args: { scenario: 'malformed' },
  play: unknownAllowance,
};

export const AReaderSeesTheConfigurationRefusalWithoutLosingThePreference: Story = {
  args: { scenario: 'blocked' },
  play: async ({ canvasElement }) => {
    await expect(await prompt(canvasElement)).toHaveValue(2048);
    await expect(
      allowance(canvasElement).getByText(/context settings could not be checked/),
    ).toBeVisible();
    await expect(allowance(canvasElement).getByText(/Allowance unknown/)).toBeVisible();
    await expect(allowance(canvasElement).queryByText(/Estimated allowance:|0 KB/)).toBeNull();
  },
};

export const AReaderSeesChangingPolicyAsUnestablished: Story = {
  args: { scenario: 'dynamic' },
  play: async ({ canvasElement }) => {
    await expect(await prompt(canvasElement)).toHaveValue(2048);
    await expect(
      allowance(canvasElement).getByText(
        /policy can change when it starts, so its allowance cannot be established/,
      ),
    ).toBeVisible();
    await expect(allowance(canvasElement).queryByText(/Estimated allowance:|0 KB/)).toBeNull();
  },
};

export const AReaderIsNotToldToSaveAnImpossibleTinyLimit: Story = {
  args: { scenario: 'tiny' },
  play: async ({ canvasElement }) => {
    const input = await prompt(canvasElement);
    await expect(input).toHaveValue(2048);
    await expect(input).toHaveAttribute('min', '16');
    await expect(allowance(canvasElement).getByText(/Estimated allowance: 1 byte/)).toBeVisible();
    await expect(
      allowance(canvasElement).getByText(
        /below the minimum Prompt size setting. A smaller actual prompt may still fit/,
      ),
    ).toBeVisible();
    await expect(allowance(canvasElement).queryByText(/Lower Prompt size|0 KB/)).toBeNull();
  },
};

import type { Meta, StoryObj } from '@storybook/react-vite';
import { useState } from 'react';
import { expect, fireEvent, userEvent, waitFor, within } from 'storybook/test';
import { createApiClient } from '../src/api/client';
import { ControlsProvider } from '../src/controls';
import { testControls } from '../src/controls/testControls';
import { SettingsScreen } from '../src/settings/SettingsView';
import { atPageWidth } from './PageFit';
import { settled } from './a11y.audit';
import { auditCalm } from './calm.audit';
import { settledLayout, settledRect } from './settled-layout';

const LIMITS = [
  { key: 'analyze_prompt_bytes', default: 524288, minimum: 16384, maximum: 2097152 },
  { key: 'analyze_record_events', default: 2000, minimum: 100, maximum: 20000 },
  { key: 'analyze_listed_checks', default: 1000, minimum: 12, maximum: 5000 },
  { key: 'analyze_scan_megabytes', default: 512, minimum: 8, maximum: 1024 },
];
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

const BLOCKS = {
  'context-config': ['context-config', 'The context settings could not be checked.'],
  'context-no-room': ['', 'The current context settings leave no room for a progress check.'],
  'settings-refused': [
    'managed-mcp',
    'Claude Code cannot run a progress check while managed-mcp.json is present.',
  ],
  'context-compaction': [
    'compaction-policy-conflict',
    'Managed settings conflict with keeping compaction off for a progress check.',
  ],
  'context-fallback': [
    'fallback-policy-conflict',
    'Managed settings conflict with keeping automatic model switching off for a progress check.',
  ],
  unavailable: ['', 'No route is selected for progress checks.'],
} as const;
type Block = keyof typeof BLOCKS;

type Scenario =
  | 'recommended'
  | 'changed'
  | 'refused'
  | 'unwritable'
  | 'unreadable'
  | 'loading'
  | 'missing-capacity'
  | 'malformed-capacity'
  | 'blocked'
  | 'dynamic'
  | 'tiny'
  | 'off-stop'
  | 'all-changed';
const posted: unknown[] = [];
let finishPost: (() => void) | undefined;

function answers(scenario: Scenario, codexBytes: number, block: Block) {
  switch (scenario) {
    case 'missing-capacity':
      return undefined;
    case 'malformed-capacity':
      return { claude: { ...ESTIMATE, fit_verified: true }, codex: { reason: 'Private sentinel' } };
    case 'blocked':
    case 'dynamic':
      return {
        claude: {
          ...ESTIMATE,
          maximum_prompt_bytes: 0,
          reason: scenario === 'blocked' ? block : 'context-dynamic',
          configuration_reason: scenario === 'blocked' ? BLOCKS[block][0] : 'dynamic-policy',
          can_lower_prompt_setting: false,
        },
      };
    case 'tiny':
      return { claude: ESTIMATE, codex: { ...ESTIMATE, maximum_prompt_bytes: 1 } };
    default:
      return {
        claude: { ...ESTIMATE, maximum_prompt_bytes: 2097152 },
        codex: { ...ESTIMATE, maximum_prompt_bytes: codexBytes },
      };
  }
}

function PromptSizeExample({
  scenario,
  codexBytes,
  block,
}: {
  readonly scenario: Scenario;
  readonly codexBytes: number;
  readonly block: Block;
}) {
  const [kit] = useState(testControls);
  const [client] = useState(() => {
    posted.length = 0;
    finishPost = undefined;
    const values = Object.fromEntries(LIMITS.map((limit) => [limit.key, limit.default]));
    if (scenario === 'changed') values['analyze_prompt_bytes'] = 1048576;
    if (scenario === 'all-changed')
      for (const limit of LIMITS)
        values[limit.key] = Math.floor((limit.default + limit.maximum) / 2);
    if (scenario === 'off-stop') values['analyze_prompt_bytes'] = 541696;
    return createApiClient({
      fetch: async (_url, init) => {
        if (scenario === 'loading') return new Promise<Response>(() => undefined);
        if (scenario === 'unreadable') return new Response('unreadable settings', { status: 500 });
        if (init?.method === 'POST') {
          const request = JSON.parse(String(init.body)) as {
            values: Record<string, number | null>;
          };
          posted.push(request.values);
          if (scenario === 'refused') {
            await new Promise<void>((resolve) => {
              finishPost = resolve;
            });
            return new Response('', { status: 400 });
          }
          if (scenario === 'unwritable') return new Response('', { status: 503 });
          for (const limit of LIMITS) {
            const value = request.values[limit.key];
            if (value !== undefined) values[limit.key] = value ?? limit.default;
          }
        }
        return Response.json({
          values,
          limits: LIMITS,
          capacities: answers(scenario, codexBytes, block),
        });
      },
    });
  });
  return (
    <ControlsProvider controls={kit.controls}>
      <SettingsScreen client={client} />
    </ControlsProvider>
  );
}

const meta = {
  title: 'Views/Settings prompt size',
  component: PromptSizeExample,
  args: { scenario: 'recommended', codexBytes: 524288, block: 'context-config' },
} satisfies Meta<typeof PromptSizeExample>;
export default meta;
type Story = StoryObj<typeof meta>;

const TITLE = 'How much a progress check reads';
const WARNING = 'The saved prompt size exceeds the Codex estimate of 512 KB.';
const UNKNOWN = 'Capacity unknown. Compass did not receive a usable estimate.';
const REFUSED = 'The server refused the change. The previous setting is still in force.';

async function customize(element: HTMLElement) {
  const region = within(await within(element).findByRole('region', { name: TITLE }));
  const trigger = region.getByRole('button', { name: 'Customize' });
  await userEvent.click(trigger);
  await waitFor(() => expect(region.getByRole('slider', { name: 'Prompt size' })).toBeVisible());
  return region;
}

export const RecommendedLimits: Story = {
  play: async ({ canvasElement }) => {
    const limits = await customize(canvasElement);
    await expect(limits.getByRole('heading', { name: TITLE })).toBeVisible();
    for (const [name, value] of [
      ['Prompt size', '512 KB'],
      ['Messages, tests and builds kept', '2,000'],
      ['Tests, builds and files listed', '1,000'],
      ['Transcript scanned for tests and builds', '524,288 KB'],
    ] as const)
      await expect(limits.getByRole('slider', { name })).toHaveAttribute('aria-valuetext', value);
    await expect(
      limits.getByText('Using the recommended limits. Bigger limits read more but take longer.'),
    ).toBeVisible();
    await expect(limits.getByText('Recommended: 512 KB')).toBeVisible();
    await expect(limits.queryByText('Changed')).toBeNull();
    await expect(limits.queryByText(WARNING)).toBeNull();
    await expect(limits.queryByText(/allowance/i)).toBeNull();
    const done = limits.getByRole('button', { name: 'Done' });
    await userEvent.click(done);
    await expect(done).toHaveAttribute('aria-expanded', 'false');
  },
};

export const ChangedOverCodexCapacity: Story = {
  args: { scenario: 'changed' },
  play: async ({ canvasElement }) => {
    const limits = await customize(canvasElement);
    await expect(limits.getByText(WARNING)).toBeVisible();
    await expect(
      limits.getByText('1 limit changed. Bigger limits read more but take longer.'),
    ).toBeVisible();
    await expect(limits.getByText('Changed')).toBeVisible();
    await expect(limits.queryByText(/Using the recommended limits/)).toBeNull();
    const reset = limits.getByRole('button', { name: 'Reset Prompt size' });
    await expect(reset.querySelector('svg[data-icon="reset"]')).not.toBeNull();
    const box = await settledRect(reset);
    await expect(Math.min(box.height, box.width)).toBeGreaterThanOrEqual(44);
    await userEvent.click(reset);
    await waitFor(() => expect(limits.queryByText(WARNING)).toBeNull());
    await expect(posted).toEqual([{ analyze_prompt_bytes: null }]);
    await expect(limits.getByRole('slider', { name: 'Prompt size' })).toHaveAttribute(
      'aria-valuetext',
      '512 KB',
    );
  },
};

export const ChangedFitsCodexCapacity: Story = {
  args: { scenario: 'changed', codexBytes: 1048576 },
  play: async ({ canvasElement }) => {
    const limits = await customize(canvasElement);
    await expect(limits.getByText('Estimated capacity: 1,024 KB.')).toBeVisible();
    await expect(limits.getByRole('slider', { name: 'Prompt size' })).toHaveAttribute(
      'aria-valuetext',
      '1,024 KB',
    );
    await expect(limits.queryByText(/exceeds the Codex estimate/)).toBeNull();
    await expect(limits.queryByText(UNKNOWN)).toBeNull();
  },
};

export const ARefusedWriteRevertsTheSlider: Story = {
  args: { scenario: 'refused' },
  play: async ({ canvasElement }) => {
    const limits = await customize(canvasElement);
    const slider = limits.getByRole('slider', { name: 'Prompt size' });
    fireEvent.keyDown(slider, { key: 'End' });
    await expect(slider).toHaveAttribute('aria-valuetext', '2,048 KB');
    await expect(posted).toHaveLength(0);
    fireEvent.keyUp(slider, { key: 'End' });
    await waitFor(() => expect(slider).toHaveAttribute('aria-disabled', 'true'));
    await expect(limits.getByText('Saving prompt size…', { exact: true })).toBeVisible();
    await expect(limits.queryByText('Limits saved.')).toBeNull();
    fireEvent.keyUp(slider, { key: 'End' });
    await expect(posted).toEqual([{ analyze_prompt_bytes: 2097152 }]);
    finishPost?.();
    await expect(await limits.findByText(REFUSED)).toBeVisible();
    await expect(limits.queryByText('Saving prompt size…')).toBeNull();
    await expect(slider).toHaveAttribute('aria-valuetext', '512 KB');
    await expect(limits.queryByText('Changed')).toBeNull();
    await expect(limits.queryByText('Limits saved.')).toBeNull();
  },
};

export const AnUnwritableStoreKeepsTheLastAnswer: Story = {
  args: { scenario: 'unwritable' },
  play: async ({ canvasElement }) => {
    const limits = await customize(canvasElement);
    const slider = limits.getByRole('slider', { name: 'Prompt size' });
    slider.focus();
    await userEvent.keyboard('{End}');
    await expect(
      await limits.findByText('The settings could not be written. Try again.'),
    ).toBeVisible();
    await expect(slider).toHaveAttribute('aria-valuetext', '512 KB');
    await expect(limits.queryByText(REFUSED)).toBeNull();
    await expect(limits.queryByText('Limits saved.')).toBeNull();
  },
};

export const ReadingCurrentSettings: Story = {
  args: { scenario: 'loading' },
  play: async ({ canvas }) => {
    await expect(canvas.getByText('Reading the settings in force.')).toBeVisible();
    await expect(
      canvas.queryByText('The prompt limits and update preference could not be read.'),
    ).toBeNull();
    await expect(canvas.queryByRole('region', { name: TITLE })).toBeNull();
  },
};

export const UnreadableSettings: Story = {
  args: { scenario: 'unreadable' },
  play: async ({ canvas }) => {
    await expect(
      await canvas.findByText('The prompt limits and update preference could not be read.'),
    ).toBeVisible();
    await expect(canvas.queryByText('Reading the settings in force.')).toBeNull();
    await expect(canvas.queryByRole('region', { name: TITLE })).toBeNull();
  },
};

const unknown: Story['play'] = async ({ canvasElement }) => {
  const limits = await customize(canvasElement);
  await expect(limits.getAllByText(UNKNOWN)).toHaveLength(2);
  await expect(
    limits.queryByText(/Estimated capacity:|exceeds the Codex estimate|Private sentinel/),
  ).toBeNull();
};
export const MissingCapacity: Story = { args: { scenario: 'missing-capacity' }, play: unknown };
export const MalformedCapacity: Story = { args: { scenario: 'malformed-capacity' }, play: unknown };

function blocked(block: Block): Story {
  return {
    args: { scenario: 'blocked', block },
    play: async ({ canvasElement }) => {
      const limits = await customize(canvasElement);
      const words = BLOCKS[block][1];
      await expect(limits.getByText(words)).toBeVisible();
      await expect(limits.getAllByText(UNKNOWN)).toHaveLength(1);
      await expect(
        limits.queryByText(/Estimated capacity:|The policy can change when it starts/),
      ).toBeNull();
      for (const [, alternative] of Object.values(BLOCKS))
        if (words !== alternative) await expect(limits.queryByText(alternative)).toBeNull();
    },
  };
}

export const BlockedCapacity = blocked('context-config');
export const NoRoomForThePrompt = blocked('context-no-room');
export const ManagedMcpRefusesThePrompt = blocked('settings-refused');
export const CompactionConflictsWithThePrompt = blocked('context-compaction');
export const ModelFallbackConflictsWithThePrompt = blocked('context-fallback');
export const NoProgressCheckRoute = blocked('unavailable');

export const DynamicCapacity: Story = {
  args: { scenario: 'dynamic' },
  play: async ({ canvasElement }) => {
    const limits = await customize(canvasElement);
    await expect(
      limits.getByText(
        'The policy can change when it starts, so Compass cannot estimate the capacity.',
      ),
    ).toBeVisible();
    await expect(limits.getAllByText(UNKNOWN)).toHaveLength(1);
    await expect(
      limits.queryByText(/Estimated capacity:|The context settings could not be checked/),
    ).toBeNull();
  },
};

export const CapacityBelowTheMinimum: Story = {
  args: { scenario: 'tiny' },
  play: async ({ canvasElement }) => {
    const limits = await customize(canvasElement);
    await expect(limits.getByText('Estimated capacity: 0.001 KB.')).toBeVisible();
    await expect(
      limits.getByText(
        'This estimate is below the minimum prompt size. A smaller actual prompt may still fit.',
      ),
    ).toBeVisible();
    await expect(limits.queryByText(UNKNOWN)).toBeNull();
  },
};

export const TheFirstTouchKeepsTheSavedStop: Story = {
  args: { scenario: 'off-stop' },
  play: async ({ canvasElement }) => {
    const limits = await customize(canvasElement);
    const slider = limits.getByRole('slider', { name: 'Prompt size' });
    const thumb = slider.closest('[data-slot="slider-thumb"]');
    if (!thumb) throw new Error('Missing slider thumb');
    const box = await settledRect(thumb);
    const position = { clientX: box.x + box.width / 2, clientY: box.y + box.height / 2 };
    fireEvent.pointerDown(thumb, { ...position, button: 0, buttons: 1 });
    fireEvent.pointerUp(thumb, { ...position, button: 0, buttons: 0 });
    await expect(slider).toHaveAttribute('aria-valuetext', '529 KB');
    await expect(posted).toEqual([]);
  },
};

export const ACancelledTouchDoesNotSave: Story = {
  args: { scenario: 'changed' },
  play: async ({ canvasElement }) => {
    const limits = await customize(canvasElement);
    const slider = limits.getByRole('slider', { name: 'Prompt size' });
    const control = slider.closest('[data-slot="slider-control"]');
    if (!control) throw new Error('Missing slider control');
    const box = await settledRect(control);
    const point = { clientX: box.x + box.width * 0.2, clientY: box.y + box.height / 2 };
    const touches = [new Touch({ identifier: 1, target: control, ...point })];
    fireEvent.pointerDown(control, { ...point, pointerType: 'touch', button: 0, buttons: 1 });
    fireEvent.touchStart(control, { changedTouches: touches });
    await expect(slider).not.toHaveAttribute('aria-valuetext', '1,024 KB');
    fireEvent.pointerCancel(control, { pointerType: 'touch' });
    fireEvent.touchEnd(control, { changedTouches: touches });
    await expect(slider).toHaveAttribute('aria-valuetext', '1,024 KB');
    await expect(posted).toEqual([]);
    await expect(limits.queryByText('Limits saved.')).toBeNull();
    slider.focus();
    await userEvent.keyboard('{End}');
    await expect(await limits.findByText('Limits saved.')).toBeVisible();
    await expect(posted).toEqual([{ analyze_prompt_bytes: 2097152 }]);
  },
};

export const ATouchSavesOnRelease: Story = {
  args: { scenario: 'changed' },
  play: async ({ canvasElement }) => {
    const limits = await customize(canvasElement);
    const slider = limits.getByRole('slider', { name: 'Prompt size' });
    const control = slider.closest('[data-slot="slider-control"]');
    if (!control) throw new Error('Missing slider control');
    const box = await settledRect(control);
    const point = { clientX: box.x + box.width * 0.2, clientY: box.y + box.height / 2 };
    const touches = [new Touch({ identifier: 1, target: control, ...point })];
    fireEvent.pointerDown(control, { ...point, pointerType: 'touch', button: 0, buttons: 1 });
    await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
    fireEvent.touchStart(control, { changedTouches: touches });
    await expect(slider).not.toHaveAttribute('aria-valuetext', '1,024 KB');
    await expect(posted).toEqual([]);
    fireEvent.pointerUp(control, { ...point, pointerType: 'touch', button: 0, buttons: 0 });
    fireEvent.touchEnd(control, { changedTouches: touches });
    await expect(await limits.findByText('Limits saved.')).toBeVisible();
    await expect(posted).toEqual([{ analyze_prompt_bytes: 32768 }]);
    await expect(slider).toHaveAttribute('aria-valuetext', '32 KB');
  },
};

function fit(width: number): Story {
  return {
    args: { scenario: 'all-changed' },
    play: async ({ canvasElement }) => {
      await atPageWidth(width, async () => {
        const limits = await customize(canvasElement);
        await settled();
        await expect(await settledLayout(() => document.documentElement.scrollWidth)).toBe(
          window.innerWidth,
        );
        for (const element of canvasElement.querySelectorAll(
          '[data-settings-limit], [data-slot="slider-control"]',
        )) {
          const box = await settledRect(element);
          await expect(box.left).toBeGreaterThanOrEqual(0);
          await expect(box.right).toBeLessThanOrEqual(window.innerWidth);
        }
        await expect(limits.getByText('16 KB')).toBeVisible();
        await expect(limits.getByText('2,048 KB', { exact: true })).toBeVisible();
        const resets = limits.getAllByRole('button', { name: /^Reset (?!all)/ });
        await expect(resets).toHaveLength(4);
        for (const reset of resets) {
          await expect(reset).toBeVisible();
          const box = await settledRect(reset);
          await expect(Math.min(box.height, box.width)).toBeGreaterThanOrEqual(44);
          await expect(reset.querySelector('svg[data-icon="reset"]')).not.toBeNull();
        }
        await expect(auditCalm(canvasElement)).toEqual([]);
      });
    },
  };
}
export const CustomizeAt390 = fit(390);
export const CustomizeAt375 = fit(375);
export const CustomizeAt320 = fit(320);

import type { Meta, StoryObj } from '@storybook/react-vite';
import { useEffect, useState } from 'react';
import { expect, userEvent, within } from 'storybook/test';
import { ControlsProvider } from '../src/controls/ControlsProvider';
import { HumanContextField } from '../src/controls/HumanContextField';
import { ShellContext } from '../src/shell/context';
import { createShell } from '../src/shell/createShell';
import { ProjectSteer } from '../src/steering/ProjectSteer';
import { Tripwires } from '../src/steering/Tripwires';
import { steeringHeldFor } from '../src/steering/held';
import { createLegacyStorage, guardrailKey, memoKey } from '../src/storage';
import { createFakeClock, createFakeEnvironment } from '../src/transport/testing';
import { fakeBackend, type FakeBackend } from '../test/storage_backends';

const PROJECT = 'alpha/app';
const MEMO_KEY = memoKey(PROJECT, null, 'outcome');
const RULES = Array.from({ length: 50 }, (_, index) => `Tripwire ${String(index + 1)}`);
const exampleBackends = new WeakMap<Element, FakeBackend>();

function backendOf(canvas: HTMLElement): FakeBackend {
  const example = canvas.querySelector('[data-local-notes-example]');
  const backend = example && exampleBackends.get(example);
  if (!backend) throw new Error('Local notes example is not mounted');
  return backend;
}

function LocalNotesExample({
  kind = 'steer',
  full = false,
  initialRules,
}: {
  readonly kind?: 'steer' | 'tripwire' | 'memo';
  readonly full?: boolean;
  readonly initialRules?: readonly string[];
}) {
  const [away, setAway] = useState(false);
  const [{ shell, backend }] = useState(() => {
    const backend = fakeBackend({
      [MEMO_KEY]: 'm'.repeat(500),
      ...(kind === 'tripwire'
        ? { [guardrailKey(PROJECT)]: JSON.stringify(initialRules ?? (full ? RULES : [])) }
        : {}),
    });
    const created = createShell({
      env: createFakeEnvironment({ clock: createFakeClock() }),
      provider: () => backend,
      fetch: async () => {
        throw new Error('Local notes must send nothing');
      },
      events: { addEventListener: () => undefined, removeEventListener: () => undefined },
      search: '',
      doc: null,
      reducedMotion: () => true,
    });
    if (full && kind === 'steer') {
      for (let n = 1; n <= 20; n += 1)
        steeringHeldFor(created).recordSteer(PROJECT, `Note ${String(n)}`);
    }
    return { shell: created, backend };
  });
  useEffect(
    () => () => {
      shell.runtime.dispose();
      shell.display.dispose();
    },
    [shell],
  );
  return (
    <ShellContext value={shell}>
      <ControlsProvider controls={shell.controls}>
        <div
          style={{ maxWidth: 560 }}
          data-local-notes-example
          ref={(node) => {
            if (!node) return;
            exampleBackends.set(node, backend);
            return () => {
              exampleBackends.delete(node);
            };
          }}
        >
          <button type="button" onClick={() => setAway(!away)}>
            {away ? 'Return to panel' : 'Leave panel'}
          </button>
          {away ? null : kind === 'tripwire' ? (
            <Tripwires project={PROJECT} />
          ) : kind === 'memo' ? (
            <>
              <HumanContextField
                memoKey={MEMO_KEY}
                kind="outcome"
                label="OUTCOME"
                placeholder="A local memo"
              />
              <HumanContextField
                memoKey={memoKey(PROJECT, null, 'focus')}
                kind="focus"
                label="FOCUS"
                placeholder="A local focus memo"
              />
            </>
          ) : (
            <ProjectSteer project={PROJECT} />
          )}
        </div>
      </ControlsProvider>
    </ShellContext>
  );
}

const meta = {
  title: 'Steering/Local notes and limits',
  component: LocalNotesExample,
} satisfies Meta<typeof LocalNotesExample>;
export default meta;
type Story = StoryObj<typeof meta>;

async function replace(box: HTMLElement, text: string) {
  await userEvent.click(box);
  if (!(box instanceof HTMLInputElement || box instanceof HTMLTextAreaElement))
    throw new Error('Expected a native editor');
  box.select();
  await userEvent.paste(text);
}

export const TripwireLimitRefuses: Story = {
  args: { kind: 'tripwire', full: true },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole('button', { name: '+ set a tripwire' }));
    const box = canvas.getByRole('textbox');
    await replace(box, 'Keep this draft');
    const backend = backendOf(canvasElement);
    const before = backend.writes.length;
    const refusal = () =>
      canvas
        .getAllByRole('status')
        .find(
          (node) =>
            node.textContent ===
            'You have 50 tripwires on this project. Remove one to add another.',
        );
    await expect(refusal()).toBeUndefined();
    await userEvent.keyboard('{Enter}');
    await expect(refusal()).toBeVisible();
    await userEvent.click(canvas.getByRole('button', { name: 'add ↵' }));
    await expect(
      canvas.getByText('You have 50 tripwires on this project. Remove one to add another.'),
    ).toBeVisible();
    await expect(box).toHaveValue('Keep this draft');
    await expect(
      canvas.getAllByRole('switch').map((row) => row.querySelector('strong')?.textContent),
    ).toEqual(RULES);
    await expect(backend.writes).toHaveLength(before);
    await expect(JSON.parse(backend.data.get(guardrailKey(PROJECT)) ?? '[]')).toEqual(RULES);
    await userEvent.click(canvas.getByRole('button', { name: 'Leave panel' }));
    await userEvent.click(canvas.getByRole('button', { name: 'Return to panel' }));
    await expect(canvas.getByRole('textbox')).toHaveValue('Keep this draft');
    await expect(canvas.getAllByRole('switch')).toHaveLength(50);
    await userEvent.click(canvas.getByRole('button', { name: 'Remove tripwire: Tripwire 1' }));
    await expect(canvas.getAllByRole('switch')).toHaveLength(49);
    await expect(canvas.getByRole('textbox')).toHaveFocus();
    await expect(canvas.getByRole('textbox')).toHaveValue('Keep this draft');
    await userEvent.keyboard('{Enter}');
    await expect(canvas.queryByRole('textbox')).toBeNull();
    await expect(
      canvas.getAllByRole('switch').map((row) => row.querySelector('strong')?.textContent),
    ).toEqual([...RULES.slice(1), 'Keep this draft']);
    await expect(JSON.parse(backend.data.get(guardrailKey(PROJECT)) ?? '[]')).toEqual(
      [...RULES.slice(1), 'Keep this draft'].map((text) => ({ enabled: true, text })),
    );
  },
};

function editorLimit(kind: 'steer' | 'tripwire' | 'memo'): Story {
  return {
    args: { kind },
    play: async ({ canvasElement }) => {
      const canvas = within(canvasElement);
      if (kind === 'tripwire')
        await userEvent.click(await canvas.findByRole('button', { name: '+ set a tripwire' }));
      if (kind === 'memo')
        await userEvent.click(await canvas.findByRole('button', { name: 'Edit OUTCOME' }));
      const box = canvas.getByRole('textbox');
      if (kind === 'memo') await expect(box).toHaveValue('m'.repeat(500));
      await expect(box).not.toHaveAttribute('maxlength');
      await replace(box, '界'.repeat(1500));
      await expect(canvas.queryByText('1500/2000')).toBeNull();
      await replace(box, '界'.repeat(1600));
      await expect(canvas.getByText('1600/2000')).toBeVisible();
      const backend = backendOf(canvasElement);
      const writes = backend.writes.length;
      const saved = backend.data.get(MEMO_KEY);
      const text = '😀'.repeat(2100);
      await replace(box, text);
      await expect(box).toHaveValue(text);
      await expect(box).toHaveAttribute('aria-invalid', 'true');
      await expect(canvas.getByText('2100/2000')).toHaveAttribute('data-over', 'true');
      await expect(canvas.getByText('2100 characters; the limit is 2000.')).toBeVisible();
      const name = kind === 'memo' ? 'Done' : kind === 'tripwire' ? 'add ↵' : 'save draft ⏎';
      await expect(canvas.getByRole('button', { name })).toBeDisabled();
      if (kind === 'memo') {
        await expect(saved).toBe('界'.repeat(1600));
        await expect(backend.writes).toHaveLength(writes);
        await expect(backend.data.get(MEMO_KEY)).toBe(saved);
      }
      if (kind === 'tripwire') await userEvent.keyboard('{Enter}');
      await userEvent.click(canvas.getByRole('button', { name: 'Leave panel' }));
      await userEvent.click(canvas.getByRole('button', { name: 'Return to panel' }));
      const returned = canvas.getByRole('textbox');
      await expect(returned).toHaveValue(text);
      await expect(canvas.getByRole('button', { name })).toBeDisabled();
      await replace(returned, '😀'.repeat(2000));
      await expect(canvas.getByText('2000/2000')).not.toHaveAttribute('data-over');
      await expect(canvas.queryByText('2100 characters; the limit is 2000.')).toBeNull();
      await expect(canvas.getByRole('button', { name })).toBeEnabled();
      await userEvent.click(canvas.getByRole('button', { name }));
      await expect(canvas.getByText('😀'.repeat(2000), { selector: 'strong' })).toBeVisible();
      if (kind === 'steer') await expect(canvas.getByRole('textbox')).toHaveValue('');
    },
  };
}

export const NoteKeepsOverLimitText = editorLimit('steer');
export const TripwireKeepsOverLimitText = editorLimit('tripwire');
export const MemoKeepsOverLimitText = editorLimit('memo');

function concurrentTripwire(action: 'remove' | 'toggle'): Story {
  return {
    args: { kind: 'tripwire', initialRules: ['A', 'B', 'C'] },
    play: async ({ canvasElement }) => {
      const canvas = within(canvasElement);
      await canvas.findByRole('switch', { name: 'B' });
      const backend = backendOf(canvasElement);
      const other = createLegacyStorage(() => backend).guardrails;
      const first = other.rules(PROJECT)[0];
      if (!first) throw new Error('Missing first tripwire');
      other.remove(PROJECT, first);
      await userEvent.click(
        action === 'remove'
          ? canvas.getByRole('button', { name: 'Remove tripwire: B' })
          : canvas.getByRole('switch', { name: 'B' }),
      );
      await expect(canvas.getByRole('switch', { name: 'C' })).toHaveAttribute(
        'aria-checked',
        'true',
      );
      if (action === 'remove') {
        await expect(canvas.queryByRole('switch', { name: 'B' })).toBeNull();
      } else {
        await expect(canvas.getByRole('switch', { name: /B/ })).toHaveAttribute(
          'aria-checked',
          'false',
        );
      }
      await expect(JSON.parse(backend.data.get(guardrailKey(PROJECT)) ?? '[]')).toEqual(
        action === 'remove'
          ? [{ enabled: true, text: 'C' }]
          : [
              { enabled: false, text: 'B' },
              { enabled: true, text: 'C' },
            ],
      );
    },
  };
}

export const RemoveAfterAnotherTabRemovesFirst = concurrentTripwire('remove');
export const ToggleAfterAnotherTabRemovesFirst = concurrentTripwire('toggle');

export const AmbiguousTripwireRefreshes: Story = {
  args: { kind: 'tripwire', initialRules: ['same', 'same', 'C'] },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const buttons = await canvas.findAllByRole('button', { name: 'Remove tripwire: same' });
    const backend = backendOf(canvasElement);
    const other = createLegacyStorage(() => backend).guardrails;
    const first = other.rules(PROJECT)[0];
    const secondButton = buttons[1];
    if (!first || !secondButton) throw new Error('Missing duplicate tripwires');
    other.remove(PROJECT, first);
    const writes = backend.writes.length;
    await userEvent.click(secondButton);
    await expect(canvas.getAllByRole('switch')).toHaveLength(2);
    await expect(canvas.getByText(/Tripwires changed in another tab/)).toBeVisible();
    await expect(backend.writes).toHaveLength(writes);
    await expect(JSON.parse(backend.data.get(guardrailKey(PROJECT)) ?? '[]')).toEqual([
      { enabled: true, text: 'same' },
      { enabled: true, text: 'C' },
    ]);
    await userEvent.click(canvas.getByRole('button', { name: 'Remove tripwire: same' }));
    await expect(canvas.queryByRole('switch', { name: 'same' })).toBeNull();
    await expect(canvas.getByRole('switch', { name: 'C' })).toBeVisible();
  },
};

export const UntouchedMemoReopensLatest: Story = {
  args: { kind: 'memo' },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole('button', { name: 'Edit OUTCOME' }));
    await userEvent.click(canvas.getByRole('button', { name: 'Edit FOCUS' }));
    const backend = backendOf(canvasElement);
    createLegacyStorage(() => backend).memo.write(MEMO_KEY, 'Saved in another tab');
    const writes = backend.writes.length;
    await userEvent.click(canvas.getByRole('button', { name: 'Edit OUTCOME' }));
    await expect(canvas.getByRole('textbox')).toHaveValue('Saved in another tab');
    await userEvent.keyboard('{Escape}');
    await expect(canvas.getByText('Saved in another tab')).toBeVisible();
    await expect(backend.data.get(MEMO_KEY)).toBe('Saved in another tab');
    await expect(backend.writes).toHaveLength(writes);
  },
};

export const MemoEscapeKeepsAnotherTabSave: Story = {
  args: { kind: 'memo' },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole('button', { name: 'Edit OUTCOME' }));
    const box = canvas.getByRole('textbox');
    await replace(box, 'My autosaved words');
    // Commit the edit before Escape removes the box: otherwise user-event fires its own
    // change-on-blur on the detached node inside a nested act, which React reports as a
    // suspension. A harness artifact, not page behaviour.
    box.blur();
    box.focus();
    const backend = backendOf(canvasElement);
    createLegacyStorage(() => backend).memo.write(MEMO_KEY, 'Saved in another tab');
    const writes = backend.writes.length;
    await userEvent.keyboard('{Escape}');
    await expect(canvas.getByText('Saved in another tab')).toBeVisible();
    await expect(backend.data.get(MEMO_KEY)).toBe('Saved in another tab');
    await expect(backend.writes).toHaveLength(writes);
  },
};

export const OlderNotesAreNotKept: Story = {
  args: { kind: 'steer', full: true },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.queryByText('Older notes are not kept.')).toBeNull();
    await replace(canvas.getByRole('textbox'), 'Note 21');
    await userEvent.click(canvas.getByRole('button', { name: 'save draft ⏎' }));
    await expect(canvas.getByText('Older notes are not kept.')).toBeVisible();
    await expect(canvas.queryByText('Note 1')).toBeNull();
    await expect(canvas.getByText('Note 2')).toBeVisible();
    await expect(canvas.getByText('Note 21')).toBeVisible();
    await expect(canvasElement.querySelectorAll('[data-next-steer-receipt]')).toHaveLength(20);
    await userEvent.click(canvas.getByRole('button', { name: 'Leave panel' }));
    await userEvent.click(canvas.getByRole('button', { name: 'Return to panel' }));
    await expect(canvas.getByText('Older notes are not kept.')).toBeVisible();
  },
};

import type { Meta, StoryObj } from '@storybook/react-vite';
import { useEffect, useState } from 'react';
import { expect, userEvent, waitFor, within } from 'storybook/test';
import { ControlsProvider } from '../src/controls';
import { notifyOwnerFor } from '../src/notify';
import { SettingsView } from '../src/settings';
import { ShellContext } from '../src/shell/context';
import { createShell } from '../src/shell/createShell';
import { useBoardRuntime } from '../src/transport/hooks';
import { createFakeClock, createFakeEnvironment } from '../src/transport/testing';
import { fakeBackend } from '../test/storage_backends';
import { atPageWidth } from './PageFit';

const LIMITS = [
  { key: 'analyze_prompt_bytes', default: 524288, minimum: 16384, maximum: 2097152 },
  { key: 'analyze_record_events', default: 2000, minimum: 100, maximum: 20000 },
  { key: 'analyze_listed_checks', default: 1000, minimum: 12, maximum: 5000 },
  { key: 'analyze_scan_megabytes', default: 512, minimum: 8, maximum: 1024 },
];

interface Scenario {
  readonly pause: 'on' | 'paused' | 'unknown' | 'refused';
  readonly summaries: 'on' | 'off' | 'unreadable' | 'daily-cap' | 'refused';
  readonly ci: 'on' | 'off' | 'flag-off' | 'unknown' | 'refused' | 'withheld';
  readonly notifications: 'granted' | 'denied' | 'default' | 'unsupported' | 'native';
  readonly update: 'on' | 'off' | 'flag-off' | 'build-off' | 'unreadable' | 'refused' | 'holds-off';
  readonly usage: 'allowed' | 'declined' | 'unavailable';
  readonly harness: 'claude' | 'codex';
  readonly annotations: boolean;
  readonly port: 'known' | 'missing' | 'loading';
  readonly copy: 'ok' | 'refused';
}

const posted: { readonly url: string; readonly body: unknown }[] = [];
const copied: string[] = [];
let permissionPrompts = 0;
let publishBoard: (state: 'stale' | 'withdrawn') => void;

const summaryDisclosure =
  "Sends to Anthropic through your Claude Code, at most 16 KB at a time: your messages and the agent's replies.";

function SettingsExample(props: Scenario) {
  const [shell] = useState(() => {
    posted.length = 0;
    copied.length = 0;
    permissionPrompts = 0;
    let generation = 0;
    let withdrawn = false;
    let stalled = false;
    let permission = props.notifications === 'native' ? 'granted' : props.notifications;
    let ci = props.ci === 'refused' || props.ci === 'withheld' ? 'on' : props.ci;
    let paused = props.pause === 'paused';
    let summariesOff = props.summaries === 'off';
    let updateOff = props.update === 'off' || props.update === 'holds-off';
    const values = Object.fromEntries(LIMITS.map((limit) => [limit.key, limit.default]));
    const reading = () => ({
      off: paused,
      consent: !paused,
      reason: paused ? 'model-calls-paused' : '',
    });
    const summaries = () => ({
      off: summariesOff,
      consent: !summariesOff && !paused,
      reason: paused
        ? 'model-calls-paused'
        : props.summaries === 'unreadable'
          ? 'store-unavailable'
          : props.summaries === 'daily-cap'
            ? 'daily-cap'
            : summariesOff
              ? 'summaries-off'
              : '',
      disclosure: summaryDisclosure,
    });
    const settings = () => ({
      values,
      limits: LIMITS,
      update_check: {
        disabled: updateOff,
        default_enabled: props.update !== 'build-off',
        cli_disabled: props.update === 'flag-off',
      },
    });

    const backend = fakeBackend();
    const next = createShell({
      env: createFakeEnvironment({ clock: createFakeClock() }),
      provider: () => backend,
      events: { addEventListener: () => undefined, removeEventListener: () => undefined },
      search: '',
      doc: null,
      reducedMotion: () => true,
      clipboard: () => ({
        writeText: async (text) => {
          if (props.copy === 'refused') throw new Error('Clipboard refused');
          copied.push(text);
        },
      }),
      fetch: async (url, init) => {
        if (url === '/api/health' && props.port === 'loading')
          return new Promise<Response>(() => undefined);
        if (url === '/api/health')
          return Response.json(props.port === 'known' ? { port: 6226 } : {});
        if (url.startsWith('/api/data')) {
          if (stalled) return new Response('', { status: 503 });
          generation += 1;
          return Response.json(
            {
              generated: generation,
              sessions: [],
              usage_fetch: props.usage !== 'unavailable',
              browser_lane: true,
              native_notify: props.notifications === 'native' ? 'osascript' : '',
              ...(!withdrawn && props.pause !== 'unknown' ? { summaries: summaries() } : {}),
              ...(!withdrawn && props.annotations && props.pause !== 'unknown'
                ? { reading: reading() }
                : {}),
              ...(!withdrawn && props.annotations && ci !== 'unknown'
                ? {
                    reading_routes: {
                      [props.harness]: {
                        ci_read: ci,
                        words_destination: props.harness === 'codex' ? 'OpenAI' : 'Anthropic',
                      },
                    },
                  }
                : {}),
            },
            { headers: { 'X-Compass-Revision': `7.${generation}` } },
          );
        }
        if (url === '/api/settings' && props.update === 'unreadable')
          return new Response('', { status: 500 });
        if (init?.method !== 'POST')
          return Response.json(url === '/api/settings' ? settings() : {});
        const body = JSON.parse(String(init.body)) as {
          readonly ci_read?: 'on' | 'off';
          readonly consent?: 'on' | 'off';
          readonly values?: Record<string, number | boolean | null>;
        };
        posted.push({ url, body });
        if (url === '/api/reading' && body.ci_read) {
          if (props.ci === 'refused') return new Response('', { status: 503 });
          if (props.ci !== 'withheld') ci = body.ci_read;
          return Response.json({ ok: true, ci_read: ci });
        }
        if (url === '/api/reading' && body.consent) {
          if (props.pause === 'refused') return new Response('', { status: 503 });
          paused = body.consent === 'off';
          return Response.json({ ok: true, reading: reading() });
        }
        if (url === '/api/summary' && body.consent) {
          if (props.summaries === 'refused') return new Response('', { status: 503 });
          summariesOff = body.consent === 'off';
          return Response.json({ ok: true, summaries: summaries() });
        }
        if (url === '/api/settings') {
          if (props.update === 'refused') return new Response('', { status: 503 });
          if (typeof body.values?.['no_update_check'] === 'boolean' && props.update !== 'holds-off')
            updateOff = body.values['no_update_check'];
          return Response.json(settings());
        }
        return Response.json({ ok: true });
      },
    });
    publishBoard = (state) => {
      stalled = state === 'stale';
      withdrawn = state === 'withdrawn';
      void next.runtime.refresh({ manual: true });
    };
    if (props.usage === 'declined') next.runtime.storage.usageConsent.set('declined');
    notifyOwnerFor(next.runtime, {
      host: {
        supported: () => permission !== 'unsupported',
        permission: () => permission,
        request: (done) => {
          permissionPrompts += 1;
          permission = 'granted';
          done();
        },
        create: () => undefined,
      },
    });
    return next;
  });

  useBoardRuntime(shell.runtime);
  useEffect(() => {
    return () => {
      shell.runtime.dispose();
      shell.display.dispose();
    };
  }, [shell]);

  return (
    <ShellContext.Provider value={shell}>
      <ControlsProvider controls={shell.controls}>
        <SettingsView />
      </ControlsProvider>
    </ShellContext.Provider>
  );
}

const meta = {
  title: 'Views/Settings',
  component: SettingsExample,
  args: {
    pause: 'on',
    summaries: 'on',
    ci: 'on',
    notifications: 'default',
    update: 'on',
    usage: 'allowed',
    harness: 'claude',
    annotations: true,
    port: 'known',
    copy: 'ok',
  },
} satisfies Meta<typeof SettingsExample>;
export default meta;
type Story = StoryObj<typeof meta>;

const UPDATE = 'Look for new versions once a day';
const UPDATE_ON = 'Asks spacedock.md at most once a day.';
const UPDATE_OFF = 'Update checks are off.';
const CI = 'Read pull request status';
const CI_ON = 'Uses your GitHub or GitLab login when a progress check names a pull request.';
const CI_OFF = 'Pull request reads are off.';
const CI_FLAG = 'Pull request reads are off for this run (--no-ci-read).';
const SUMMARY_PAUSED = 'Paused while AI use is paused.';
const SUMMARY_ON = 'Summaries are on.';
const SUMMARY_OFF = 'Summaries are off.';
const SUMMARY_UNKNOWN = 'The Summaries setting is unavailable.';
const NOT_ASKED = 'Permission has not been requested in this browser.';
const ALLOWED = 'Allowed in this browser.';
const BLOCKED =
  'Blocked in this browser. To allow notifications, change this site’s permissions in your browser.';
const NOT_SUPPORTED = 'This browser does not support desktop notifications.';

export const SavesChangesWithoutSave: Story = {
  play: async ({ canvas }) => {
    const updates = await canvas.findByRole('switch', { name: UPDATE });
    await expect(updates).toHaveAttribute('aria-checked', 'true');
    for (const name of ['Summaries', 'Pause all AI use', CI])
      await expect(await canvas.findByRole('switch', { name })).toBeVisible();
    await expect(canvas.getByText('Desktop notifications')).toBeVisible();
    await expect(canvas.getByText('Show my AI allowance')).toBeVisible();
    await expect(canvas.getByText(/Kept in this browser/)).toBeVisible();
    await expect(canvas.getByText(/Turn it on in a session’s technical details/)).toBeVisible();
    await expect(canvas.queryByRole('switch', { name: 'Live monitor' })).toBeNull();
    await expect(canvas.queryByRole('button', { name: 'Save' })).toBeNull();
    await expect(canvas.queryByRole('button', { name: 'Restore all defaults' })).toBeNull();
    await expect(canvas.queryByRole('button', { name: 'Show technical details' })).toBeNull();
    await userEvent.click(updates);
    await expect(await canvas.findByText(UPDATE_OFF)).toBeVisible();
    await expect(updates).toHaveAttribute('aria-checked', 'false');
    await expect(canvas.queryByText(UPDATE_ON)).toBeNull();
    await expect(posted).toEqual([
      { url: '/api/settings', body: { values: { no_update_check: true } } },
    ]);
  },
};

export const UpdateChecksOff: Story = {
  args: { update: 'off' },
  play: async ({ canvas }) => {
    const control = await canvas.findByRole('switch', { name: UPDATE });
    await expect(control).toHaveAttribute('aria-checked', 'false');
    await expect(canvas.getByText(UPDATE_OFF)).toBeVisible();
    await expect(canvas.queryByText(UPDATE_ON)).toBeNull();
    await userEvent.click(control);
    await expect(await canvas.findByText(UPDATE_ON)).toBeVisible();
    await expect(control).toHaveAttribute('aria-checked', 'true');
    await expect(posted).toEqual([
      { url: '/api/settings', body: { values: { no_update_check: false } } },
    ]);
  },
};

export const UpdateAnswerTakesPrecedence: Story = {
  args: { update: 'holds-off' },
  play: async ({ canvas }) => {
    const control = await canvas.findByRole('switch', { name: UPDATE });
    await userEvent.click(control);
    await expect(await canvas.findByText('Update check preference saved.')).toBeVisible();
    await expect(control).toHaveAttribute('aria-checked', 'false');
    await expect(canvas.getByText(UPDATE_OFF)).toBeVisible();
    await expect(canvas.queryByText(UPDATE_ON)).toBeNull();
    await expect(posted).toHaveLength(1);
  },
};

export const UpdateChecksDisabledForThisRun: Story = {
  args: { update: 'flag-off' },
  play: async ({ canvas }) => {
    await expect(
      await canvas.findByText('Update checks are off for this run (--no-update-check).'),
    ).toBeVisible();
    await expect(canvas.queryByRole('switch', { name: UPDATE })).toBeNull();
    await expect(canvas.queryByText(UPDATE_ON)).toBeNull();
    await expect(canvas.queryByText(UPDATE_OFF)).toBeNull();
  },
};
export const UpdateChecksDisabledInThisBuild: Story = {
  args: { update: 'build-off' },
  play: async ({ canvas }) => {
    await expect(await canvas.findByText('Update checks are off in this build.')).toBeVisible();
    await expect(canvas.queryByRole('switch', { name: UPDATE })).toBeNull();
    await expect(canvas.queryByText(UPDATE_ON)).toBeNull();
    await expect(canvas.queryByText(UPDATE_OFF)).toBeNull();
  },
};
export const UpdateStoreRefuses: Story = {
  args: { update: 'refused' },
  play: async ({ canvas }) => {
    const control = await canvas.findByRole('switch', { name: UPDATE });
    await userEvent.click(control);
    await expect(
      await canvas.findByText('The settings could not be written. Try again.'),
    ).toBeVisible();
    await expect(control).toHaveAttribute('aria-checked', 'true');
    await expect(canvas.getByText(UPDATE_ON)).toBeVisible();
    await expect(canvas.queryByText(UPDATE_OFF)).toBeNull();
  },
};

export const PullRequestReadOn: Story = {
  play: async ({ canvas }) => {
    const control = await canvas.findByRole('switch', { name: CI });
    await expect(control).toHaveAttribute('aria-checked', 'true');
    await expect(canvas.getByText(CI_ON)).toBeVisible();
    await expect(canvas.queryByText(CI_OFF)).toBeNull();
    await userEvent.click(control);
    await expect(await canvas.findByText(CI_OFF)).toBeVisible();
    await expect(control).toHaveAttribute('aria-checked', 'false');
    await expect(posted).toEqual([
      { url: '/api/reading', body: { ci_read: 'off', press: true, observer_model: 1 } },
    ]);
  },
};

export const PullRequestReadOff: Story = {
  args: { ci: 'off' },
  play: async ({ canvas }) => {
    const control = await canvas.findByRole('switch', { name: CI });
    await expect(control).toHaveAttribute('aria-checked', 'false');
    await expect(canvas.getByText(CI_OFF)).toBeVisible();
    await expect(canvas.queryByText(CI_ON)).toBeNull();
    await expect(canvas.queryByText(CI_FLAG)).toBeNull();
    await userEvent.click(control);
    await expect(await canvas.findByText(CI_ON)).toBeVisible();
    await expect(posted).toEqual([
      { url: '/api/reading', body: { ci_read: 'on', press: true, observer_model: 1 } },
    ]);
  },
};

export const PullRequestReadFlagOff: Story = {
  args: { ci: 'flag-off' },
  play: async ({ canvas }) => {
    await expect(await canvas.findByText(CI_FLAG)).toBeVisible();
    await expect(canvas.queryByRole('switch', { name: CI })).toBeNull();
    await expect(canvas.queryByText(CI_OFF)).toBeNull();
    await expect(canvas.queryByText(CI_ON)).toBeNull();
  },
};

export const PullRequestReadUnavailable: Story = {
  args: { ci: 'unknown' },
  play: async ({ canvas }) => {
    await expect(canvas.getByText('The pull request read setting is unavailable.')).toBeVisible();
    await expect(canvas.queryByRole('switch', { name: CI })).toBeNull();
    for (const alternative of [CI_ON, CI_OFF, CI_FLAG])
      await expect(canvas.queryByText(alternative)).toBeNull();
  },
};

export const PullRequestReadRefusal: Story = {
  args: { ci: 'refused' },
  play: async ({ canvas }) => {
    const control = await canvas.findByRole('switch', { name: CI });
    await userEvent.click(control);
    await expect(await canvas.findByText('Could not save that. Try again.')).toBeVisible();
    await expect(control).toHaveAttribute('aria-checked', 'true');
    await expect(canvas.getByText(CI_ON)).toBeVisible();
    await expect(canvas.queryByText(CI_OFF)).toBeNull();
  },
};

export const PullRequestReadShowsTheReply: Story = {
  args: { ci: 'withheld' },
  play: async ({ canvas }) => {
    const control = await canvas.findByRole('switch', { name: CI });
    await userEvent.click(control);
    await waitFor(() => expect(posted).toHaveLength(1));
    await waitFor(() => expect(control).not.toHaveAttribute('aria-busy'));
    await expect(control).toHaveAttribute('aria-checked', 'true');
    await expect(canvas.queryByText(CI_OFF)).toBeNull();
  },
};

export const AiUseOn: Story = {
  play: async ({ canvas }) => {
    const pause = await canvas.findByRole('switch', { name: 'Pause all AI use' });
    const summaries = canvas.getByRole('switch', { name: 'Summaries' });
    await expect(pause).toHaveAttribute('aria-checked', 'false');
    await expect(summaries).toHaveAttribute('aria-checked', 'true');
    await expect(canvas.getByText(SUMMARY_ON)).toBeVisible();
    await expect(canvas.queryByText(SUMMARY_PAUSED)).toBeNull();
    await expect(canvas.queryByRole('switch', { name: 'Resume AI use' })).toBeNull();
    await userEvent.click(pause);
    await expect(await canvas.findByRole('switch', { name: 'Resume AI use' })).toHaveAttribute(
      'aria-checked',
      'true',
    );
    await expect(summaries).toHaveAttribute('aria-disabled', 'true');
    await expect(canvas.getByText(SUMMARY_PAUSED)).toBeVisible();
    await expect(posted).toEqual([
      { url: '/api/reading', body: { consent: 'off', press: true, observer_model: 1 } },
    ]);
  },
};

export const AiUsePaused: Story = {
  args: { pause: 'paused' },
  play: async ({ canvas }) => {
    const pause = await canvas.findByRole('switch', { name: 'Resume AI use' });
    const summaries = canvas.getByRole('switch', { name: 'Summaries' });
    await expect(pause).toHaveAttribute('aria-checked', 'true');
    await expect(summaries).toHaveAttribute('aria-disabled', 'true');
    await expect(summaries).toHaveAttribute('aria-checked', 'false');
    await expect(canvas.getByText(SUMMARY_PAUSED)).toBeVisible();
    await expect(canvas.queryByText(SUMMARY_ON)).toBeNull();
    await expect(canvas.queryByText(SUMMARY_OFF)).toBeNull();
    await expect(canvas.queryByRole('switch', { name: 'Pause all AI use' })).toBeNull();
    const parent = pause.parentElement?.parentElement;
    await expect(parent).toContainElement(summaries);
    await userEvent.click(pause);
    await expect(await canvas.findByRole('switch', { name: 'Pause all AI use' })).toHaveAttribute(
      'aria-checked',
      'false',
    );
    await expect(posted).toEqual([
      { url: '/api/reading', body: { consent: 'on', press: true, observer_model: 1 } },
    ]);
  },
};

export const AiSettingsUnreadable: Story = {
  args: { pause: 'unknown' },
  play: async ({ canvas }) => {
    await expect(canvas.getByText('The AI pause setting is unavailable.')).toBeVisible();
    await expect(canvas.getByText(SUMMARY_UNKNOWN)).toBeVisible();
    await expect(
      canvas.queryByRole('switch', { name: /Pause all AI use|Resume AI use|Summaries/ }),
    ).toBeNull();
  },
};

export const BoardSettingsAreStale: Story = {
  play: async ({ canvas }) => {
    await canvas.findByRole('switch', { name: CI });
    await canvas.findByRole('switch', { name: 'Pause all AI use' });
    publishBoard('stale');
    await expect(
      await canvas.findByText('Compass could not refresh the AI pause setting.'),
    ).toBeVisible();
    await expect(
      canvas.getByText('Compass could not refresh the pull request read setting.'),
    ).toBeVisible();
    await expect(canvas.getByText(SUMMARY_UNKNOWN)).toBeVisible();
    await expect(
      canvas.queryByRole('switch', {
        name: /Pause all AI use|Resume AI use|Summaries|Read pull request status/,
      }),
    ).toBeNull();
    await expect(canvas.queryByText(CI_ON)).toBeNull();
    await expect(canvas.queryByText(SUMMARY_ON)).toBeNull();
  },
};

export const BoardSettingsAreWithdrawn: Story = {
  play: async ({ canvas }) => {
    await canvas.findByRole('switch', { name: CI });
    await canvas.findByRole('switch', { name: 'Pause all AI use' });
    publishBoard('withdrawn');
    await expect(await canvas.findByText('The AI pause setting is unavailable.')).toBeVisible();
    await expect(canvas.getByText('The pull request read setting is unavailable.')).toBeVisible();
    await expect(canvas.getByText(SUMMARY_UNKNOWN)).toBeVisible();
    await expect(
      canvas.queryByRole('switch', {
        name: /Pause all AI use|Resume AI use|Summaries|Read pull request status/,
      }),
    ).toBeNull();
    await expect(canvas.queryByText(CI_ON)).toBeNull();
    await expect(canvas.queryByText(SUMMARY_ON)).toBeNull();
  },
};

export const SettingsOverview: Story = {
  play: async ({ canvas }) => {
    await expect(await canvas.findByRole('switch', { name: 'Pause all AI use' })).toBeVisible();
    await expect(canvas.getByRole('heading', { level: 1, name: 'Settings' })).toBeVisible();
    await expect(canvas.getByRole('region', { name: 'AI use' })).toBeVisible();
    await expect(canvas.getByRole('region', { name: 'Connections' })).toBeVisible();
    await expect(
      await canvas.findByRole('region', { name: 'How much a progress check reads' }),
    ).toBeVisible();
    await expect(canvas.getByRole('region', { name: 'Your data' })).toBeVisible();
  },
};

export const AiPauseRefused: Story = {
  args: { pause: 'refused' },
  play: async ({ canvas }) => {
    const pause = await canvas.findByRole('switch', { name: 'Pause all AI use' });
    await userEvent.click(pause);
    await expect(await canvas.findByText('Could not confirm AI use is paused.')).toBeVisible();
    await expect(pause).toHaveAttribute('aria-checked', 'false');
    await expect(canvas.getByText(SUMMARY_ON)).toBeVisible();
    await expect(canvas.queryByText(SUMMARY_PAUSED)).toBeNull();
  },
};

export const SummariesOff: Story = {
  args: { summaries: 'off' },
  play: async ({ canvas }) => {
    const control = await canvas.findByRole('switch', { name: 'Summaries' });
    await expect(control).toHaveAttribute('aria-checked', 'false');
    await expect(canvas.getByText(SUMMARY_OFF)).toBeVisible();
    await expect(canvas.queryByText(SUMMARY_PAUSED)).toBeNull();
    await expect(canvas.queryByText(SUMMARY_ON)).toBeNull();
    await userEvent.click(control);
    await expect(await canvas.findByText(SUMMARY_ON)).toBeVisible();
    await expect(posted).toEqual([{ url: '/api/summary', body: { consent: 'on' } }]);
  },
};

export const SummariesUnreadable: Story = {
  args: { summaries: 'unreadable' },
  play: async ({ canvas }) => {
    await canvas.findByRole('switch', { name: 'Pause all AI use' });
    await expect(canvas.getByText(SUMMARY_UNKNOWN)).toBeVisible();
    await expect(canvas.queryByRole('switch', { name: 'Summaries' })).toBeNull();
    for (const alternative of [SUMMARY_ON, SUMMARY_OFF, SUMMARY_PAUSED])
      await expect(canvas.queryByText(alternative)).toBeNull();
  },
};

export const SummariesAtTheDailyLimit: Story = {
  args: { summaries: 'daily-cap' },
  play: async ({ canvas }) => {
    const control = await canvas.findByRole('switch', { name: 'Summaries' });
    await expect(control).toHaveAttribute('aria-checked', 'true');
    await expect(
      canvas.getByText('Summaries are on. Today’s limit has been reached.'),
    ).toBeVisible();
    for (const alternative of [SUMMARY_ON, SUMMARY_OFF, SUMMARY_PAUSED])
      await expect(canvas.queryByText(alternative)).toBeNull();
  },
};

export const SummariesRefused: Story = {
  args: { summaries: 'refused' },
  play: async ({ canvas }) => {
    const control = await canvas.findByRole('switch', { name: 'Summaries' });
    await userEvent.click(control);
    await expect(
      await canvas.findByText('Could not confirm summaries are off. Try turning them off again.'),
    ).toBeVisible();
    await expect(canvas.getByText(SUMMARY_ON)).toBeVisible();
    await expect(canvas.queryByText(SUMMARY_OFF)).toBeNull();
    await expect(control).toHaveAttribute('aria-checked', 'true');
  },
};

export const PromptSettingsFailButAiPauseIsAvailable: Story = {
  args: { update: 'unreadable', annotations: false },
  play: async ({ canvas }) => {
    await expect(
      await canvas.findByText('The prompt limits and update preference could not be read.'),
    ).toBeVisible();
    await expect(canvas.getByText('The update check setting is unavailable.')).toBeVisible();
    await expect(await canvas.findByRole('switch', { name: 'Pause all AI use' })).toHaveAttribute(
      'aria-checked',
      'false',
    );
    await expect(canvas.queryByRole('switch', { name: UPDATE })).toBeNull();
    await expect(canvas.queryByText(UPDATE_ON)).toBeNull();
    await expect(canvas.queryByText(UPDATE_OFF)).toBeNull();
  },
};

function notifications(permission: Scenario['notifications'], words: string): Story {
  return {
    args: { notifications: permission },
    play: async ({ canvas }) => {
      await expect(await canvas.findByText(words)).toBeVisible();
      for (const alternative of [NOT_ASKED, ALLOWED, BLOCKED, NOT_SUPPORTED])
        if (words !== alternative) await expect(canvas.queryByText(alternative)).toBeNull();
      await expect(canvas.queryByRole('button', { name: 'Allow' })).toBeNull();
      await expect(permissionPrompts).toBe(0);
    },
  };
}

export const NotificationsGranted = notifications('granted', ALLOWED);
export const NotificationsDenied = notifications('denied', BLOCKED);
export const NotificationsUnavailable = notifications('unsupported', NOT_SUPPORTED);
export const NativeNotifications = notifications(
  'native',
  'Compass sends desktop notifications directly on this computer.',
);
export const NotificationsNotYetAsked: Story = {
  play: async ({ canvas }) => {
    await expect(canvas.getByText(NOT_ASKED)).toBeVisible();
    await expect(canvas.queryByText(ALLOWED)).toBeNull();
    await expect(canvas.queryByText(BLOCKED)).toBeNull();
    await expect(permissionPrompts).toBe(0);
    const button = canvas.getByRole('button', { name: 'Allow' });
    await userEvent.click(button);
    await expect(canvas.getByText(ALLOWED)).toHaveFocus();
    await expect(canvas.queryByText(NOT_ASKED)).toBeNull();
    await expect(permissionPrompts).toBe(1);
  },
};

export const PlanUsageAllowed: Story = {
  play: async ({ canvas }) => {
    await expect(await canvas.findByText('Plan usage is allowed in this browser.')).toBeVisible();
    await expect(canvas.queryByText('Plan usage is turned off in this browser.')).toBeNull();
    await userEvent.click(canvas.getByRole('button', { name: 'Turn off plan usage' }));
    await expect(canvas.getByText('Plan usage is turned off in this browser.')).toBeVisible();
    await expect(canvas.queryByText('Plan usage is allowed in this browser.')).toBeNull();
  },
};
export const PlanUsageDeclined: Story = {
  args: { usage: 'declined' },
  play: async ({ canvas }) => {
    await expect(canvas.getByText('Plan usage is turned off in this browser.')).toBeVisible();
    await expect(canvas.getByRole('button', { name: 'Allow plan usage' })).toBeVisible();
    await expect(canvas.queryByText('Plan usage is allowed in this browser.')).toBeNull();
  },
};
export const PlanUsageUnavailable: Story = {
  args: { usage: 'unavailable' },
  play: async ({ canvas }) => {
    await canvas.findByRole('switch', { name: 'Pause all AI use' });
    await expect(canvas.getByText('Plan usage is unavailable on this dashboard.')).toBeVisible();
    await expect(canvas.queryByText('Plan usage is allowed in this browser.')).toBeNull();
  },
};

export const WhatIsSentForCodex: Story = {
  args: { harness: 'codex' },
  play: async ({ canvas }) => {
    const aiUse = within(canvas.getByRole('region', { name: 'AI use' }));
    const trigger = aiUse.getByRole('button', { name: 'What is sent, and where' });
    await expect(trigger).toHaveAttribute('aria-expanded', 'false');
    await userEvent.click(trigger);
    await waitFor(() => expect(aiUse.getByText('OpenAI', { exact: true })).toBeVisible());
    await expect(aiUse.getByText('Saved prompt size limit: 512 KB.')).toBeVisible();
    await expect(aiUse.getByText(summaryDisclosure)).toBeVisible();
    await expect(aiUse.queryByText('The progress check destination is unavailable.')).toBeNull();
    await expect(aiUse.queryByText(/524,288 bytes/)).toBeNull();
  },
};

export const WhatIsSentWithoutPublishedDetails: Story = {
  args: { pause: 'unknown', annotations: false, update: 'unreadable' },
  play: async ({ canvas }) => {
    const aiUse = within(canvas.getByRole('region', { name: 'AI use' }));
    await userEvent.click(aiUse.getByRole('button', { name: 'What is sent, and where' }));
    await waitFor(() =>
      expect(aiUse.getByText('The saved prompt size limit is unavailable.')).toBeVisible(),
    );
    await expect(aiUse.getByText('The progress check destination is unavailable.')).toBeVisible();
    await expect(aiUse.getByText('Summary details are unavailable.')).toBeVisible();
    await expect(aiUse.queryByText(/Saved prompt size limit:|Published destinations:/)).toBeNull();
  },
};

function fit(width: number): Story {
  return {
    play: async ({ canvas, canvasElement }) => {
      await atPageWidth(width, async () => {
        await canvas.findByRole('switch', { name: CI });
        await expect(document.documentElement.scrollWidth).toBe(window.innerWidth);
        for (const target of canvasElement.querySelectorAll('button, a[href]')) {
          if (target.closest('[hidden]')) continue;
          const box = target.getBoundingClientRect();
          if (box.width === 0 && box.height === 0) continue;
          await expect(
            Math.min(box.width, box.height),
            target.textContent ?? '',
          ).toBeGreaterThanOrEqual(44);
          await expect(box.left).toBeGreaterThanOrEqual(0);
          await expect(box.right).toBeLessThanOrEqual(window.innerWidth);
        }
      });
    },
  };
}

export const SettingsAt390 = fit(390);
export const SettingsAt375 = fit(375);
export const SettingsAt320 = fit(320);

export const ForgetEverythingInline: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const card = within(canvas.getByRole('region', { name: 'Your data' }));
    await expect(
      canvas.getByRole('region', { name: 'Your data' }).querySelector('svg[data-icon="forget"]'),
    ).not.toBeNull();
    const trigger = card.getByRole('button', { name: 'Forget everything' });
    await expect(trigger).toHaveAttribute('aria-expanded', 'false');
    await userEvent.click(trigger);
    await expect(trigger).toHaveAttribute('aria-expanded', 'true');
    await waitFor(() => expect(card.getByText('This cannot be undone.')).toBeVisible());
    const stop = await card.findByText('spacedock-compass --port 6226 --stop');
    const forget = card.getByText('spacedock-compass --port 6226 --forget');
    await expect(
      stop.compareDocumentPosition(forget) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    await expect(card.getByRole('list', { name: 'Deletes' })).toBeVisible();
    await expect(card.getByRole('list', { name: 'Keeps' })).toBeVisible();
    await expect(
      canvasElement.querySelector('[role="dialog"], [role="alertdialog"], [aria-modal]'),
    ).toBeNull();
    await expect(card.queryByRole('button', { name: 'Done' })).toBeNull();
  },
};

export const ForgetCommandsCopied: Story = {
  play: async ({ canvas }) => {
    const card = within(canvas.getByRole('region', { name: 'Your data' }));
    await userEvent.click(card.getByRole('button', { name: 'Forget everything' }));
    await userEvent.click(await card.findByRole('button', { name: 'Copy' }));
    await waitFor(() => expect(card.getByText('Commands copied.')).toBeVisible());
    await expect(card.queryByText(/Could not copy/)).toBeNull();
    await expect(copied).toEqual([
      'spacedock-compass --port 6226 --stop\nspacedock-compass --port 6226 --forget',
    ]);
    await expect(posted).toHaveLength(0);
  },
};

export const ForgetClipboardRefused: Story = {
  args: { copy: 'refused' },
  play: async ({ canvas }) => {
    const card = within(canvas.getByRole('region', { name: 'Your data' }));
    await userEvent.click(card.getByRole('button', { name: 'Forget everything' }));
    await userEvent.click(await card.findByRole('button', { name: 'Copy' }));
    await waitFor(() =>
      expect(
        card.getByText('Could not copy. Select the commands above to copy them.'),
      ).toBeVisible(),
    );
    await expect(card.queryByText('Commands copied.')).toBeNull();
    await expect(copied).toEqual([]);
  },
};

export const ForgetPortUnavailable: Story = {
  args: { port: 'missing' },
  play: async ({ canvas }) => {
    const card = within(canvas.getByRole('region', { name: 'Your data' }));
    await userEvent.click(card.getByRole('button', { name: 'Forget everything' }));
    await waitFor(() =>
      expect(
        card.getByText(
          'Compass could not read the dashboard port. Use the port you started it with.',
        ),
      ).toBeVisible(),
    );
    await expect(card.queryByRole('button', { name: 'Copy' })).toBeNull();
    await expect(card.queryByText(/spacedock-compass --port/)).toBeNull();
  },
};

export const ForgetPortLoading: Story = {
  args: { port: 'loading' },
  play: async ({ canvas }) => {
    const card = within(canvas.getByRole('region', { name: 'Your data' }));
    await userEvent.click(card.getByRole('button', { name: 'Forget everything' }));
    await waitFor(() => expect(card.getByText('Reading the dashboard port.')).toBeVisible());
    await expect(card.queryByRole('button', { name: 'Copy' })).toBeNull();
    await expect(card.queryByText(/could not read the dashboard port/i)).toBeNull();
  },
};

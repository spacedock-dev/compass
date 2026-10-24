import { screen, waitFor } from '@testing-library/react';
import { userEvent } from 'storybook/test';
import { describe, expect, it } from 'vitest';
import { goalBox, mountSession } from './panel.testing';
import { json } from './testing';

const choices = [{ fact_id: 'p1', text: 'Fix the login redirect', at: 100, cut: false }];
const trigger = () => screen.getByRole('button', { name: 'Use your prompt' });

async function opening() {
  const page = mountSession({
    routes: {
      '/api/project-context': (request) => (request.url.includes('prompts=1') ? 'hold' : json({})),
    },
  });
  await page.settle();
  await page.settle();
  const user = userEvent.setup();
  const select = trigger();
  await user.click(select);
  await waitFor(() => expect(select.getAttribute('aria-expanded')).toBe('true'));

  return { page, select, user };
}

describe('a reader opening their prompts', () => {
  it('sees that a long-record prompt search stopped, beside the choices it did find', async () => {
    const { page } = await opening();
    await page.release(
      '/api/project-context',
      json({ prompt_choices: choices, prompt_scan: { state: 'ok', bound: 'bytes' } }),
    );
    expect(
      screen.getByRole('option', {
        name: 'The prompt search reached its limit. Older prompts may be outside this read.',
      }),
    ).toBeTruthy();
    expect(screen.getByRole('option', { name: /Fix the login redirect/ })).toBeTruthy();
  });
  it('sees an open loading list on the first press and chooses from that same popup when the request arrives', async () => {
    const { page, select, user } = await opening();
    expect(select.textContent).toBe('Use your prompt');
    expect(select.getAttribute('aria-busy')).toBe('true');
    expect(select.getAttribute('aria-expanded')).toBe('true');
    const popup = screen.getByRole('listbox');
    expect(
      screen.getByRole('option', { name: 'Loading your prompts' }).getAttribute('aria-disabled'),
    ).toBe('true');
    await page.release('/api/project-context', json({ prompt_choices: choices }));
    expect(trigger()).toBe(select);
    expect(screen.getByRole('listbox')).toBe(popup);
    expect(select.getAttribute('aria-busy')).toBe('false');
    await user.click(screen.getByRole('option', { name: /Fix the login redirect/ }));
    expect(goalBox().value).toBe('Fix the login redirect');
    expect(page.posts()).toBe(0);
    expect(page.state.requests.filter((request) => request.url.includes('prompts=1'))).toHaveLength(
      1,
    );
  });

  it.each([
    [
      json({ prompt_choices: [] }),
      'No usable prompts were found in the parts of this session Compass read.',
    ],
    [json({ error: 'unavailable' }, 503), 'Compass could not read your prompts from this session.'],
  ])(
    'keeps an empty or failed list open with its own stated absence (%#)',
    async (response, sentence) => {
      const { page, select } = await opening();
      await page.release('/api/project-context', response);
      expect(select.getAttribute('aria-expanded')).toBe('true');
      expect(select.getAttribute('aria-busy')).toBe('false');
      expect(screen.getByRole('option', { name: sentence }).getAttribute('aria-disabled')).toBe(
        'true',
      );
    },
  );

  it('keeps the absence popup even when the last cached offer was the only reason to show the trigger', async () => {
    const page = mountSession({
      session: { first_prompt: '', first_prompt_at: null },
      routes: {
        '/api/project-context': (request) =>
          request.url.includes('prompts=1') ? 'hold' : json({ prompt_choices: choices }),
      },
    });
    await page.settle();
    await page.settle();
    const select = trigger();
    await userEvent.setup().click(select);
    const popup = await screen.findByRole('listbox');
    await page.release('/api/project-context', json({ prompt_choices: [] }));
    expect(select.isConnected).toBe(true);
    expect(screen.getByRole('listbox')).toBe(popup);
    expect(
      screen
        .getByRole('option', {
          name: 'No usable prompts were found in the parts of this session Compass read.',
        })
        .getAttribute('aria-disabled'),
    ).toBe('true');
  });

  it('says the read failed, not that none were found, when the server names this record unavailable', async () => {
    const { page, select } = await opening();
    await page.release(
      '/api/project-context',
      json({
        prompt_choices: [],
        sources: { work: { unavailable: [{ harness: 'claude', sid: 's1', reason: 'not found' }] } },
      }),
    );
    expect(select.getAttribute('aria-busy')).toBe('false');
    expect(
      screen.getByRole('option', {
        name: 'Compass could not read your prompts from this session.',
      }),
    ).toBeTruthy();
  });

  it('keeps saying the read failed when the last cached offer was the only reason to show the trigger', async () => {
    const page = mountSession({
      session: { first_prompt: '', first_prompt_at: null },
      routes: {
        '/api/project-context': (request) =>
          request.url.includes('prompts=1') ? 'hold' : json({ prompt_choices: choices }),
      },
    });
    await page.settle();
    await page.settle();
    await userEvent.setup().click(trigger());
    await screen.findByRole('listbox');
    await page.release('/api/project-context', json({ error: 'unavailable' }, 503));
    expect(
      screen.getByRole('option', {
        name: 'Compass could not read your prompts from this session.',
      }),
    ).toBeTruthy();
  });

  it('closes only the popup on Escape and never reopens it when a dismissed request arrives', async () => {
    const { page, select, user } = await opening();
    await user.keyboard('{Escape}');
    expect(select.getAttribute('aria-expanded')).toBe('false');
    expect(page.router.getRoute().view).toBe('session');
    await page.release('/api/project-context', json({ prompt_choices: choices }));
    expect(select.getAttribute('aria-expanded')).toBe('false');
    expect(goalBox().value).toBe('Ship the queue worker');
  });
});

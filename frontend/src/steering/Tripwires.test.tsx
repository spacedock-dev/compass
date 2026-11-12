import { act, fireEvent, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { Tripwires } from './Tripwires';
import { mountPanels } from './testing';

/* The tripwires are browser preferences. They keep the released storage format and read the older one, the add
   box stays open for the tab, Escape cancels its draft without leaving the page, and none of it is ever sent. */
const KEY = (project: string) => `compass.next.guardrails.${encodeURIComponent(project)}`;
const input = (): HTMLInputElement =>
  document.querySelector('[data-next-guardrail-input]') as HTMLInputElement;
const add = () => screen.getByText('+ set a tripwire');
const rows = () => [...document.querySelectorAll('[data-next-guardrail-toggle]')];
const press = async (element: Element) => {
  await act(async () => {
    fireEvent.click(element);
  });
};
const type = (element: HTMLInputElement, value: string) => {
  element.focus();
  fireEvent.input(element, { target: { value } });
};

describe('the panel says nothing enforces these', () => {
  it('names itself local and says it is a note to yourself', async () => {
    const page = mountPanels(<Tripwires project="alpha/app" />);
    await page.settle();
    expect(screen.getByText('local only · nothing enforces these')).toBeInTheDocument();
    expect(
      screen.getByText(/Until it ships they are a note to yourself, held in this browser\./),
    ).toBeInTheDocument();
    expect(screen.getByText('No tripwires saved in this browser.')).toBeInTheDocument();
  });
});

describe('the rules', () => {
  it.each(['remove', 'toggle'] as const)(
    'lets a reader %s B after another tab removes A, without changing C',
    async (action) => {
      const page = mountPanels(<Tripwires project="p" />, {
        storage: { [KEY('p')]: '["A","B","C"]' },
      });
      await page.settle();
      page.backend.setItem(KEY('p'), '["B","C"]');
      await press(
        action === 'remove'
          ? screen.getByRole('button', { name: 'Remove tripwire: B' })
          : screen.getByRole('switch', { name: 'B' }),
      );
      expect(rows().map((row) => row.querySelector('strong')?.textContent)).toEqual(
        action === 'remove' ? ['C'] : ['B', 'C'],
      );
      expect(JSON.parse(page.backend.data.get(KEY('p')) ?? '[]')).toEqual(
        action === 'remove'
          ? [{ enabled: true, text: 'C' }]
          : [
              { enabled: false, text: 'B' },
              { enabled: true, text: 'C' },
            ],
      );
    },
  );

  it.each(['remove', 'toggle'] as const)(
    'refreshes a missing rule after a stale %s without writing',
    async (action) => {
      const page = mountPanels(<Tripwires project="p" />, {
        storage: { [KEY('p')]: '["A","B","C"]' },
      });
      await page.settle();
      page.backend.setItem(KEY('p'), '["A","C"]');
      const writes = page.backend.writes.length;
      await press(
        action === 'remove'
          ? screen.getByRole('button', { name: 'Remove tripwire: B' })
          : screen.getByRole('switch', { name: 'B' }),
      );
      expect(rows().map((row) => row.querySelector('strong')?.textContent)).toEqual(['A', 'C']);
      expect(page.backend.writes).toHaveLength(writes);
      expect(screen.getByText(/Tripwires changed in another tab/)).toBeVisible();
    },
  );

  it('read what an older build stored, and write the released shape', async () => {
    const page = mountPanels(<Tripwires project="alpha/app" />, {
      storage: {
        [KEY('alpha/app')]: JSON.stringify([
          'an old string rule',
          { text: ' kept ', enabled: false },
          5,
          { text: '   ' },
        ]),
      },
    });
    await page.settle();
    expect(rows().map((row) => row.textContent)).toEqual([
      '◇an old string rule',
      '◇keptDisabled in this browser.',
    ]);
    expect(rows().map((row) => row.getAttribute('aria-checked'))).toEqual(['true', 'false']);
    await press(rows()[0] as Element);
    expect(JSON.parse(page.backend.data.get(KEY('alpha/app')) ?? '[]')).toEqual([
      { enabled: false, text: 'an old string rule' },
      { enabled: false, text: 'kept' },
    ]);
  });

  it('are one project’s own, keyed by the exact label', async () => {
    const page = mountPanels(<Tripwires project="alpha/app" />);
    await page.settle();
    await press(add());
    type(input(), 'alert me when the build breaks');
    fireEvent.keyDown(input(), { key: 'Enter' });
    expect(rows()).toHaveLength(1);
    page.show(<Tripwires project="beta/api" />);
    await page.settle();
    expect(rows()).toHaveLength(0);
    expect(page.backend.data.has(KEY('alpha/app'))).toBe(true);
    expect(page.backend.data.has(KEY('beta/api'))).toBe(false);
  });

  it('keep all fifty tripwires and the draft when another add is refused', async () => {
    const rules = Array.from({ length: 50 }, (_, index) => `rule ${String(index + 1)}`);
    const stored = JSON.stringify(rules);
    const page = mountPanels(<Tripwires project="p" />, { storage: { [KEY('p')]: stored } });
    await page.settle();
    await press(add());
    type(input(), 'keep this draft');
    fireEvent.keyDown(input(), { key: 'Enter' });
    expect(
      screen
        .getAllByRole('status')
        .some(
          (node) =>
            node.textContent ===
            'You have 50 tripwires on this project. Remove one to add another.',
        ),
    ).toBe(true);
    expect((input() as HTMLInputElement | HTMLTextAreaElement).value).toBe('keep this draft');
    expect(rows()).toHaveLength(50);
    expect(rows().map((row) => row.querySelector('strong')?.textContent)).toEqual(rules);
    expect(page.backend.data.get(KEY('p'))).toBe(stored);
    expect(page.backend.writes.filter((key) => key === KEY('p'))).toEqual([]);
    page.show(<p>elsewhere</p>);
    page.show(<Tripwires project="p" />);
    await page.settle();
    expect((input() as HTMLInputElement | HTMLTextAreaElement).value).toBe('keep this draft');
    const remove = screen.getByRole('button', { name: 'Remove tripwire: rule 1' });
    remove.focus();
    await press(remove);
    await page.settle();
    expect(document.activeElement).toBe(input());
    expect(rows()).toHaveLength(49);
    expect(input().value).toBe('keep this draft');
    fireEvent.keyDown(input(), { key: 'Enter' });
    expect(rows()).toHaveLength(50);
    expect(rows().at(-1)?.querySelector('strong')?.textContent).toBe('keep this draft');
  });

  it('returns focus to the add control when the last rule is removed with no editor open', async () => {
    const page = mountPanels(<Tripwires project="p" />, { storage: { [KEY('p')]: '["only"]' } });
    await page.settle();
    const remove = screen.getByRole('button', { name: 'Remove tripwire: only' });
    remove.focus();
    await press(remove);
    await page.settle();
    expect(document.activeElement).toBe(add());
    expect(rows()).toHaveLength(0);
  });
});

describe('the add box', () => {
  it('accepts 1050 emoji as 1050 characters', async () => {
    const page = mountPanels(<Tripwires project="p" />);
    await page.settle();
    await press(add());
    const text = '😀'.repeat(1050);
    type(input(), text);
    expect(input().hasAttribute('aria-invalid')).toBe(false);
    expect(document.querySelector('[data-character-count]')).toBeNull();
    fireEvent.keyDown(input(), { key: 'Enter' });
    expect(rows()[0]?.querySelector('strong')?.textContent).toBe(text);
  });
  it.each(['界'.repeat(2100), '😀'.repeat(2100)])(
    'keeps an over-limit paste, refuses Enter and submit, and adds after editing back',
    async (text) => {
      const page = mountPanels(<Tripwires project="alpha/app" />);
      await page.settle();
      await press(add());
      type(input(), text);
      expect(input().hasAttribute('maxlength')).toBe(false);
      expect((input() as HTMLInputElement | HTMLTextAreaElement).value).toBe(text);
      expect(screen.getByText('2100/2000').getAttribute('data-over')).toBe('true');
      expect(input().getAttribute('aria-invalid')).toBe('true');
      expect(screen.getByText('2100 characters; the limit is 2000.')).toBeVisible();
      expect((screen.getByRole('button', { name: 'add ↵' }) as HTMLButtonElement).disabled).toBe(
        true,
      );
      fireEvent.keyDown(input(), { key: 'Enter' });
      fireEvent.submit(input().closest('form') as HTMLFormElement);
      expect(rows()).toHaveLength(0);
      expect((input() as HTMLInputElement | HTMLTextAreaElement).value).toBe(text);
      page.show(<p>elsewhere</p>);
      page.show(<Tripwires project="alpha/app" />);
      await page.settle();
      expect((input() as HTMLInputElement | HTMLTextAreaElement).value).toBe(text);
      type(input(), Array.from(text).slice(0, 2000).join(''));
      expect((screen.getByRole('button', { name: 'add ↵' }) as HTMLButtonElement).disabled).toBe(
        false,
      );
      fireEvent.keyDown(input(), { key: 'Enter' });
      expect(rows()[0]?.querySelector('strong')?.textContent).toBe(
        Array.from(text).slice(0, 2000).join(''),
      );
    },
  );

  it('shows a counter from eighty percent and lets Escape abandon over-limit words', async () => {
    const page = mountPanels(<Tripwires project="alpha/app" />);
    await page.settle();
    await press(add());
    type(input(), 'x'.repeat(1500));
    expect(document.querySelector('[data-character-count]')).toBeNull();
    type(input(), 'x'.repeat(1600));
    expect(screen.getByText('1600/2000')).toBeVisible();
    type(input(), 'x'.repeat(2100));
    fireEvent.keyDown(input(), { key: 'Escape' });
    await press(add());
    expect((input() as HTMLInputElement | HTMLTextAreaElement).value).toBe('');
    expect(document.querySelector('[data-character-count]')).toBeNull();
  });

  it('stays open for the tab, with its words, when the panel leaves and returns', async () => {
    const page = mountPanels(<Tripwires project="alpha/app" />);
    await page.settle();
    await press(add());
    type(input(), 'half a rule');
    input().setSelectionRange(2, 4);
    page.show(<p>elsewhere</p>);
    page.show(<Tripwires project="alpha/app" />);
    await page.settle();
    expect(input().value).toBe('half a rule');
    expect([input().selectionStart, input().selectionEnd]).toEqual([2, 4]);
  });

  it('Escape cancels the draft and closes the box, and the page does not leave', async () => {
    const page = mountPanels(<Tripwires project="alpha/app" />);
    await page.settle();
    const before = page.history.entries();
    await press(add());
    type(input(), 'never mind');
    const event = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true });
    let reachedWindow = false;
    const watch = () => {
      reachedWindow = true;
    };
    window.addEventListener('keydown', watch);
    await act(async () => {
      input().dispatchEvent(event);
    });
    window.removeEventListener('keydown', watch);
    expect(reachedWindow).toBe(false);
    expect(event.defaultPrevented).toBe(true);
    expect(document.querySelector('[data-next-guardrail-form]')).toBeNull();
    expect(page.history.entries()).toEqual(before);
    // Reopened, it is empty: an abandoned draft is not offered back.
    await press(add());
    expect(input().value).toBe('');
    expect(rows()).toHaveLength(0);
  });

  it('Enter adds once and the committed rule is not offered back', async () => {
    const page = mountPanels(<Tripwires project="alpha/app" />);
    await page.settle();
    await press(add());
    type(input(), 'notify me of a force push');
    fireEvent.keyDown(input(), { key: 'Enter' });
    expect(rows()).toHaveLength(1);
    await press(add());
    expect(input().value).toBe('');
    fireEvent.keyDown(input(), { key: 'Enter' });
    expect(rows()).toHaveLength(1);
    expect(page.backend.writes.filter((key) => key === KEY('alpha/app'))).toHaveLength(1);
  });

  it('closes on an empty submit without adding anything', async () => {
    const page = mountPanels(<Tripwires project="alpha/app" />);
    await page.settle();
    await press(add());
    await act(async () => {
      fireEvent.submit(document.querySelector('[data-next-guardrail-form]') as HTMLFormElement);
    });
    expect(document.querySelector('[data-next-guardrail-form]')).toBeNull();
    expect(rows()).toHaveLength(0);
  });

  it('ignores an Enter that commits an input-method composition', async () => {
    const page = mountPanels(<Tripwires project="alpha/app" />);
    await page.settle();
    await press(add());
    type(input(), 'にほん');
    fireEvent.keyDown(input(), { key: 'Enter', isComposing: true });
    expect(rows()).toHaveLength(0);
    expect(document.querySelector('[data-next-guardrail-form]')).not.toBeNull();
  });
});

describe('nothing is sent', () => {
  it('no request leaves from a mount, a press, a toggle or a poll', async () => {
    const page = mountPanels(<Tripwires project="alpha/app" />, {
      data: { generated: 1, sessions: [] },
    });
    await page.settle();
    await press(add());
    type(input(), 'a rule');
    fireEvent.keyDown(input(), { key: 'Enter' });
    await press(rows()[0] as Element);
    await page.poll({ generated: 2, sessions: [] });
    expect(page.allPosts()).toEqual([]);
  });
});

import { act, fireEvent, screen, within } from '@testing-library/react';
import { Profiler } from 'react';
import { steeringHeldFor } from './held';
import { Tripwires } from './Tripwires';
import { StageConditions } from './StageConditions';
import { describe, expect, it } from 'vitest';
import { ProjectSteer } from './ProjectSteer';
import { mountPanels } from './testing';

/* The steering bar is a note to oneself. These hold what the reader keeps: the words, the caret, the receipt,
   and that nothing is ever sent. The real browser keeps the undo history and the composition, which jsdom
   cannot, and `console-parity.mjs` proves those against Chromium. */
const box = (): HTMLInputElement =>
  document.querySelector('[data-next-draft="steer"]') as HTMLInputElement;
const type = (element: HTMLInputElement, value: string) => {
  element.focus();
  fireEvent.input(element, { target: { value } });
};

describe('the steering bar says what it is before the first keystroke', () => {
  it('names itself local and says there is no write path into a session', async () => {
    const page = mountPanels(<ProjectSteer project="alpha/app" />);
    await page.settle();
    expect(screen.getByText('Your note (this tab only)')).toBeInTheDocument();
    expect(
      screen.getByText(
        /Compass has no write path into a session\. Anything you type here is a note to yourself/,
      ),
    ).toBeInTheDocument();
    expect(box().hasAttribute('maxlength')).toBe(false);
  });
});

describe('a draft', () => {
  it('accepts 1050 emoji and counts 1600 emoji as 1600 characters', async () => {
    const page = mountPanels(<ProjectSteer project="p" />);
    await page.settle();
    type(box(), '😀'.repeat(1600));
    expect(screen.getByText('1600/2000')).toBeVisible();
    type(box(), '😀'.repeat(1050));
    expect(box().hasAttribute('aria-invalid')).toBe(false);
    expect(document.querySelector('[data-character-count]')).toBeNull();
    fireEvent.submit(box().closest('form') as HTMLFormElement);
    expect(document.querySelector('[data-next-steer-receipt] strong')?.textContent).toBe(
      '😀'.repeat(1050),
    );
  });

  it('updates each local counter without notifying shared subscribers or rendering sibling panels', async () => {
    let siblingRenders = 0;
    const page = mountPanels(
      <>
        <ProjectSteer project="p" />
        <Profiler
          id="siblings"
          onRender={() => {
            siblingRenders += 1;
          }}
        >
          <Tripwires project="p" />
          <StageConditions sessions={null} />
        </Profiler>
      </>,
    );
    await page.settle();
    const held = steeringHeldFor(page.shell);
    let notifications = 0;
    const stop = held.subscribe(() => {
      notifications += 1;
    });
    const before = siblingRenders;
    type(box(), 'x'.repeat(1600));
    expect(screen.getByText('1600/2000')).toBeVisible();
    expect(notifications).toBe(0);
    expect(siblingRenders).toBe(before);
    fireEvent.click(screen.getByRole('button', { name: '+ set a tripwire' }));
    const opened = notifications;
    const tripwire = screen.getByRole('textbox', { name: 'New local tripwire' });
    fireEvent.input(tripwire, { target: { value: 'x'.repeat(2100) } });
    expect(screen.getByText('2100 characters; the limit is 2000.')).toBeVisible();
    expect(notifications).toBe(opened);
    stop();
  });
  it.each(['界'.repeat(2100), '😀'.repeat(2100)])(
    'keeps an over-limit paste, blocks saving and enables it after editing back',
    async (text) => {
      const page = mountPanels(<ProjectSteer project="alpha/app" />);
      await page.settle();
      type(box(), text);
      expect((box() as HTMLInputElement | HTMLTextAreaElement).value).toBe(text);
      expect(box().getAttribute('aria-invalid')).toBe('true');
      expect(screen.getByText('2100/2000').getAttribute('data-over')).toBe('true');
      expect(screen.getByText('2100 characters; the limit is 2000.')).toBeVisible();
      expect(
        (screen.getByRole('button', { name: 'save draft ⏎' }) as HTMLButtonElement).disabled,
      ).toBe(true);
      fireEvent.submit(box().closest('form') as HTMLFormElement);
      expect(document.querySelectorAll('[data-next-steer-receipt]')).toHaveLength(0);
      page.show(<p>elsewhere</p>);
      page.show(<ProjectSteer project="alpha/app" />);
      await page.settle();
      expect((box() as HTMLInputElement | HTMLTextAreaElement).value).toBe(text);
      expect(
        (screen.getByRole('button', { name: 'save draft ⏎' }) as HTMLButtonElement).disabled,
      ).toBe(true);
      type(box(), Array.from(text).slice(0, 2000).join(''));
      expect(
        (screen.getByRole('button', { name: 'save draft ⏎' }) as HTMLButtonElement).disabled,
      ).toBe(false);
      fireEvent.submit(box().closest('form') as HTMLFormElement);
      expect(document.querySelector('[data-next-steer-receipt] strong')?.textContent).toBe(
        Array.from(text).slice(0, 2000).join(''),
      );
    },
  );

  it('shows the counter from eighty percent and hides it below that point', async () => {
    const page = mountPanels(<ProjectSteer project="alpha/app" />);
    await page.settle();
    type(box(), 'x'.repeat(1500));
    expect(screen.queryByText('1500/2000')).toBeNull();
    type(box(), 'x'.repeat(1600));
    expect(screen.getByText('1600/2000')).toBeVisible();
    type(box(), 'x'.repeat(1500));
    expect(document.querySelector('[data-character-count]')).toBeNull();
  });

  it('survives the bar leaving and coming back, with its caret', async () => {
    const page = mountPanels(<ProjectSteer project="alpha/app" />);
    await page.settle();
    type(box(), 'tell the queue to drain');
    box().setSelectionRange(5, 9);
    page.show(<p>elsewhere</p>);
    await page.settle();
    expect(document.querySelector('[data-next-steer]')).toBeNull();
    page.show(<ProjectSteer project="alpha/app" />);
    await page.settle();
    expect(box().value).toBe('tell the queue to drain');
    expect([box().selectionStart, box().selectionEnd]).toEqual([5, 9]);
  });

  it('is one project’s own: another project’s box is another node with its own words', async () => {
    const page = mountPanels(<ProjectSteer project="alpha/app" />);
    await page.settle();
    const alpha = box();
    type(alpha, 'alpha words');
    page.show(<ProjectSteer project="beta/api" />);
    await page.settle();
    expect(box()).not.toBe(alpha);
    expect(box().value).toBe('');
    type(box(), 'beta words');
    page.show(<ProjectSteer project="alpha/app" />);
    await page.settle();
    expect(box().value).toBe('alpha words');
    page.show(<ProjectSteer project="beta/api" />);
    await page.settle();
    expect(box().value).toBe('beta words');
  });

  it('keeps one node across a board that changes: the editor is never replaced under the reader', async () => {
    const data = { generated: 1000, sessions: [] };
    const page = mountPanels(<ProjectSteer project="alpha/app" />, { data });
    await page.settle();
    const node = box();
    type(node, 'half a sentence');
    node.setSelectionRange(3, 3);
    await page.poll({ generated: 1001, sessions: [] });
    await page.poll({ generated: 1002, sessions: [] });
    expect(box()).toBe(node);
    expect(box().value).toBe('half a sentence');
    expect(box().selectionStart).toBe(3);
  });
});

describe('sending a draft', () => {
  it('records a receipt that says it was not delivered, and empties the box AND the draft', async () => {
    const page = mountPanels(<ProjectSteer project="alpha/app" />);
    await page.settle();
    type(box(), '  take the safer route  ');
    await act(async () => {
      fireEvent.submit(box().closest('form') as HTMLFormElement);
    });
    const receipt = document.querySelector('[data-next-steer-receipt]') as HTMLElement;
    expect(within(receipt).getByText('take the safer route')).toBeInTheDocument();
    expect(receipt.textContent).toContain('Draft recorded in this tab. Not delivered.');
    expect(box().value).toBe('');
    // Gone from the draft too: the bar leaving and returning must not bring the sentence back.
    page.show(<p>elsewhere</p>);
    page.show(<ProjectSteer project="alpha/app" />);
    await page.settle();
    expect(box().value).toBe('');
    // A second send of nothing records nothing.
    await act(async () => {
      fireEvent.submit(box().closest('form') as HTMLFormElement);
    });
    expect(document.querySelectorAll('[data-next-steer-receipt]')).toHaveLength(1);
  });

  it('never sends anything: no request from a mount, a poll, a press or StrictMode', async () => {
    const page = mountPanels(<ProjectSteer project="alpha/app" />, {
      data: { generated: 1, sessions: [] },
    });
    await page.settle();
    type(box(), 'note');
    await act(async () => {
      fireEvent.submit(box().closest('form') as HTMLFormElement);
    });
    await page.poll({ generated: 2, sessions: [] });
    expect(page.allPosts()).toEqual([]);
  });

  it('says when older notes are gone after the twenty-first receipt, and keeps the notice on return', async () => {
    const page = mountPanels(<ProjectSteer project="alpha/app" />);
    await page.settle();
    for (let n = 1; n <= 21; n += 1) {
      type(box(), `note ${String(n)}`);
      await act(async () => {
        fireEvent.submit(box().closest('form') as HTMLFormElement);
      });
      if (n === 20) expect(screen.queryByText('Older notes are not kept.')).toBeNull();
    }
    const notes = [...document.querySelectorAll('[data-next-steer-receipt] strong')].map(
      (node) => node.textContent,
    );
    expect(notes).toHaveLength(20);
    expect(notes[0]).toBe('note 2');
    expect(notes[19]).toBe('note 21');
    expect(screen.getByText('Older notes are not kept.')).toBeVisible();
    page.show(<p>elsewhere</p>);
    page.show(<ProjectSteer project="alpha/app" />);
    await page.settle();
    expect(screen.getByText('Older notes are not kept.')).toBeVisible();
  });
});

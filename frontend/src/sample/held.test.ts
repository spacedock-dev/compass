// @vitest-environment jsdom
import { describe, expect, it } from 'vitest';
import { heldPosition, isHeld } from './held';

const html = (markup: string): Element => {
  document.body.innerHTML = markup;
  return document.body.firstElementChild?.querySelector('[data-target]') as Element;
};

describe('which controls the view-only sample holds', () => {
  it.each([
    ['a plain button', '<div><button data-target>Analyze drift</button></div>'],
    [
      'a save',
      '<div><button data-target data-next-cockpit-action="save">Save intent</button></div>',
    ],
    [
      'a turn on',
      '<div><button data-target data-next-cockpit-action="reading-on">Resume model calls</button></div>',
    ],
    [
      'a keep',
      '<div><button data-target data-next-cockpit-action="direction-keep">Keep</button></div>',
    ],
    [
      'a control inside a popover',
      '<div data-slot="popover-content"><button data-target data-next-cockpit-action="held-clear">Clear</button></div>',
    ],
    [
      'a control inside a disclosure panel',
      '<div class="ctl-disclosure"><div data-slot="accordion-content"><button data-target>Pause model calls</button></div></div>',
    ],
    [
      'a turn off',
      '<div><button data-target data-next-cockpit-action="reading-off">Pause model calls</button></div>',
    ],
    [
      'Summarize',
      '<div><button data-target data-next-cockpit-action="summary-start">Summarize</button></div>',
    ],
    [
      'Update summary',
      '<div><button data-target data-next-cockpit-action="summary-update">Update summary</button></div>',
    ],
    [
      'Summarize again',
      '<div><button data-target data-next-cockpit-action="summary-rerun">Summarize again</button></div>',
    ],
    [
      'Cancel a summary',
      '<div><button data-target data-next-cockpit-action="summary-cancel">Cancel</button></div>',
    ],
    [
      'Delete summary',
      '<div><button data-target data-next-cockpit-action="summary-delete">Delete summary</button></div>',
    ],
    [
      'Turn off summaries',
      '<div><button data-target data-next-cockpit-action="summary-off">Turn off summaries</button></div>',
    ],
    [
      'Turn summaries on',
      '<div><button data-target data-next-cockpit-action="summary-on">Turn summaries on</button></div>',
    ],
    ['a text box', '<div><textarea data-target></textarea></div>'],
    ['an input', '<div><input data-target /></div>'],
    [
      'the text inside a held button',
      '<div><button><span data-target>Remove</span></button></div>',
    ],
  ])('holds %s', (_name, markup) => {
    expect(isHeld(html(markup))).toBe(true);
  });

  it.each([
    ['a link', '<div><a href="#n=sessions" data-target>Sessions</a></div>'],
    ['a tour mark', '<div><button data-sample-tour data-target>2</button></div>'],
    [
      'show cited entries',
      '<div><button data-target data-next-cockpit-action="finding-jump">Show</button></div>',
    ],
    [
      'steer back',
      '<div><button data-target data-next-cockpit-action="steer-back">Steer back</button></div>',
    ],
    [
      'copy',
      '<div><button data-target data-next-cockpit-action="correction-copy">Copy</button></div>',
    ],
    [
      'an accordion trigger',
      '<div class="ctl-disclosure"><button data-slot="accordion-trigger" data-target>What is sent</button></div>',
    ],
    [
      'a collapsible trigger',
      '<div><button data-slot="collapsible-trigger" data-target>3 checks</button></div>',
    ],
    [
      'a popover trigger',
      '<div><button data-slot="popover-trigger" data-target>More</button></div>',
    ],
    ['plain text', '<div><p data-target>Words</p></div>'],
  ])('lets %s work', (_name, markup) => {
    expect(isHeld(html(markup))).toBe(false);
  });
});

describe('where the view-only sentence is drawn', () => {
  const rect = (top: number, height: number, left = 0, width = 800) =>
    ({ top, bottom: top + height, left, width, height, right: left + width }) as DOMRect;
  it('sits under a control with room below it', () => {
    expect(heldPosition(rect(100, 30, 40), rect(0, 2000), 900)).toEqual({ top: 136, left: 40 });
  });
  it('flips above a control at the foot of the viewport, so it is seen before it lapses', () => {
    expect(heldPosition(rect(860, 30, 40), rect(0, 2000), 900)).toEqual({
      bottom: 2000 - 860 + 6,
      left: 40,
    });
  });
});

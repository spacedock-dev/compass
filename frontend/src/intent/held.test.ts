import { describe, expect, it } from 'vitest';
import { createAnnouncer } from '../shell/announcer';
import { createFakeClock } from '../transport/testing';
import { createHeld, HELD_CUE_LIMIT } from './held';

/* The drift block's cue lane: stamped, restored for thirty seconds, bounded to the newest sixteen, and the
   announcement guard goes with the mark it guards. */
function setup() {
  const clock = createFakeClock();
  const announcer = createAnnouncer();
  const node = document.createElement('p');
  announcer.attach('cue', node);
  const held = createHeld({ clock, announcer });
  held.activate();
  return { clock, announcer, held, node };
}

describe('the cue lane', () => {
  it('keeps another reader session’s action feedback when its id shares a prefix', () => {
    const { held } = setup();
    held.actionFeedback.set('direction-add:claude:s10', 'A refusal for the other session.');
    held.actionFeedback.set('direction-goal:claude:s1:line:f1', 'A refusal for this session.');
    held.clearActionFeedback('claude:s1');
    expect(held.actionFeedback.get('direction-add:claude:s10')).toBe(
      'A refusal for the other session.',
    );
    expect(held.actionFeedback.has('direction-goal:claude:s1:line:f1')).toBe(false);
  });
  it('restores a mark for thirty seconds and not longer', () => {
    const { held, clock } = setup();
    held.mark('a', 'saved');
    expect(held.kind('a')).toBe('saved');
    clock.advance(29_999);
    expect(held.kind('a')).toBe('saved');
    clock.advance(1);
    expect(held.kind('a')).toBe('');
  });

  it('keeps only the newest sixteen marks', () => {
    const { held } = setup();
    expect(HELD_CUE_LIMIT).toBe(16);
    for (let index = 0; index < HELD_CUE_LIMIT + 3; index += 1)
      held.mark(`k${String(index)}`, 'saved');
    expect(held.kind('k0')).toBe('');
    expect(held.kind('k2')).toBe('');
    expect(held.kind('k3')).toBe('saved');
    expect(held.kind(`k${String(HELD_CUE_LIMIT + 2)}`)).toBe('saved');
  });

  it('moves a re-stamped mark to the newest end, so it is the last to go', () => {
    const { held } = setup();
    held.mark('first', 'saved');
    for (let index = 0; index < HELD_CUE_LIMIT - 1; index += 1)
      held.mark(`k${String(index)}`, 'saved');
    held.mark('first', 'saved');
    held.mark('extra', 'saved');
    expect(held.kind('first')).toBe('saved');
    expect(held.kind('k0')).toBe('');
  });

  it('drops the announcement guard with the mark, so a lapsed warning is a new warning', () => {
    const { held, clock, announcer, node } = setup();
    held.mark('a', 'saved');
    announcer.announce('a', 'Saved.');
    node.textContent = '';
    // The same sentence for the same standing mark is a repeat.
    announcer.announce('a', 'Saved.');
    expect(node.textContent).toBe('');
    clock.advance(30_000);
    announcer.announce('a', 'Saved.');
    expect(node.textContent).toBe('Saved.');
  });

  it('reports when a mark was stamped and nothing once it lapses', () => {
    const { held, clock } = setup();
    expect(held.stampOf('a')).toBe(0);
    held.mark('a', 'discard-armed');
    expect(held.stampOf('a')).toBe(clock.now());
    clock.advance(31_000);
    expect(held.stampOf('a')).toBe(0);
  });
});

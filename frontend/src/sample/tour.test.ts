import { describe, expect, it } from 'vitest';
import { TOUR } from './tour';

const note = (id: string) => TOUR.find((each) => each.id === id);
const words = (id: string) => `${note(id)?.title ?? ''} ${note(id)?.body ?? ''}`;

describe('the sample tour', () => {
  it('names no expected outcome: the sample saves a goal alone', () => {
    for (const each of TOUR) {
      expect(`${each.title} ${each.body}`).not.toMatch(/outcome|expect/i);
    }
  });

  it('says how a reader sets the goal for their own session, and that the sample set it once', () => {
    const intent = words('intent');
    expect(intent).toContain('what should be true when the work is done');
    expect(intent).toContain('Every issue in the milestone is closed');
    for (const way of ['type', 'one of your prompts', 'Find goal', '/goal']) {
      expect(intent).toContain(way);
    }
  });

  it('says the summary phases start closed, and that a reader presses one to read it', () => {
    expect(words('summary')).toMatch(/start closed/);
    expect(words('summary')).toMatch(/press a phase/i);
  });

  it('says the three phases that hold the one departure from the goal', () => {
    const phase = words('phase');
    expect(phase).toContain('three phases');
    expect(phase).toContain('goal');
    expect(phase).toContain('the one departure');
  });

  it('says what a departure rests on and that it is not a check the work was done', () => {
    expect(words('departure')).toContain('never a verification');
  });

  it('says Steer back writes from the goal and leaves pasting it to the reader', () => {
    const steer = words('steer');
    expect(steer).toContain('your goal');
    expect(steer).toContain('paste it into the session yourself');
  });

  it('uses plain sentence case with no em dashes and no tracker keys', () => {
    for (const each of TOUR) {
      expect(`${each.title} ${each.body}`).not.toMatch(/—|read against|DRC-\d+/);
    }
  });
});

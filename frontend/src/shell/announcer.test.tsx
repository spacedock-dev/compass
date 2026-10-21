import { render, screen } from '@testing-library/react';
import { StrictMode, useEffect } from 'react';
import { describe, expect, it } from 'vitest';
import {
  ANNOUNCEMENT_LIMIT,
  createAnnouncer,
  REGION_IDS,
  type Announcer,
  type RegionName,
} from './announcer';
import { AnnouncerProvider, LiveRegions } from './LiveRegions';
import { useAnnouncer } from './announcerContext';

function attached(
  announcer: Announcer,
  regions: readonly RegionName[] = ['attention', 'copy', 'raise', 'cue', 'alert'],
) {
  const nodes = {} as Record<RegionName, HTMLElement>;
  for (const region of regions) {
    nodes[region] = document.createElement('p');
    announcer.attach(region, nodes[region]);
  }
  return nodes;
}

describe('a sentence is spoken once per standing key', () => {
  it('writes the first sentence and suppresses a repeat of it', () => {
    const announcer = createAnnouncer();
    const nodes = attached(announcer);
    announcer.announce('save:goal', 'Saved.');
    expect(nodes.cue.textContent).toBe('Saved.');
    nodes.cue.textContent = 'something else';
    announcer.announce('save:goal', 'Saved.');
    expect(nodes.cue.textContent).toBe('something else');
  });

  it('keys the guard by mark, because the cue sentences are the same for every field', () => {
    const announcer = createAnnouncer();
    const nodes = attached(announcer);
    announcer.announce('save:goal', 'Saved.');
    nodes.cue.textContent = '';
    announcer.announce('save:outcome', 'Saved.');
    expect(nodes.cue.textContent).toBe('Saved.');
  });

  it('speaks a changed sentence under the same key', () => {
    const announcer = createAnnouncer();
    const nodes = attached(announcer);
    announcer.announce('save:goal', 'Saving.');
    announcer.announce('save:goal', 'Saved.');
    expect(nodes.cue.textContent).toBe('Saved.');
  });

  it('says it again after the mark is dropped, as a pending control does on its next press', () => {
    const announcer = createAnnouncer();
    const nodes = attached(announcer);
    announcer.announce('pending:save', 'Saving the line.');
    announcer.forget('pending:save');
    nodes.cue.textContent = '';
    announcer.announce('pending:save', 'Saving the line.');
    expect(nodes.cue.textContent).toBe('Saving the line.');
  });

  it('says nothing for an empty sentence', () => {
    const announcer = createAnnouncer();
    const nodes = attached(announcer);
    announcer.announce('save:goal', '');
    expect(nodes.cue.textContent).toBe('');
  });

  it('remembers only the last sixteen keys, oldest first out', () => {
    expect(ANNOUNCEMENT_LIMIT).toBe(16);
    const announcer = createAnnouncer();
    const nodes = attached(announcer);
    for (let index = 0; index < ANNOUNCEMENT_LIMIT + 1; index += 1)
      announcer.announce(`k${index}`, `Sentence ${index}.`);
    nodes.cue.textContent = '';
    announcer.announce('k1', 'Sentence 1.');
    expect(nodes.cue.textContent).toBe('');
    announcer.announce('k0', 'Sentence 0.');
    expect(nodes.cue.textContent).toBe('Sentence 0.');
  });

  it('does not record a sentence as spoken when no region could carry it', () => {
    const announcer = createAnnouncer();
    announcer.announce('save:goal', 'Saved.');
    const nodes = attached(announcer);
    announcer.announce('save:goal', 'Saved.');
    expect(nodes.cue.textContent).toBe('Saved.');
  });
});

describe('the assertive region carries the armed warning alone', () => {
  it('writes an assertive sentence to the alert region and leaves the status region alone', () => {
    const announcer = createAnnouncer();
    const nodes = attached(announcer);
    announcer.announce('discard:goal', 'Nothing has been deleted yet.', { assertive: true });
    expect(nodes.alert.textContent).toBe('Nothing has been deleted yet.');
    expect(nodes.cue.textContent).toBe('');
  });

  it('retracts the standing warning silently when its arm ends, and only for that arm', () => {
    const announcer = createAnnouncer();
    const nodes = attached(announcer);
    announcer.announce('discard:goal', 'Nothing has been deleted yet.', { assertive: true });
    announcer.retractArmed('discard:outcome');
    expect(nodes.alert.textContent).toBe('Nothing has been deleted yet.');
    announcer.retractArmed('discard:goal');
    expect(nodes.alert.textContent).toBe('');
    announcer.retractArmed();
    expect(nodes.alert.textContent).toBe('');
  });

  it('forgets the warning with its mark so a lapsed arm pressed again is a new warning', () => {
    const announcer = createAnnouncer();
    const nodes = attached(announcer);
    announcer.announce('discard:goal', 'Nothing has been deleted yet.', { assertive: true });
    announcer.forget('discard:goal');
    expect(nodes.alert.textContent).toBe('');
    announcer.announce('discard:goal', 'Nothing has been deleted yet.', { assertive: true });
    expect(nodes.alert.textContent).toBe('Nothing has been deleted yet.');
  });
});

describe('the other regions are written directly', () => {
  it('writes the attention, copy and raise sentences without the guard, as each press is its own act', () => {
    const announcer = createAnnouncer();
    const nodes = attached(announcer);
    announcer.say('copy', 'Copied session ID abc');
    nodes.copy.textContent = '';
    announcer.say('copy', 'Copied session ID abc');
    expect(nodes.copy.textContent).toBe('Copied session ID abc');
    announcer.say('raise', 'Raise requested');
    announcer.say('attention', 'Attention updated: 1 need you');
    expect(nodes.raise.textContent).toBe('Raise requested');
    expect(nodes.attention.textContent).toBe('Attention updated: 1 need you');
  });

  it('writes a repeated sentence as a new text node, which is what lets a reader’s software speak it again', () => {
    const announcer = createAnnouncer();
    const nodes = attached(announcer);
    announcer.say('copy', 'Copied');
    const first = nodes.copy.firstChild;
    announcer.say('copy', 'Copied');
    expect(nodes.copy.firstChild).not.toBe(first);
  });

  it('ignores an empty sentence and a region that is not attached', () => {
    const announcer = createAnnouncer();
    const nodes = attached(announcer, ['copy']);
    announcer.say('copy', '');
    expect(nodes.copy.textContent).toBe('');
    expect(() => announcer.say('raise', 'x')).not.toThrow();
  });

  it('stops writing to a node once it is detached', () => {
    const announcer = createAnnouncer();
    const node = document.createElement('p');
    const detach = announcer.attach('copy', node);
    detach();
    announcer.say('copy', 'late');
    expect(node.textContent).toBe('');
  });
});

describe('the five regions are stable nodes outside the replaceable page', () => {
  it('draws each region once with the politeness the legacy page gave it, empty', () => {
    const announcer = createAnnouncer();
    const { container } = render(
      <AnnouncerProvider announcer={announcer}>
        <LiveRegions />
      </AnnouncerProvider>,
    );
    const expectations: readonly [RegionName, string, string][] = [
      ['attention', 'status', 'polite'],
      ['copy', 'status', 'polite'],
      ['raise', 'status', 'polite'],
      ['cue', 'status', 'polite'],
      ['alert', 'alert', 'assertive'],
    ];
    for (const [region, role, live] of expectations) {
      const node = container.querySelector(`#${REGION_IDS[region]}`);
      expect(node, region).not.toBeNull();
      expect(node?.getAttribute('role')).toBe(role);
      expect(node?.getAttribute('aria-live')).toBe(live);
      expect(node?.getAttribute('aria-atomic')).toBe('true');
      expect(node?.textContent).toBe('');
    }
  });

  it('keeps the same nodes, with their text, while the surrounding page re-renders', () => {
    const announcer = createAnnouncer();
    const view = (label: string) => (
      <AnnouncerProvider announcer={announcer}>
        <main>{label}</main>
        <LiveRegions />
      </AnnouncerProvider>
    );
    const { container, rerender } = render(view('one'));
    const before = container.querySelector(`#${REGION_IDS.cue}`);
    announcer.announce('k', 'A sentence.');
    rerender(view('two'));
    const after = container.querySelector(`#${REGION_IDS.cue}`);
    expect(after).toBe(before);
    expect(after?.textContent).toBe('A sentence.');
  });
});

describe('an announcement made on mount is made once under StrictMode', () => {
  /* The region's text is written through `textContent`, so a counting setter sees every write. */
  function countingRegion() {
    const node = document.createElement('p');
    const writes: string[] = [];
    Object.defineProperty(node, 'textContent', {
      configurable: true,
      get: () => writes.at(-1) ?? '',
      set: (value: string) => void writes.push(value),
    });
    return { node, writes };
  }

  function Announces({ announcer }: { readonly announcer: Announcer }) {
    useEffect(() => {
      announcer.announce('mount:cue', 'Shown once.');
    }, [announcer]);
    return null;
  }

  it('writes the region one time although the effect runs twice', () => {
    const announcer = createAnnouncer();
    const { node, writes } = countingRegion();
    announcer.attach('cue', node);
    render(
      <StrictMode>
        <Announces announcer={announcer} />
      </StrictMode>,
    );
    expect(writes).toEqual(['Shown once.']);
  });

  it('would write twice without the guard, which is what the test above is proving', () => {
    const { node, writes } = countingRegion();
    function Unguarded() {
      useEffect(() => {
        node.textContent = 'Shown once.';
      }, []);
      return null;
    }
    render(
      <StrictMode>
        <Unguarded />
      </StrictMode>,
    );
    expect(writes).toHaveLength(2);
  });
});

describe('a component reaches the announcer through the shell', () => {
  it('hands the provided announcer to a descendant, and refuses to run without one', () => {
    const announcer = createAnnouncer();
    let seen: Announcer | null = null;
    function Reader() {
      seen = useAnnouncer();
      return <span>reader</span>;
    }
    render(
      <AnnouncerProvider announcer={announcer}>
        <Reader />
      </AnnouncerProvider>,
    );
    expect(screen.getByText('reader')).toBeInTheDocument();
    expect(seen).toBe(announcer);
    expect(() => render(<Reader />)).toThrow(/AnnouncerProvider/);
  });
});

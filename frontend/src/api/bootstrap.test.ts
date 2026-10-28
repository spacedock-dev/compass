// @vitest-environment jsdom
import { describe, expect, it } from 'vitest';
import {
  FOCUS_META_SELECTOR,
  dataPath,
  nextFiniteNumber,
  nextNumber,
  payloadAsks,
  payloadSessions,
  readBootstrap,
} from './bootstrap';

function documentWithFocus(content: string | null): Pick<Document, 'querySelector'> {
  const meta = document.implementation.createHTMLDocument('x');
  if (content !== null) {
    const element = meta.createElement('meta');
    element.setAttribute('name', 'compass-focus');
    element.setAttribute('content', content);
    meta.head.append(element);
  }
  return meta;
}

describe('page bootstrap', () => {
  it('admits all=1 only when the query value is exactly 1', () => {
    expect(readBootstrap('?all=1', null).showAll).toBe(true);
    for (const search of ['', '?all=', '?all=true', '?all=2', '?all=01', '?other=1', '?ALL=1']) {
      expect(readBootstrap(search, null).showAll, search).toBe(false);
    }
  });

  it('never forwards unrelated query parameters to the data route', () => {
    expect(dataPath({ showAll: false, usage: false })).toBe('/api/data');
    expect(dataPath({ showAll: true, usage: false })).toBe('/api/data?all=1');
    expect(dataPath({ showAll: false, usage: true })).toBe('/api/data?usage=1');
    expect(dataPath({ showAll: true, usage: true })).toBe('/api/data?all=1&usage=1');
  });

  it('reads the focus capability from the page marker and trims it', () => {
    expect(FOCUS_META_SELECTOR).toBe('meta[name="compass-focus"]');
    expect(readBootstrap('', documentWithFocus('  tok  ')).focusCapability).toBe('tok');
  });

  it('treats a missing marker, empty content or no document as an empty capability', () => {
    expect(readBootstrap('', documentWithFocus(null)).focusCapability).toBe('');
    expect(readBootstrap('', documentWithFocus('   ')).focusCapability).toBe('');
    expect(readBootstrap('', null).focusCapability).toBe('');
    const throwing = {
      querySelector: () => {
        throw new Error('bad selector');
      },
    } as unknown as Pick<Document, 'querySelector'>;
    expect(readBootstrap('', throwing).focusCapability).toBe('');
  });
});

describe('number helpers stay distinct', () => {
  it('nextNumber accepts only finite numbers and returns null otherwise', () => {
    expect(nextNumber(3)).toBe(3);
    expect(nextNumber(0)).toBe(0);
    for (const value of [undefined, null, '3', NaN, Infinity, {}, []])
      expect(nextNumber(value)).toBeNull();
  });

  it('nextFiniteNumber coerces and falls back to zero, so it never proves a measurement', () => {
    expect(nextFiniteNumber('3')).toBe(3);
    expect(nextFiniteNumber(undefined)).toBe(0);
    expect(nextFiniteNumber(NaN)).toBe(0);
    expect(nextFiniteNumber(null)).toBe(0);
  });
});

describe('payload collections', () => {
  it('keeps only object rows and distinguishes a missing collection from an empty one', () => {
    expect(payloadSessions({ sessions: [{ sid: 'a' }, null, 4, [], 'x'] })).toEqual({
      present: true,
      rows: [{ sid: 'a' }],
    });
    expect(payloadSessions({ sessions: [] })).toEqual({ present: true, rows: [] });
    expect(payloadSessions({})).toEqual({ present: false, rows: [] });
    expect(payloadSessions({ sessions: 'nope' })).toEqual({ present: false, rows: [] });
    expect(payloadSessions(null)).toEqual({ present: false, rows: [] });
    expect(payloadSessions([])).toEqual({ present: false, rows: [] });
    expect(payloadAsks({ asks: [{ id: 'q' }, 1] })).toEqual({ present: true, rows: [{ id: 'q' }] });
    expect(payloadAsks({})).toEqual({ present: false, rows: [] });
  });
});

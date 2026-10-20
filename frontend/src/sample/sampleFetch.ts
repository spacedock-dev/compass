import type { FetchLike } from '../api/client';
import { datedClock } from '../observed/values';
import type { SampleFixture } from './fixture';

/* The sample session's whole server. A read answers from the fixture, composing a Steer back correction
   answers the correction Compass's composer made from the stored reading, and recording a copy of it is
   accepted and goes nowhere. Anything else the page can send is refused, so a press that reaches the
   network by a path the view-only guard missed still changes nothing and says why. */
const COMPOSE = '/api/correction';
const COPIED = '/api/correction/copied';

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' },
  });
}

/* The stored correction keeps each time as its moment (`CLOCK_MARK` in scripts/build_sample_fixture.py), because
   the real route draws times on the reader's clock (owner, 2026-10-20) and a text drawn in the capture's zone would
   disagree with the page beside it. Drawn here by `datedClock`, the page's copy of the route's rule, against the
   moment the sample is frozen at. */
const CLOCK_MARK = /\{\{clock:(\d+(?:\.\d+)?)\}\}/g;

export function drawCorrection(correction: Record<string, unknown>, frozen: number): unknown {
  const parts = correction['parts'];
  if (!Array.isArray(parts)) return correction;
  return {
    ...correction,
    parts: parts.map((part) =>
      typeof part === 'string'
        ? part.replace(CLOCK_MARK, (_, at: string) => datedClock(Number(at), frozen))
        : part,
    ),
  };
}

export function createSampleFetch(fixture: SampleFixture): FetchLike {
  return (url, init) => {
    const path = url.split('?')[0] ?? url;
    const query = new URLSearchParams(url.split('?')[1] ?? '');
    const method = (init?.method ?? 'GET').toUpperCase();
    if (method === 'GET') {
      if (path === '/api/data') return Promise.resolve(json(fixture.board));
      if (path === '/api/project-context')
        return Promise.resolve(json(query.has('prompts') ? fixture.prompts : fixture.context));
      if (path === '/api/session-record') {
        const before = query.get('before');
        if (before === null) return Promise.resolve(json(fixture.record));
        /* Every older page was captured to the record's start. A cursor the capture never named is answered
           the way the server answers a cursor it cannot read, so the page starts again from the newest page;
           answering it with an empty start would say entries do not exist when they were never asked for. */
        const older = Object.hasOwn(fixture.older ?? {}, before) ? fixture.older?.[before] : null;
        return Promise.resolve(
          json(
            older ?? {
              ...fixture.record,
              entries: [],
              next: null,
              reached_start: false,
              bound: null,
              scanned_bytes: 0,
              state: 'stale',
            },
          ),
        );
      }
      return Promise.resolve(json({}, 404));
    }
    if (path === COMPOSE)
      return Promise.resolve(
        json(drawCorrection(fixture.correction, Number(fixture.board['generated']))),
      );
    if (path === COPIED) return Promise.resolve(json({ ok: true }));
    return Promise.resolve(
      json(
        { ok: false, reason: 'sample', why: 'This is a sample session. Nothing in it can be run.' },
        403,
      ),
    );
  };
}

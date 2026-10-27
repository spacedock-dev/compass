import { createContext } from 'react';
import raw from './session.fixture.json';

/* What the Session page asks the server for, answered once, in advance. Built by
   `scripts/build_sample_fixture.py` from a real server reading the anonymized session in
   `sample-session/`, never edited by hand. `record` is the newest page of the session's record and
   `older` every page before it, keyed by the cursor the page before names (`older-1`, `older-2`, ...),
   so a citation anywhere in the sample can be found. A sample whose record is one page has none. */
export interface SampleFixture {
  readonly board: Record<string, unknown>;
  readonly context: Record<string, unknown>;
  readonly prompts: Record<string, unknown>;
  readonly record: Record<string, unknown>;
  readonly older?: Readonly<Record<string, Record<string, unknown>>>;
  readonly correction: Record<string, unknown>;
}

export const SAMPLE_FIXTURE = raw as unknown as SampleFixture;

/* The fixture the sample draws. The page always draws SAMPLE_FIXTURE; a story provides another to show a
   longer record than the shipped one holds. */
export const SampleFixtureContext = createContext<SampleFixture>(SAMPLE_FIXTURE);

import type { ApiClient } from './client';
import type { ReadingRequest } from './types';

export function turnOffReadings(client: Pick<ApiClient, 'postReading'>, signal?: AbortSignal) {
  return client.postReading(
    { consent: 'off', press: true, observer_model: 1 } as unknown as ReadingRequest,
    signal,
  );
}

/* The page's switch for the GitHub read of a pull request's CI checks: one marker on the server, read back on
   the board's routes. The flag `--no-ci-read` holds it off whatever is sent. */
export function setCiRead(
  client: Pick<ApiClient, 'postReading'>,
  answer: 'on' | 'off',
  signal?: AbortSignal,
) {
  return client.postReading(
    { ci_read: answer, press: true, observer_model: 1 } as unknown as ReadingRequest,
    signal,
  );
}

export function resumeModelCalls(client: Pick<ApiClient, 'postReading'>, signal?: AbortSignal) {
  return client.postReading(
    { consent: 'on', press: true, observer_model: 1 } as unknown as ReadingRequest,
    signal,
  );
}

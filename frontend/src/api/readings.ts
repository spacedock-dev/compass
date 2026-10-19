import type { ApiClient } from './client';
import type { ReadingRequest } from './types';

export function turnOffReadings(client: Pick<ApiClient, 'postReading'>, signal?: AbortSignal) {
  return client.postReading(
    { consent: 'off', press: true, observer_model: 1 } as unknown as ReadingRequest,
    signal,
  );
}

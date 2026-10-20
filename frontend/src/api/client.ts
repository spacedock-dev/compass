import { dataPath } from './bootstrap';
import type {
  AnnotateReceipt,
  AnnotateRequest,
  AnnotationsBody,
  AnswerReceipt,
  ApiResult,
  CorrectionReceipt,
  DirectionReceipt,
  DirectionBatchReceipt,
  DismissReceipt,
  FocusOutcome,
  FocusReceipt,
  InteractionOrigin,
  NotifyReceipt,
  PayloadData,
  ProjectContext,
  ReadingCancelReceipt,
  ReadingReceipt,
  ReadingRequest,
  UnaskedGrantRequest,
  SessionIdentity,
  SessionRecord,
  SummaryReceipt,
  SummaryRequest,
  TripwireReceipt,
  TripwireRequest,
} from './types';

export type FetchLike = (url: string, init?: RequestInit) => Promise<Response>;

const REVISION_HEADER = 'X-Compass-Revision';

/* Raced against the signal as well as handed it, so a fetch that ignores the
   signal still releases its caller at the bound. The listener is removed on
   every path, or a long-lived signal would collect one per request. */
export function fetchBounded(
  fetchImpl: FetchLike,
  url: string,
  init: RequestInit | undefined,
  signal: AbortSignal | undefined,
): Promise<Response> {
  if (!signal) return fetchImpl(url, init);
  if (signal.aborted) return Promise.reject(new Error('bounded'));
  let request: Promise<Response>;
  try {
    request = fetchImpl(url, { ...init, signal });
  } catch (error) {
    return Promise.reject(error instanceof Error ? error : new Error(String(error)));
  }
  return new Promise<Response>((resolve, reject) => {
    const onAbort = () => reject(new Error('bounded'));
    signal.addEventListener('abort', onAbort);
    request.then(
      (value) => {
        signal.removeEventListener('abort', onAbort);
        resolve(value);
      },
      (error: unknown) => {
        signal.removeEventListener('abort', onAbort);
        reject(error instanceof Error ? error : new Error(String(error)));
      },
    );
  });
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

async function readText(response: Response): Promise<string> {
  try {
    return await response.text();
  } catch {
    return '';
  }
}

function parseLoose(text: string): unknown {
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return text;
  }
}

/* Status and body stay separate on a refusal because `send_error` may answer
   in HTML, and a failure is never rewritten as an empty healthy body. */
async function settle<T>(
  request: () => Promise<Response>,
  signal: AbortSignal | undefined,
  readRevision: boolean,
): Promise<ApiResult<T>> {
  let response: Response;
  try {
    response = await request();
  } catch {
    return signal?.aborted ? { kind: 'aborted' } : { kind: 'network-error' };
  }
  const text = await readText(response);
  if (signal?.aborted) return { kind: 'aborted' };
  if (!response.ok) return { kind: 'http-error', status: response.status, body: parseLoose(text) };
  let body: unknown;
  try {
    body = JSON.parse(text) as unknown;
  } catch {
    return { kind: 'malformed', status: response.status };
  }
  if (!isRecord(body)) return { kind: 'malformed', status: response.status };
  return {
    kind: 'ok',
    status: response.status,
    body: body as T,
    revision: readRevision ? (response.headers.get(REVISION_HEADER) ?? '') : '',
  };
}

export interface ProjectContextQuery {
  readonly project: string;
  /** The exact `harness:sid` key of the focused session, when the read is session-scoped. */
  readonly session?: string;
  readonly prompts?: boolean;
  readonly refresh?: boolean;
  readonly observerModel?: boolean;
  readonly signal?: AbortSignal;
}

export interface SessionRecordQuery {
  readonly project: string;
  readonly session: string;
  readonly limit?: number;
  readonly before?: string;
  readonly signal?: AbortSignal;
}

export function createApiClient(deps: { readonly fetch: FetchLike }) {
  const get = <T>(path: string, signal: AbortSignal | undefined, readRevision = false) =>
    settle<T>(() => fetchBounded(deps.fetch, path, undefined, signal), signal, readRevision);

  const post = <T>(
    path: string,
    body: unknown,
    signal?: AbortSignal,
    headers: Record<string, string> = {},
  ) =>
    settle<T>(
      () =>
        fetchBounded(
          deps.fetch,
          path,
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...headers },
            body: JSON.stringify(body),
          },
          signal,
        ),
      signal,
      false,
    );

  return {
    /** The one route that reads `X-Compass-Revision`. */
    getData: (options: {
      readonly showAll: boolean;
      readonly usage: boolean;
      readonly signal?: AbortSignal;
    }) => get<PayloadData>(dataPath(options), options.signal, true),

    getProjectContext(query: ProjectContextQuery) {
      let path = `/api/project-context?project=${encodeURIComponent(query.project)}`;
      if (query.session) path += `&session=${encodeURIComponent(query.session)}`;
      if (query.refresh) path += '&refresh=1';
      if (query.observerModel) path += '&observer_model=1';
      if (query.prompts) path += '&prompts=1';
      return get<ProjectContext>(path, query.signal);
    },

    getSessionRecord(query: SessionRecordQuery) {
      const params = new URLSearchParams({ project: query.project, session: query.session });
      if (query.limit !== undefined) params.set('limit', String(query.limit));
      if (query.before !== undefined) params.set('before', query.before);
      return get<SessionRecord>(`/api/session-record?${params.toString()}`, query.signal);
    },

    getAnnotations: (options: { readonly signal?: AbortSignal }) =>
      get<AnnotationsBody>('/api/annotations', options.signal),

    getInteractionOrigin: (identity: SessionIdentity, signal?: AbortSignal) =>
      get<InteractionOrigin>(
        `/api/interaction/origin?harness=${encodeURIComponent(identity.harness)}&sid=${encodeURIComponent(identity.sid)}`,
        signal,
      ),

    postAnnotate: (body: AnnotateRequest, signal?: AbortSignal) =>
      post<AnnotateReceipt>('/api/annotate', body, signal),
    postDirection: (body: SessionIdentity & { readonly fact_id: string }, signal?: AbortSignal) =>
      post<DirectionReceipt>('/api/direction', body, signal),
    postDirections: (
      body: SessionIdentity & { readonly fact_ids: readonly string[] },
      signal?: AbortSignal,
    ) => post<DirectionBatchReceipt>('/api/direction', body, signal),
    postReading: (body: ReadingRequest | UnaskedGrantRequest, signal?: AbortSignal) =>
      post<ReadingReceipt>('/api/reading', body, signal),
    postReadingCancel: (
      body: SessionIdentity & {
        readonly job: string;
        readonly press: true;
        readonly observer_model: 1;
      },
      signal?: AbortSignal,
    ) => post<ReadingCancelReceipt>('/api/reading/cancel', body, signal),
    /* A summary start, Update summary, Summarize again, or the summary grant's off and on
       (docs/design-session-summary.md#requests-and-replies). */
    postSummary: (body: SummaryRequest, signal?: AbortSignal) =>
      post<SummaryReceipt>('/api/summary', body, signal),
    postSummaryCancel: (body: SessionIdentity, signal?: AbortSignal) =>
      post<SummaryReceipt>('/api/summary/cancel', body, signal),
    postSummaryDelete: (body: SessionIdentity, signal?: AbortSignal) =>
      post<SummaryReceipt>('/api/summary/delete', body, signal),
    /* `utc_offset_minutes` is the reader's zone, which the correction's times are drawn in; without it the
       server falls back to its own clock. */
    postCorrection: (
      body: SessionIdentity & { readonly utc_offset_minutes?: number },
      signal?: AbortSignal,
    ) => post<CorrectionReceipt>('/api/correction', body, signal),
    postCorrectionCopied: (
      body: SessionIdentity & { readonly text: string },
      signal?: AbortSignal,
    ) => post<Record<string, unknown>>('/api/correction/copied', body, signal),
    postTripwire: (body: TripwireRequest, signal?: AbortSignal) =>
      post<TripwireReceipt>('/api/tripwire', body, signal),
    postLane: (
      body: { readonly supported: boolean; readonly permission: string },
      signal?: AbortSignal,
    ) => post<Record<string, unknown>>('/api/lane', body, signal),
    postAnswer: (body: { readonly id: string; readonly index: number }, signal?: AbortSignal) =>
      post<AnswerReceipt>('/api/answer', body, signal),
    postDismiss: (body: SessionIdentity, signal?: AbortSignal) =>
      post<DismissReceipt>('/api/dismiss', body, signal),
    postNotify: (
      body: { readonly message: string; readonly session_id: string },
      signal?: AbortSignal,
    ) => post<NotifyReceipt>('/api/notify', body, signal),

    /* One attempt per call. 429 means wait and 403 means this document is
       stale; nothing else the server says is actionable from here. A missing
       capability sends nothing, because the request could only be refused. */
    async focus(options: {
      readonly identity: SessionIdentity;
      readonly capability: string;
      readonly signal?: AbortSignal;
    }): Promise<FocusOutcome> {
      const capability = options.capability.trim();
      if (!capability) return 'unavailable';
      const result = await post<FocusReceipt>(
        '/api/focus',
        { harness: options.identity.harness, sid: options.identity.sid },
        options.signal,
        { 'X-Compass-Capability': capability },
      );
      if (result.kind === 'http-error') {
        if (result.status === 429) return 'throttled';
        if (result.status === 403) return 'stale';
        return 'failed';
      }
      if (result.kind !== 'ok') return 'failed';
      return result.body.focused === true ? 'sent' : 'declined';
    },
  };
}

export type ApiClient = ReturnType<typeof createApiClient>;

type Fetch = (url: string, init?: { signal?: AbortSignal }) => Promise<Response>;
interface Options {
  fetchImpl?: Fetch;
  limit?: number;
  concurrency?: number;
  deadlineMs?: number;
  requestTimeoutMs?: number;
  timeoutMs?: number;
  pauseMs?: number;
  skip?: RegExp | null;
  entries?: string[];
}
export interface WarmUpSummary {
  fetched: number;
  skipped: number;
  stoppedBy: 'complete' | 'limit' | 'deadline';
}
export function referencedPaths(body: string): string[];
export function loadModuleGraph(
  origin: string,
  entries: string[],
  options?: Options,
): Promise<WarmUpSummary>;
export function waitForIndex(origin: string, options?: Options): Promise<void>;
export function warmDevServer(origin: string, options?: Options): Promise<WarmUpSummary>;
export function describeWarmUp(summary: WarmUpSummary): string;

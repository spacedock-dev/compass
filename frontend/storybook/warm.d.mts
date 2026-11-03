type Fetch = (url: string) => Promise<Response>;
interface Options {
  fetchImpl?: Fetch;
  limit?: number;
  concurrency?: number;
  timeoutMs?: number;
  pauseMs?: number;
}
export function referencedPaths(body: string): string[];
export function loadModuleGraph(
  origin: string,
  entries: string[],
  options?: Options,
): Promise<string[]>;
export function waitForIndex(origin: string, options?: Options): Promise<void>;
export function warmDevServer(origin: string, options?: Options): Promise<string[]>;

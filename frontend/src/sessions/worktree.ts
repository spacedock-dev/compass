/* The linked worktree a session ran in, as the collector published it: a directory name, or nothing for a
   main checkout. The project label no longer carries it, so this is what keeps two sessions on one
   repository apart. */
export function worktreeOf(row: Readonly<Record<string, unknown>> | null | undefined): string {
  const value = row?.['worktree'];
  return typeof value === 'string' ? value.trim() : '';
}

/* The verb each harness's own CLI takes to re-enter a session. Both were read
   off `--help` on the installed CLI, not off documentation: Claude Code takes
   `--resume <session-id>` and Codex takes `resume <SESSION_ID>`. A harness absent
   from this table gets no control at all, because a guessed verb costs the reader
   a failed command on top of the hunt it was meant to replace. */
const COMMANDS = new Map<string, (token: string) => string>([
  ['claude', (token) => `claude --resume ${token}`],
  ['codex', (token) => `codex resume ${token}`],
]);

/* The published token is checked again here although the collector checked it
   first, because the page treats the payload as untrusted and this is the one
   string on the board that becomes a shell command in someone else's terminal.
   Same grammar as the server's RESUME_TOKEN_PATTERN, first character included: a
   `-`-leading token is one word to a shell but a flag to the CLI, and both
   harnesses have a valueless flag that turns off their permission checks. Keep
   the two in step. */
const RESUME_TOKEN = /^[A-Za-z0-9_][A-Za-z0-9_-]{0,63}$/;

export function validResumeToken(token: unknown): token is string {
  return typeof token === 'string' && RESUME_TOKEN.test(token);
}

export function resumeCommand(harness: string, resumeId: string): string {
  const build = COMMANDS.get(harness);
  return build && validResumeToken(resumeId) ? build(resumeId) : '';
}

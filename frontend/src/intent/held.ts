import { CUE_TTL_MS, createKeyedState, type KeyedState } from '../controls/keyedState';
import type { Announcer } from '../shell/announcer';
import type { Clock } from '../transport/ports';

/* Everything the Intent panel holds for the reader that a redraw must not lose, kept in memory and never
   written to browser storage (docs/design-reader-state.md names each row). The board redraws on every
   revision, so a draft held by a node would go with it; these are held outside the rendered tree and
   keyed by the exact harness and session id, so one session's words never reach another's box.

   One notification channel, a version number: the panel re-reads what it draws whenever anything here
   changes. A keystroke changes it too, which is cheap because the editors are uncontrolled: React
   re-renders around a native textarea and leaves its text, caret, selection and undo history alone. */

export type LinesAnswer = 'keep' | 'clear' | null;

/* A prompt the reader chose from "Use your prompt" or a direction they used as their goal, as the fact's
   id, words and time. It stands in the goal box as a pending adoption and is not the box's typed draft, so
   the box reads untouched and Save intent adopts it. `direction` marks one that came from a later
   direction, which the menu never listed, so it is not checked against the menu. */
export interface ChosenPrompt {
  readonly factId: string;
  readonly text: string;
  readonly at: number | null;
  readonly cut?: boolean;
  readonly direction?: boolean;
  linesAnswer?: LinesAnswer;
}

export interface PromptChoice {
  readonly factId: string;
  readonly text: string;
  readonly at: number | null;
  readonly cut: boolean;
}

/* The prompt menu's list, fetched once per opening and never by a poll. `open` is whether the reader's
   own opening gesture is still standing, so a list that arrives after the menu was dismissed does not pop
   it open again. */
export interface PromptList {
  readonly pending: boolean;
  readonly open: boolean;
  readonly choices: readonly PromptChoice[];
  /** The read itself failed, as distinct from a read that found none of the reader's prompts. */
  readonly failed?: boolean;
  readonly bounded?: boolean;
}

/* A later direction opened for review as one pending outcome line. Its box carries no `maxlength`, so
   nothing truncates it; a line over the store's bound is refused at the save, never cut. */
export interface DirectionLine {
  readonly recordOrigin?: boolean;
  readonly factId: string;
  readonly n: string | null;
  readonly later: boolean;
  opening?: boolean;
  error?: string;
  /* The whole text as the reader edits it. Mutated in place, as a reply that lands while the reader is still
     typing must find what they typed, and the next render reads it from the same entry. */
  text?: string;
  clipped?: boolean;
  replace?: number | null;
  pending?: boolean;
  cue?: string;
}

export interface OpenedDirection {
  readonly text: string;
  readonly clipped: boolean;
}

/* The whole text of each direction Keep opened before settling, by fact id, the ids the question drew
   whole, and the revision the page drew them against. */
export interface DirectionWhole {
  readonly texts: Map<string, OpenedDirection>;
  drawn: ReadonlySet<string>;
  revision: number | null;
}

/* What a reader-requested action's last press said, per session, and whether it is still open. The lane
   the drift block's reading feedback shares: Keep writes it, and so does Analyze. */
export interface RequestNote {
  pending?: boolean;
  message?: string;
  refusal?: boolean;
  announced?: boolean;
  notice?: Readonly<Record<string, unknown>> | null;
  [field: string]: unknown;
}

/* The drift block's save cue lane: a stamped kind per key, restored for 30 seconds and bounded to the
   newest sixteen, as the row controls' cues are. Typing clears a save cue, the discard arm lapses on the
   same window, and the sentence a discard earns is the server's. */
export const HELD_CUE_LIMIT = 16;
export type CueKind = string;

export interface HeldDeps {
  readonly clock: Clock;
  readonly announcer: Announcer;
}

export function createHeld(deps: HeldDeps) {
  const { clock, announcer } = deps;
  const goals = new Map<string, string>();
  const lines = new Map<string, string[]>();
  /* Which saved line each draft line came from, by position, or null for one added here. Kept beside the
     draft so the save can say it, and the store can give a line its own source when two lines share
     text: deleting the first of two lends the survivor its own entry, not the deleted one's. */
  const origins = new Map<string, (number | null)[]>();
  const chosen = new Map<string, ChosenPrompt>();
  const picks = new Map<string, string>();
  const prompts = new Map<string, PromptList>();
  const directions = new Map<string, DirectionLine>();
  const wholes = new Map<string, DirectionWhole>();
  const requests = new Map<string, RequestNote>();
  const actionFeedback = new Map<string, string>();
  const cues: KeyedState<CueKind> = createKeyedState<CueKind>({
    clock,
    ttlMs: CUE_TTL_MS,
    limit: HELD_CUE_LIMIT,
  });
  /* The guard the announcer keeps per standing mark is dropped with the mark, at every site that drops
     one. The keyed lane evicts and lapses on its own, so its keys are mirrored here, in the same order, to
     know which marks went. */
  const marks = new Map<string, CueKind>();
  /* When each standing mark was stamped. The keyed lane stores the kind alone, and the discard's dwell is
     measured from the press that armed it. */
  const stamps = new Map<string, number>();
  /* The focus a press asks for once its panel has drawn: the new empty line, the field Escape came from. */
  let focusName: string | null = null;
  let version = 0;
  const listeners = new Set<() => void>();

  function notify(): void {
    version += 1;
    for (const listener of [...listeners]) listener();
  }

  function dropGuard(key: string): void {
    marks.delete(key);
    stamps.delete(key);
    announcer.forget(key);
  }

  cues.subscribe(() => {
    for (const key of [...marks.keys()]) {
      if (cues.read(key) === undefined) dropGuard(key);
    }
    notify();
  });

  return {
    clock,
    announcer,
    goals,
    lines,
    origins,
    chosen,
    picks,
    prompts,
    directions,
    wholes,
    requests,
    actionFeedback,

    clearActionFeedback(sessionKey: string): void {
      for (const key of actionFeedback.keys()) {
        const scope = key.slice(key.indexOf(':') + 1);
        if (scope === sessionKey || scope.startsWith(`${sessionKey}:`)) {
          actionFeedback.delete(key);
          announcer.forget(`action:${key}`);
        }
      }
      const request = requests.get(sessionKey);
      if (request && !request.pending) request.message = '';
      announcer.forget(`keep:${sessionKey}`);
    },
    cues,

    subscribe(listener: () => void): () => void {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    getVersion: (): number => version,
    notify,

    /** When the standing mark was stamped, or 0 where there is none. */
    stampOf: (key: string): number => (cues.read(key) === undefined ? 0 : (stamps.get(key) ?? 0)),

    /** The stamped kind, or nothing once it has expired. */
    kind(key: string): CueKind {
      return cues.read(key) ?? '';
    },

    /* Stamps a mark. `say` is the caller's: a press whose outcome is said once its refresh has drawn it
       stamps without saying. Marking is not dropping, so the guard stays and a repeat of the same sentence
       is not announced twice. */
    mark(key: string, kind: CueKind): void {
      marks.delete(key);
      marks.set(key, kind);
      stamps.set(key, clock.now());
      cues.remember(key, kind);
      while (marks.size > HELD_CUE_LIMIT) {
        const [oldest] = marks.keys();
        if (oldest === undefined) break;
        dropGuard(oldest);
      }
    },

    /* One drop, all three lanes: the mark, its repeat guard and an armed warning it held. */
    drop(key: string): void {
      cues.forget(key);
      dropGuard(key);
    },

    /* Arms the lane's expiry timer, so a mark that lapses is dropped with its repeat guard and the panel is
       told, instead of waiting for the next render to notice. Idempotent, so StrictMode's second effect is
       harmless; the returned function stops it. */
    activate(): () => void {
      cues.activate();
      return () => cues.deactivate();
    },

    requestFocus(name: string): void {
      focusName = name;
      notify();
    },
    takeFocus(): string | null {
      const name = focusName;
      focusName = null;
      return name;
    },
  };
}

export type Held = ReturnType<typeof createHeld>;

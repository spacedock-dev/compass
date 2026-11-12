import { useSyncExternalStore } from 'react';
import { GUARDRAIL_TEXT_LIMIT } from '../storage';
import { useShell, type Shell } from '../shell/context';

/* What the project's steering controls hold for the reader that a redraw must not lose, kept in memory and
   never written to browser storage: the words typed and not yet sent, the add-a-tripwire box once opened and
   the receipts of this tab's drafts (docs/design-reader-state.md, "A typed and unsent draft" and "The + set a
   tripwire box"). The local tripwires themselves are browser preferences and live in the guardrail store.

   Keyed by the exact project label and nothing else, so one project's words never reach another's box, and
   held outside the rendered tree because a node does not outlive a route change. The editors are
   uncontrolled: a keystroke is recorded here and React is never asked to write the value back, which is what
   keeps the native caret, selection and undo history of a box that is being edited. */

export const STEER_RECORD_LIMIT = 20;

export type DraftKind = 'steer' | 'guardrail';

interface ProjectHeld {
  adding: boolean;
  /** The draft notes recorded in this tab, oldest first. */
  steers: { readonly text: string }[];
  steersDropped: boolean;
  drafts: Record<DraftKind, string>;
}

/* A workflow stage condition's save and the focus it asked for once it settles. The draft choice, the cue
   the last press earned and a request for focus are held by the workflow's id and not by a node, because the
   board redraws while a request is out and the card must come back as the reader left it (docs/design-reader-
   state.md, "A workflow stage-condition choice, save cue and action focus"). */
export interface StageFocus {
  readonly key: string;
  /** The card instance that made the request. A card that has gone took its request with it. */
  readonly owner: symbol;
  /** The interaction count the press saw. A later keystroke or pointer press means the reader moved on. */
  readonly interaction: number;
}

export function createSteeringHeld() {
  const projects = new Map<string, ProjectHeld>();
  const stageDrafts = new Map<string, string>();
  const stageCues = new Map<string, string>();
  let stageInteraction = 0;
  let stageMounts = 0;
  let stageFocus: StageFocus | null = null;
  const stageCards = new Set<symbol>();
  let version = 0;
  const listeners = new Set<() => void>();

  function notify(): void {
    version += 1;
    for (const listener of [...listeners]) listener();
  }

  function stateOf(project: string): ProjectHeld {
    let state = projects.get(project);
    if (!state) {
      state = {
        adding: false,
        steers: [],
        steersDropped: false,
        drafts: { steer: '', guardrail: '' },
      };
      projects.set(project, state);
    }
    return state;
  }

  return {
    subscribe(listener: () => void): () => void {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    getVersion: (): number => version,
    draft: (project: string, kind: DraftKind): string => stateOf(project).drafts[kind],
    setDraft(project: string, kind: DraftKind, text: string): void {
      stateOf(project).drafts[kind] = text;
      // The mounted editor updates its own counter; other panels need no render for a keystroke.
    },
    /* The words are gone from the draft AND, by the caller, from the node: a box that still held them would
       be read back over this write by the next capture, and a second send would record them twice. */
    clearDraft(project: string, kind: DraftKind): void {
      stateOf(project).drafts[kind] = '';
    },
    adding: (project: string): boolean => stateOf(project).adding,
    setAdding(project: string, adding: boolean): void {
      const state = stateOf(project);
      if (state.adding === adding) return;
      state.adding = adding;
      notify();
    },
    steers: (project: string): readonly { readonly text: string }[] => stateOf(project).steers,
    steersDropped: (project: string): boolean => stateOf(project).steersDropped,
    recordSteer(project: string, text: string): void {
      const state = stateOf(project);
      if (state.steers.length >= STEER_RECORD_LIMIT) state.steersDropped = true;
      state.steers = [...state.steers, { text }].slice(-STEER_RECORD_LIMIT);
      notify();
    },
    notify,

    stage: {
      draft: (id: string): string | undefined => stageDrafts.get(id),
      setDraft(id: string, stage: string): void {
        stageDrafts.set(id, stage);
        notify();
      },
      dropDraft(id: string): void {
        stageDrafts.delete(id);
      },
      cue: (id: string): string => stageCues.get(id) ?? '',
      setCue(id: string, cue: string): void {
        stageCues.set(id, cue);
        notify();
      },
      interaction: (): number => stageInteraction,
      /* A keystroke or a pointer press anywhere on the page: the reader is somewhere else now. */
      interacted(): void {
        stageInteraction += 1;
      },
      /* Counted, so StrictMode's mount, cleanup, mount leaves one and a card that is gone leaves none. A
         request for focus is only taken while some card is there to receive it, and dropped with the last,
         so it never outlives the page that asked for it. */
      mounted(): () => void {
        stageMounts += 1;
        return () => {
          stageMounts -= 1;
          if (stageMounts <= 0) {
            stageMounts = 0;
            stageFocus = null;
          }
        };
      },
      /* One per card on the page, by the instance and not the workflow: the Projects page draws a card for
         the same workflow as the Course tab, and a request made on one is not the other's. */
      cardMounted(owner: symbol): () => void {
        stageCards.add(owner);
        return () => {
          stageCards.delete(owner);
          if (stageFocus?.owner === owner) stageFocus = null;
        };
      },
      requestFocus(request: StageFocus): void {
        if (stageMounts <= 0 || !stageCards.has(request.owner)) return;
        stageFocus = request;
        notify();
      },
      takeFocus(): StageFocus | null {
        const request = stageFocus;
        stageFocus = null;
        return request;
      },
    },
  };
}

export type SteeringHeld = ReturnType<typeof createSteeringHeld>;

/* One per shell, made on first use and kept for the document's life, so a view that unmounts and returns
   finds what it left, and a second shell (a test, a hot update) never shares a word with the first. */
const held = new WeakMap<Shell, SteeringHeld>();

export function steeringHeldFor(shell: Shell): SteeringHeld {
  let found = held.get(shell);
  if (!found) {
    found = createSteeringHeld();
    held.set(shell, found);
  }
  return found;
}

export function useSteeringHeld(): SteeringHeld {
  return steeringHeldFor(useShell());
}

/* Re-render when anything held changes. */
export function useHeldVersion(store: SteeringHeld): number {
  return useSyncExternalStore(store.subscribe, store.getVersion);
}

export const TEXT_LIMIT = GUARDRAIL_TEXT_LIMIT;

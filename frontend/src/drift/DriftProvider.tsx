import './drift.css';
import { useEffect, useMemo, useRef, useState, useSyncExternalStore, type ReactNode } from 'react';
import { payloadSessions } from '../api/bootstrap';
import { compatSessKey, contextKey, stableProjectKey } from '../api/identity';
import {
  liveMonitorFor,
  monitorKey,
  useLiveMonitorOn,
  useMonitorEntry,
} from '../intent/liveMonitor';
import { workObject } from './level';
import { monitorLevel, parseLease } from './monitor';
import { useHeldVersion } from '../intent/useIntent';
import type { Row } from '../observed';
import { useDisplayed, useShell } from '../shell/context';
import { DriftContext, type DriftValue, type Jump, type JumpMissing } from './context';
import { buildModel, type DriftModel } from './model';
import { overlaid } from './overlay';
import { readingCopied } from './shape';
import { driftCtxFor, useDriftVersion, type DriftCtx } from './state';
import { clearFlipLines } from './flip';
import { entryWindow } from '../intent/work';
import { citationsHeld, citedIdsOf, citesOf, entriesHeld, heldIds } from './citations';
import { fullActivityKey } from '../sessions/fullActivityKey';
import { trackJobs } from './jobs';
import { syncPaused } from './steerActions';

/* Whether the reader is in this session's correction box (untouched or edited), composing in it, or holding a
   pointer on a control they left it for: then the Drift card keeps showing the board it already drew. The
   legacy page queued the whole page's paint for an edited box. The React page keeps a persistent node, so the
   editor's caret, selection and undo survive an ordinary redraw, but a redraw that moves the box in the tree
   (a stale mark turning the layout into another) would remount it, resetting the caret of a reader who has
   only clicked into it and ending a composition. So a board that arrives while the reader is in the box
   waits, and the newest one shows when they leave
   ([the reader state row](../../../docs/design-reader-state.md)). The reader's own presses never wait. */
function engaged(ctx: DriftCtx, key: string): boolean {
  const { editor, corrections } = ctx.drift;
  if (editor.composition) return true;
  if (editor.pointer && editor.pointer.key === key) return true;
  return Boolean(corrections.get(key) && editor.focused === key);
}

export function DriftProvider({
  session,
  payload,
  project,
  children,
}: {
  readonly session: Row;
  readonly payload: Row;
  readonly project: string;
  readonly children: ReactNode;
}) {
  const shell = useShell();
  const ctx = driftCtxFor(shell);
  useHeldVersion(ctx.intent.held);
  useDriftVersion(ctx.drift);
  const overlay = useSyncExternalStore(ctx.drift.subscribe, ctx.drift.getOverlay);
  const contexts = useDisplayed((snapshot) => snapshot.contexts);
  const records = useDisplayed((snapshot) => snapshot.records);
  const count = useDisplayed((snapshot) => snapshot.acceptedCount);
  const key = compatSessKey(session);
  const live = useMemo(
    () => ({
      session,
      base: payload,
      payload: overlaid(payload, overlay, count),
      contexts,
    }),
    [session, payload, count, contexts, overlay],
  );
  /* The board the card shows. While the reader is mid-edit it stays the last one drawn, and the newest shows
     when they leave: state adjusted during the render that finds the wait over, so no ref is read in one. */
  const [shown, setShown] = useState(live);
  const waiting = engaged(ctx, key);
  if (!waiting && shown !== live) setShown(live);
  const view = waiting ? shown : live;
  const projectKey = useMemo(
    () =>
      stableProjectKey({
        label: project,
        sessions: payloadSessions(view.payload as never).rows.filter(
          (row) => String(row.project ?? '') === project,
        ),
      }),
    [view.payload, project],
  );
  const liveOn = useLiveMonitorOn(session);
  /* The lease the server publishes on the focused context is fed to the one place the page keeps it, so the
     switch, the card and the question read one state; an older state never replaces a newer one. */
  const monitors = liveMonitorFor(shell);
  const leaseRow = workObject(view.contexts, projectKey, session, 'live_monitor');
  useEffect(() => {
    const lease = parseLease(leaseRow);
    if (lease) monitors.observe(monitorKey(session), lease);
  }, [monitors, leaseRow, session]);
  const held = useMonitorEntry(session);
  const monitor = liveOn && held.lease ? monitorLevel(held.lease) : null;
  const record = records.get(contextKey(projectKey, session as never));
  const model: DriftModel = buildModel({
    liveOn,
    monitor,
    session: view.session,
    payload: view.payload,
    base: view.base,
    project,
    projectKey,
    contexts: view.contexts,
    held: ctx.intent.held,
    ...(record ? { record } : {}),
  });
  const [chosen, setChosen] = useState<Jump | null>(null);
  const [settled, setSettled] = useState<Jump | null>(null);
  const [missing, setMissing] = useState<JumpMissing | null>(null);
  // The latest press: a read that ends after another press began says nothing about the one now standing.
  const latestPress = useRef<Jump | null>(null);
  const readAt = model.raw?.['read_at'];
  const pressed =
    chosen?.session === key && chosen.readAt === readAt
      ? (model.shape?.criteria.find((row) => row.key === chosen.key) ?? null)
      : null;
  /* A selection stands while its cited rows are held, and while the pages its press asked for are still being
     read, when none may be held yet. */
  const finding = pressed && (pressed.citedIds.length || settled !== chosen) ? pressed : null;
  /* Every cited entry held and none drawn as the finding's: the reading's own rules (its window, its request,
     its limit) set them aside. Said where the press would have landed, so focus has somewhere to go. */
  if (chosen && settled === chosen && pressed && !pressed.citedIds.length && !missing)
    setMissing({ press: chosen, count: 0, reason: 'unshown' });
  // Invalidation ends the press, so returning to its session or citations cannot restore its marks.
  if (chosen && !finding) setChosen(null);
  // The note answers one press on one reading; a new reading or another session takes it down, as it does `chosen`.
  if (missing && (missing.press.session !== key || missing.press.readAt !== readAt))
    setMissing(null);
  /* A press of a cited entry opens Full activity and, where an entry it cites is not one the page holds,
     reads older record pages until it is, the record's start, or the page cap. The reader asked for these
     entries, so this is their read, as Show more is; docs/design-reader-state.md#the-inventory owns it.
     Whatever is still not held when the read ends is counted, and the list says so. */
  const chooseFinding = (
    findingKey: string,
    origin: HTMLElement | null = null,
    entry: string | null = null,
  ) => {
    const next: Jump = { session: key, readAt, key: findingKey, origin, entry };
    latestPress.current = next;
    setChosen(next);
    setSettled(null);
    setMissing(null);
    ctx.shell.controls.disclosures.set(fullActivityKey(project, session), true);
    const cited = citesOf(model.raw, findingKey);
    const identity = model.identity;
    const scope = { projectKey: model.projectKey, session: model.session, cited };
    const settle = () => {
      if (latestPress.current !== next) return;
      const snapshot = ctx.shell.runtime.store.getSnapshot();
      const held = heldIds(snapshot, scope);
      const count = cited.filter((id) => !held.has(id)).length;
      /* "Does not list it" only once the record's start was read: the page cap or a failed page also end the
         read, and older pages may still hold the entry then. */
      const reached =
        snapshot.records.get(contextKey(model.projectKey, model.session as never))?.reachedStart ===
        true;
      setSettled(next);
      setMissing(count ? { press: next, count, reason: reached ? 'start' : 'stopped' } : null);
    };
    if (!identity || !cited.length) {
      settle();
      return;
    }
    void ctx.shell.runtime
      .resolveRecord({ projectKey: model.projectKey, focus: identity }, (snapshot) =>
        entriesHeld(snapshot, scope),
      )
      .finally(settle);
  };
  /* The reading drawn now, noted in this tab's memory of what each reading carried. A reading the shape
     refuses or the reader marked inaccurate is no reading to compare. */
  const standing = readAt;
  const cleared =
    typeof standing === 'number' &&
    model.shape &&
    !model.shape.malformed &&
    model.annotation?.['not_accurate'] !== true
      ? ctx.drift.noteReading(
          key,
          standing,
          model.shape.departures.map((row) => ({
            key: row.key,
            detail: row.detail,
            cites: row.citedIds,
          })),
          model.entries.filter(readingCopied).map((entry) => Number(entry.at) || 0),
        )
      : null;
  const value: DriftValue = {
    ctx,
    model,
    finding,
    cleared,
    jump: finding ? chosen : null,
    jumpMissing: missing,
    chooseFinding,
  };

  /* After the commit, never from the render: the timers the card asked for, the announcements of a running
     analysis, and the one release of a paint the reader's editing queued. */
  useEffect(() => {
    ctx.drift.applyTimers();
  });
  const {
    payload: board,
    job,
    key: sessionKey,
    projectKey: boardProject,
    raw,
    session: row,
  } = model;
  const harness = model.identity?.harness;
  const sid = model.identity?.sid;
  useEffect(() => {
    const drawn = new Set<string>();
    const id = job?.['id'];
    if (typeof id === 'string') drawn.add(id);
    const finished = trackJobs(ctx, board, drawn);
    /* The one read the page makes for the reader: this press stored a reading, and it may cite entries
         past the ones the board holds, so older record pages are read until they resolve. Nothing else
         loads a page. docs/design-reader-state.md#the-inventory owns the exception. A press ends once, so
         the effect running again for another dependency asks for nothing. */
    const cited = citedIdsOf(raw);
    if (!finished.includes(sessionKey) || !harness || !sid || !cited.length) return;
    const scope = {
      projectKey: boardProject,
      session: row,
      cited,
      opened: entryWindow(row, board),
    };
    void ctx.shell.runtime.resolveRecord(
      { projectKey: boardProject, focus: { harness, sid } },
      (snapshot) => citationsHeld(snapshot, scope),
    );
  }, [ctx, board, job, sessionKey, boardProject, raw, row, harness, sid]);
  const editing =
    waiting && shown !== live && !ctx.drift.editor.composition && !ctx.drift.editor.pointer;
  useEffect(() => syncPaused(ctx, key, editing), [ctx, key, editing]);
  useEffect(() => ctx.drift.mount(), [ctx]);
  /* The next click inside the card takes the change line down. */
  useEffect(() => {
    const onClick = (event: Event) => {
      const target = event.target;
      if (!(target instanceof Element) || !target.closest('#next-session-drift')) return;
      clearFlipLines(ctx);
    };
    document.addEventListener('click', onClick, true);
    return () => document.removeEventListener('click', onClick, true);
  }, [ctx]);
  /* Leaving the page leaves no box drawn, so a job that ends while the reader is elsewhere is not announced
     as one they watched. */
  useEffect(
    () => () => {
      for (const seen of ctx.drift.jobsSeen.values()) seen.drawn = false;
      // A press's ask for focus belongs to the page it was made on, so one still waiting goes with the card.
      ctx.intent.held.takeFocus();
    },
    [ctx],
  );
  return <DriftContext value={value}>{children}</DriftContext>;
}

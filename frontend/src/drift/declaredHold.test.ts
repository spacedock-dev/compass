// @vitest-environment node
import { expect, it } from 'vitest';
import {
  heldContext,
  heldData,
  heldParent,
  nativeContext,
  nativeData,
  nativeParent,
} from '../../test/declaredHold';
import { boardProgressFromRecordedView, pageView } from './terminalParity.view.test.helper';
import { buildRegistry, readSemantic } from '../timeline/semantic';
import { readHint, observe, observeSession, nativeSession, type Row } from '../observed';
import { sessionFooter, turnEndedSentence } from '../sessions/detail';
import { notifyEdge } from '../notify/edges';
import { createNotifyOwner } from '../notify/owner';
import { workEntries } from '../intent/work';
import { lastTurn } from './workList';
import { attentionModel } from '../attention/model';
import { locationWarnings } from '../observed/location';
import { createWorkstream } from '../workstream/model';
import { createBoardStore } from '../store/board';
import { buildProjectModel } from '../project/model';
import { slotContext } from '../project/slots';
import type { PayloadData } from '../api/types';

it('a serialized display hold preserves the terminal reading with the board’s current-level eligibility', () => {
  const view = (session: Record<string, unknown>) =>
    pageView({
      name: 'declared-hold',
      rules: [],
      session,
      payload: heldData,
      context: heldContext,
    });
  expect(view(nativeParent)).toMatchObject({ reading: true, stale: { kind: 'work' }, pill: null });
  expect(view(heldParent)).toEqual(view(nativeParent));
  expect(
    pageView({
      name: 'native',
      rules: [],
      session: nativeParent,
      payload: nativeData,
      context: nativeContext,
    }),
  ).toEqual(view(heldParent));
  const work = (heldContext['sources'] as Record<string, unknown>)['work'] as Record<
    string,
    unknown
  >;
  const [recorded] = work['drift_views'] as unknown[];
  expect(recorded).toMatchObject({ pill: { so_far: false } });
  expect(boardProgressFromRecordedView(recorded)).toEqual(view(heldParent));
});

it('a serialized display hold retains the server context final result', () => {
  const model = readSemantic(heldContext['semantic']);
  const results = (focus: Record<string, unknown> & { harness: string; sid: string }) =>
    buildRegistry({ model, focus })
      .lanes.filter((lane) => lane.kind === 'fo')
      .flatMap((lane) => lane.events)
      .filter((event) => ['result', 'final_output'].includes(event.type))
      .map((event) => event.id);
  expect(results(nativeParent)).not.toHaveLength(0);
  expect(results(heldParent)).toEqual(results(nativeParent));
});

it('a display hold preserves Analyze scope, completion, footer and last-turn bounds', () => {
  const native = {
    ...nativeParent,
    finished_at: 100,
    annotation_window_start: 10,
    turn_output_tokens: 5,
    session_output_tokens: 100,
  };
  const held = {
    ...native,
    ...heldParent,
    finished_at: 100,
    annotation_window_start: 10,
    turn_output_tokens: 5,
    session_output_tokens: 100,
  };
  expect(readHint(held)).toEqual(readHint(native));
  expect(turnEndedSentence(held)).toEqual(turnEndedSentence(native));
  expect(sessionFooter(held)).toEqual({
    source: 'session',
    text: '100 output tokens this session',
  });
  const entries = workEntries(native, {
    facts: [
      {
        fact_id: 'u1',
        type: 'user_message',
        at: 20,
        by: 'person:me',
        source_session: { harness: native.harness, sid: native.sid },
      },
    ],
  });
  expect(lastTurn(native, entries)).toEqual({ from: 20, to: 100 });
  expect(lastTurn(held, entries)).toEqual(lastTurn(native, entries));
});

it('a held idle parent still reports its native quiet notification edge', () => {
  expect(notifyEdge(heldParent, 'working')).toEqual(notifyEdge(nativeParent, 'working'));
  expect(notifyEdge(heldParent, 'working')).toMatchObject({ title: 'has gone quiet' });
});

it('removing a display hold cannot raise a quiet notification, while a native stop can', () => {
  const banners: string[] = [];
  const owner = createNotifyOwner({
    host: {
      supported: () => true,
      permission: () => 'granted',
      request: () => undefined,
      create: (_title, options) => {
        banners.push(options.body);
      },
    },
    now: () => 0,
    postLane: () => Promise.resolve(true),
    isLeader: () => true,
  });
  const publish = (row: Row) => owner.sync({ ...heldData, native_notify: '', sessions: [row] });
  publish(heldParent);
  publish(nativeParent);
  expect(banners).toEqual([]);
  publish({ ...nativeParent, state: 'working', active: true });
  publish(heldParent);
  expect(banners).toEqual([`[alpha-app] ${nativeParent.state_detail}`]);
});

it('native projection preserves activity and detail without changing the held row', () => {
  expect(nativeSession(heldParent)).toMatchObject({
    state: nativeParent.state,
    active: nativeParent.active,
    state_detail: nativeParent.state_detail,
  });
  expect(heldParent.state).toBe('working');
  expect(heldParent.waiting_on_child).not.toBeNull();
  expect(nativeSession(nativeParent)).toBe(nativeParent);
});

it('the project slot projects native state before dropping the snapshot', () => {
  const store = createBoardStore({ now: () => 0 });
  store.acceptData(heldData as unknown as PayloadData, '1');
  const model = buildProjectModel(store.getSnapshot(), {
    view: 'project',
    project: heldParent.project,
    session: null,
    focus: `claude:${heldParent.sid}`,
    tab: 'decisions',
  });
  expect(model).not.toBeNull();
  if (!model) throw new Error('missing recorded project');
  const focus = slotContext(model).focus;
  expect(focus?.state).toBe('idle');
  const registry = buildRegistry({ model: readSemantic(heldContext['semantic']), focus });
  expect(
    registry.lanes.flatMap((lane) => lane.events).some((event) => event.type === 'result'),
  ).toBe(true);
});

it('observed completion facts survive while the row still displays Working', () => {
  const observeOne = (row: Row) =>
    observeSession(row, [], { key: 'claude', reports_turn_bounds: true }, heldData.generated, '');
  const native = observeOne(nativeParent);
  const held = observeOne(heldParent);
  expect(held.isWorking).toBe(true);
  expect(held.outcomeText).toEqual(native.outcomeText);
  expect(held.outcomeKnown).toBe(true);
  expect(held.landing).toEqual(native.landing);
  expect(held.turnText).toEqual(native.turnText);
  const closing = (row: Row) => observe({ ...heldData, sessions: [row] }).coverage.observed;
  const idle = { ...nativeParent, active: false };
  const waiting = {
    ...heldParent,
    declared_native_state: {
      state: idle.state,
      active: idle.active,
      state_detail: idle.state_detail,
    },
  };
  expect(closing(idle)).toContain('1 to close the loop');
  expect(closing(waiting)).toEqual(closing(idle));
});

it('a display hold cannot invent a long turn or resumed-work risk and keeps the stop', () => {
  const signalKinds = (row: Row) => {
    const model = attentionModel({ ...heldData, sessions: [row] });
    return [...model.risk, ...model.close].flatMap((subject) =>
      subject.signals.map((signal) => signal.kind),
    );
  };
  const native = { ...nativeParent, active: false, turn: { long: true } };
  const held = {
    ...heldParent,
    turn: { long: true },
    declared_native_state: {
      state: native.state,
      active: native.active,
      state_detail: native.state_detail,
    },
  };
  expect(signalKinds(native)).toContain('stop-unknown');
  expect(signalKinds(held)).toEqual(signalKinds(native));
});

it('a child display hold cannot author a resumed-work event in the workstream', () => {
  const stream = createWorkstream();
  stream.observe({ ...nativeData, sessions: [nativeParent] });
  stream.observe({ ...heldData, generated: heldData.generated + 1, sessions: [heldParent] });
  expect(
    stream
      .snapshot()
      .groups.flatMap((group) => group.events)
      .filter((event) => event.kind === 'state'),
  ).toEqual([]);
});

it('a child display hold cannot count its idle parent as working in the same checkout', () => {
  const location = {
    project_identity_source: 'git common directory',
    project_key: 'repo',
    checkout_key: 'checkout',
  };
  const child = { ...location, harness: 'codex', sid: 'child', state: 'working' };
  const warnings = (row: Row) => locationWarnings([{ ...row, ...location }, child]);
  expect(warnings(nativeParent)).toEqual([]);
  expect(warnings(heldParent)).toEqual([]);
});

it('a held headless parent keeps the finished-run reading hint', () => {
  const native = { ...nativeParent, harness: 'codex', headless: true, turn_end_at: 100 };
  const held = { ...heldParent, harness: 'codex', headless: true, turn_end_at: 100 };
  expect(readHint(held)).toEqual(readHint(native));
  expect(turnEndedSentence(held, 110)).toBe('Run finished 10s ago');
});

it('a display hold preserves the recommendation to inspect this idle owner', () => {
  const recommendations = (row: Row) => {
    const store = createBoardStore({ now: () => 0 });
    store.acceptData({ ...heldData, sessions: [row] } as unknown as PayloadData, '1');
    return buildProjectModel(store.getSnapshot(), {
      view: 'project',
      project: heldParent.project,
      session: null,
    })?.attention.map((item) => item.label);
  };
  expect(recommendations(nativeParent)).toContain('inspect idle owner · 1');
  expect(recommendations(heldParent)).toEqual(recommendations(nativeParent));
});

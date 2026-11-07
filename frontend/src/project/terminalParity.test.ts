// @vitest-environment node
import { readFileSync } from 'node:fs';
import { expect, it } from 'vitest';
import { observe, type Row } from '../observed';
import { groupFor, stableKey, workingSessions, sessKey } from './group';
import { scopeLinks } from './scope';
import {
  commandAttention,
  attentionCoverage,
  recoveryAssignment,
  recoveryChildren,
  semanticOf,
} from './recovery';
import { goalScope, instructionHeading } from './goal';

const read = (name: string) =>
  JSON.parse(readFileSync(new URL(`../../test/fixtures/${name}.json`, import.meta.url), 'utf8'));
it('a person reads the same recorded project brief in the terminal and on the board', () => {
  const payload = read('client-contract/data-terminal-project').response.body as Row;
  const context = read('client-contract/context-terminal-project').response.body as Row;
  const group = groupFor(payload, observe(payload), 'terminal-project');
  if (!group) throw new Error('recorded project absent');
  const harnesses = new Map(
    (payload['harnesses'] as Row[]).map((row) => [String(row['key']), String(row['label'])]),
  );
  const generated = payload['generated'] as number;
  const env = { group, harnesses, generated, entry: { data: context }, workflow: false };
  const attention = commandAttention(env);
  const assignment = recoveryAssignment(env, semanticOf(context), context, attention);
  const children = recoveryChildren(env);
  const allChildren = [
    ...children.active,
    ...(children.latestReturn ? [children.latestReturn] : []),
  ];
  const working = new Set(workingSessions(group).map(sessKey));
  const goal = goalScope(group.observed, null);
  const board = {
    label: group.label,
    key: stableKey(group),
    counts: group.observed.countLine,
    warning: group.observed.sharedLabelText,
    members: scopeLinks(group, harnesses, generated)
      .slice(1)
      .map((link) => ({
        key: link.key,
        title: link.title,
        state: link.meta?.state,
        age: link.meta?.age,
        harness: link.scope.detail,
      })),
    task: assignment.label,
    task_stage: assignment.stage,
    task_source: assignment.provenance,
    instruction: goal.text,
    instruction_heading: instructionHeading(group.observed, null),
    instruction_source: goal.src,
    running: group.sessions
      .filter(
        (row) =>
          working.has(sessKey(row)) ||
          allChildren.some((child) => child.sourceSession === sessKey(row)),
      )
      .map(sessKey),
    children: allChildren.map((child) => ({
      worker: child.worker,
      lifecycle: child.lifecycle,
      assignment: child.assignment,
      source: child.assignmentSource,
      parent: child.sourceSession,
      result: child.result || '',
      stale: child.lifecycle === 'returned' && (child.ageSec ?? 0) >= 600,
    })),
    attention: attention.map((item) => ({
      owner: item.owner,
      label: item.label,
      kind: item.kind,
      source: String((item.evidence as Row)['source'] || ''),
    })),
    coverage: attentionCoverage(env.entry, false).label,
  };
  expect(board).toEqual(read('terminal-project'));
});

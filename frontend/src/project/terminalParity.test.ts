// @vitest-environment jsdom
import { readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
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
import { mountProject } from './testing';

const read = (name: string) =>
  JSON.parse(readFileSync(resolve('frontend/test/fixtures', `${name}.json`), 'utf8'));
for (const name of ['terminal-project', 'terminal-project-fo']) {
  it(`a person reads the same recorded ${name} brief in the terminal and on the board`, async () => {
    const payload = read(`client-contract/data-${name}`).response.body as Row;
    const context = read(`client-contract/context-${name}`).response.body as Row;
    const group = groupFor(payload, observe(payload), 'terminal-project');
    if (!group) throw new Error('recorded project absent');
    const harnesses = new Map(
      (payload['harnesses'] as Row[]).map((row) => [String(row['key']), String(row['label'])]),
    );
    const generated = payload['generated'] as number;
    const workflow = group.sessions.some(
      (row) => (row['spacedock'] as Row | undefined)?.['role'] === 'first-officer',
    );
    const env = { group, harnesses, generated, entry: { data: context }, workflow };
    const page = mountProject({
      hash: '#n=project:terminal-project',
      data: payload,
      contexts: { [`${stableKey(group)}\n`]: context },
    });
    await page.settle();
    const strip = page.getByLabelText('Recovery summary');
    const authority = strip.querySelector('.next-cockpit-authority');
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
      coverage: attentionCoverage(env.entry, workflow).label,
      attention_heading: authority?.querySelector(':scope > span')?.textContent ?? '',
      attention_truth: authority?.querySelector(':scope > small')?.textContent ?? '',
      authority_gloss: strip.querySelector('.next-cockpit-recovery-gloss')?.textContent ?? '',
    };
    if (name === 'terminal-project-fo') {
      expect(board.attention_heading).toBe('FO INSPECTING');
      expect(board.attention_truth).toBe('Captain not needed');
      expect(board.children.at(-1)?.worker).toBe('First');
      expect(board.attention.some((item) => item.label === 'recover First handoff')).toBe(true);
      expect(board.attention.some((item) => item.label === 'recover Second handoff')).toBe(false);
    }
    // Expected briefs come from the rendered React page, never from the Python port.
    if (process.env['COMPASS_WRITE_PROJECT_PARITY'] === '1') {
      writeFileSync(
        resolve('frontend/test/fixtures', `${name}.json`),
        `${JSON.stringify(board, null, 2)}\n`,
      );
    }
    expect(board).toEqual(read(name));
  });
}

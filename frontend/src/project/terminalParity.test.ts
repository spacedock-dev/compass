// @vitest-environment jsdom
import { mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
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
import { locationBoard, locationRow } from '../../test/location_boards';

const read = (name: string) =>
  JSON.parse(readFileSync(resolve('frontend/test/fixtures', `${name}.json`), 'utf8'));
for (const name of ['terminal-project', 'terminal-project-fo']) {
  it(`the board preserves the recorded ${name} brief with evidence-based Quiet counts`, async () => {
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
          state: link.meta?.label || link.limit,
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
    // Workflow authority wording below the terminal's Needs you line is specific to the CLI.
    const { terminal_attention: terminalAttention, ...recorded } = read(name);
    // Emit candidates from the rendered board for review, leaving the fixture untouched.
    if (process.env['COMPASS_WRITE_PROJECT_PARITY'] === '1') {
      const candidate = join(
        mkdtempSync(join(tmpdir(), 'compass-terminal-project-')),
        `${name}.json`,
      );
      writeFileSync(
        candidate,
        `${JSON.stringify({ ...board, terminal_attention: terminalAttention }, null, 2)}\n`,
      );
      console.info(`Project candidate: ${candidate}`);
      return;
    }
    expect(board).toEqual(recorded);
  });
}

it('a mixed project counts two measured sessions and discloses its one unknown', async () => {
  const payload = locationBoard(3);
  locationRow(payload, 1)['project_key'] = 'path:other';
  locationRow(payload, 2)['project_identity_source'] = 'inferred Claude worktree layout';
  const group = groupFor(payload, observe(payload), 'audits');
  expect(group?.observed.sharedLabelText).toBe(
    '2 sessions share this display label across 2 measured locations. Location not measured for 1 session with this display label',
  );
});

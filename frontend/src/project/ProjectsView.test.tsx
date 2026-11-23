import { fireEvent, screen, within } from '@testing-library/react';
import { expect, it } from 'vitest';
import { projectRequestBoard, projectStatusBoard } from '../../test/project_boards';
import { mountProject } from './testing';

const projects = () =>
  screen.getByRole('heading', { name: 'Projects' }).closest('section') as HTMLElement;

it('counts measured quiet rows and excludes scan-only absences from the chip', async () => {
  const page = mountProject({ hash: '#n=projects', data: projectStatusBoard });
  await page.settle();
  const view = within(projects());
  expect(view.getByRole('img', { name: '1 quiet' })).toBeVisible();
  expect(view.queryByRole('img', { name: '2 quiet' })).toBeNull();
  expect(view.getByText('3 sessions')).toBeVisible();
});

it('keeps the project link and focus when a session joins above the earlier rows', async () => {
  const page = mountProject({ hash: '#n=projects', data: projectRequestBoard });
  await page.settle();
  const link = within(projects()).getByRole('link', { name: /rollup/ });
  link.focus();
  await page.poll({ ...projectRequestBoard, generated: Number(projectRequestBoard.generated) + 1 });
  expect(within(projects()).getByRole('link', { name: /rollup/ })).toBe(link);
  expect(document.activeElement).toBe(link);
  fireEvent.click(link);
  expect(page.router.getRoute()).toMatchObject({ view: 'project', project: 'rollup' });
});

import assert from 'node:assert/strict';
import { test } from 'node:test';
import config from '../../vitest.config.mts';

test('a contributor can run the DOM suite without retaining a worker up to its heap ceiling', () => {
  const dom = config.test.projects.find((project) => project.test.name === 'dom').test;
  assert.equal(dom.pool, 'vmForks');
  // Vitest 4.1 reads the VM-only limit from the root when scheduling project files.
  assert.equal(
    config.test.vmMemoryLimit,
    '1GiB',
    'recycle DOM workers before the hosted 2 GiB old-space ceiling',
  );
  const logic = config.test.projects.find((project) => project.test.name === 'logic').test;
  assert.equal(
    logic.pool ?? config.test.pool ?? 'forks',
    'forks',
    'logic workers are outside the VM recycling policy',
  );
});

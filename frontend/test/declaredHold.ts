import native from './fixtures/client-contract/data-focused-drift-completed.json';
import held from './fixtures/client-contract/data-focused-drift-held.json';
import nativeRead from './fixtures/client-contract/context-focused-drift-completed.json';
import heldRead from './fixtures/client-contract/context-focused-drift-held.json';
import type { Row } from '../src/observed';

export const nativeData = native.response.body;
export const heldData = held.response.body;
export const nativeContext: Row = nativeRead.response.body;
export const heldContext: Row = heldRead.response.body;
function present<T>(row: T | undefined): T {
  if (row === undefined) throw new Error('missing recorded parent');
  return row;
}

export const nativeParent = present(nativeData.sessions.find((row) => row.harness === 'claude'));

export const heldParent = present(heldData.sessions.find((row) => row.harness === 'claude'));

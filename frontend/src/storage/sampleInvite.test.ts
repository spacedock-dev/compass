import { expect, it } from 'vitest';
import { fakeBackend } from '../../test/storage_backends';
import { createLegacyStorage } from '.';

it('remembers the dismissal on a fresh page', () => {
  const backend = fakeBackend();
  const load = () => createLegacyStorage(() => backend).sampleInvite;
  expect(load().dismissed()).toBe(false);
  load().dismiss();
  expect(load().dismissed()).toBe(true);
});

it('keeps the dismissal in this tab even when browser storage throws', () => {
  const blocked = () => {
    throw new Error('storage blocked');
  };
  const store = createLegacyStorage(blocked).sampleInvite;
  expect(store.dismissed()).toBe(false);
  store.dismiss();
  expect(store.dismissed()).toBe(true);
  expect(createLegacyStorage(blocked).sampleInvite.dismissed()).toBe(false);
});

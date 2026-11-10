import { describe, expect, it } from 'vitest';
import { readOnlyBackend, fakeBackend } from '../../test/storage_backends';
import { storageAccess } from './backend';
import { STORAGE_KEYS } from './keys';
import { createUpdateDismissals } from './update';

describe('release notice dismissals', () => {
  it('keeps an in-tab dismissal through repeated reads when persistence fails', () => {
    const versions = Array.from({ length: 32 }, (_, index) => `1.0.${index}`);
    const backend = readOnlyBackend({ [STORAGE_KEYS.updateDismissed]: JSON.stringify(versions) });
    const dismissals = createUpdateDismissals(storageAccess(() => backend));
    dismissals.dismiss('2.0.0');
    for (let index = 0; index < 100; index++) expect(dismissals.dismissed('2.0.0')).toBe(true);
    expect(dismissals.dismissed('3.0.0')).toBe(false);
  });

  it('persists the newest 32 versions with local dismissals taking precedence', () => {
    const versions = Array.from({ length: 32 }, (_, index) => `1.0.${index}`);
    const backend = fakeBackend({ [STORAGE_KEYS.updateDismissed]: JSON.stringify(versions) });
    const dismissals = createUpdateDismissals(storageAccess(() => backend));
    dismissals.dismiss('2.0.0');
    expect(JSON.parse(backend.data.get(STORAGE_KEYS.updateDismissed) ?? '[]')).toEqual([
      ...versions.slice(1),
      '2.0.0',
    ]);
    expect(createUpdateDismissals(storageAccess(() => backend)).dismissed('2.0.0')).toBe(true);
  });
});

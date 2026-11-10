// @vitest-environment jsdom
import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { UpdateNotice } from './UpdateNotice';
import { createLegacyStorage } from '../storage';
import { fakeBackend, blockedBackend } from '../../test/storage_backends';

describe('a reader handles a newer Compass release', () => {
  it('remembers dismissal for that version across remounts and shows a later one', () => {
    const backend = fakeBackend();
    const storage = createLegacyStorage(() => backend);
    const notice = render(
      <UpdateNotice update={{ version: '2.9.0', checked_at: 1 }} storage={storage} />,
    );
    expect(screen.getByText('Compass 2.9.0 is available')).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: 'Dismiss update notice' }));
    expect(screen.queryByText('Compass 2.9.0 is available')).toBeNull();
    notice.unmount();
    const reload = render(
      <UpdateNotice
        update={{ version: '2.9.0', checked_at: 2 }}
        storage={createLegacyStorage(() => backend)}
      />,
    );
    expect(screen.queryByText('Compass 2.9.0 is available')).toBeNull();
    reload.rerender(
      <UpdateNotice update={{ version: '2.10.0', checked_at: 3 }} storage={storage} />,
    );
    expect(screen.getByText('Compass 2.10.0 is available')).toBeVisible();
  });

  it('holds dismissal in the tab when storage is blocked and draws nothing without an answer', () => {
    const storage = createLegacyStorage(blockedBackend);
    const notice = render(<UpdateNotice update={null} storage={storage} />);
    expect(screen.queryByRole('button', { name: 'Dismiss update notice' })).toBeNull();
    notice.rerender(
      <UpdateNotice update={{ version: '2.9.0', checked_at: 1 }} storage={storage} />,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Dismiss update notice' }));
    notice.rerender(
      <UpdateNotice update={{ version: '2.9.0', checked_at: 2 }} storage={storage} />,
    );
    expect(screen.queryByText('Compass 2.9.0 is available')).toBeNull();
  });
});

import { SESSION_ROW_WORDS } from '../language/glossary';
import { Icon } from '../ui/icons';

export function WorthALookFlag({ reason }: { readonly reason: string }) {
  return (
    <span
      className="mt-1 flex items-baseline gap-1.5 text-label font-semibold text-[var(--progress-off-course)]"
      data-next-row-worth-a-look
    >
      <Icon name="worth-a-look" className="relative top-[.15em]" />
      <span>{`${SESSION_ROW_WORDS.worthALook}: ${reason}`}</span>
    </span>
  );
}

import type { ReactNode } from 'react';
import { Card } from '../ui/card';

export const WHAT_IT_DID_PLACEHOLDER =
  'An outline of what this session did is not drawn here yet. Every entry it recorded is under Full activity below.';

/* The What the session has done card: a stable region between the Intent card and the Drift card that the
   outline and the summary fill. Until they do it says so, so the page never reads as if the session did
   nothing. `children` is the slot; `data-next-session-summary-slot` is the hook a later part and its tests
   find it by. */
export function WhatItDid({ children }: { readonly children?: ReactNode }) {
  return (
    <Card
      variant="drift-panel"
      as="section"
      className="flex flex-col gap-2 px-4 pt-4 pb-4"
      aria-labelledby="next-session-summary-heading"
      data-next-session-summary
    >
      <h2 id="next-session-summary-heading" className="next-session-drift-heading">
        What the session has done
      </h2>
      <div className="flex flex-col gap-2" data-next-session-summary-slot>
        {children ?? (
          <p className="next-cockpit-define" data-next-session-summary-empty>
            {WHAT_IT_DID_PLACEHOLDER}
          </p>
        )}
      </div>
    </Card>
  );
}

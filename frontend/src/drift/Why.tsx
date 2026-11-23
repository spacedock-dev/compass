import type { ReactNode } from 'react';
import { Disclosure, disclosureKey } from '../controls';
import { useDrift } from './context';

/* Tier 2 of the caveat rule
   ([NUI-19](../../../docs/design-next-ui.md#nui-19-a-caveat-has-three-tiers)): the claim stays inline where the
   reader meets it and the rest goes behind a summary naming what is inside. Open state is the reader's own,
   kept by the disclosure lane under a key made of the project, this session and the control's name, so it
   survives every redraw and opening a caveat on one session never opens it on the next.

   Two fallbacks, because both silently delete a caveat rather than tiering it: an empty body renders nothing
   at all instead of a summary promising text that is not there, and a missing summary renders the body
   inline instead of hiding it behind a control with no label. */
export function Why({
  name,
  summary,
  body,
  searchable,
  children,
}: {
  readonly name: string;
  readonly summary?: string;
  readonly body?: string;
  readonly searchable?: boolean;
  readonly children?: ReactNode;
}) {
  const { model } = useDrift();
  const text = String(body == null ? '' : body).trim();
  if (!text && !children) return null;
  const content = (
    <>
      {text ? <p className="next-cockpit-reading-why">{text}</p> : null}
      {children}
    </>
  );
  if (!summary) return content;
  return (
    <Disclosure
      disclosureKey={disclosureKey({ project: model.project, scope: model.key, name })}
      summary={summary}
      {...(searchable === undefined ? {} : { searchable })}
      className="next-cockpit-why"
    >
      {content}
    </Disclosure>
  );
}

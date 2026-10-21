import type { ReactNode } from 'react';
import type { Row } from '../observed';
import { Card } from '../ui/card';
import { NOTICE_SENT, noticeProvider, noticeDestination, noticeToolOutput } from './sentences';

/* The server owns these words; splitting a label changes presentation only. */
const PART_LABEL = /^([A-Z][A-Za-z' ,]{1,40}?):\s+(\S[\s\S]*)$/;

export function DisclosureParts({
  parts,
  id,
}: {
  readonly parts: readonly string[];
  readonly id?: string;
}) {
  return (
    <ul className="next-cockpit-reading-parts" id={id}>
      {parts.map((part, index) => {
        const labelled = parts.length > 1 ? PART_LABEL.exec(part) : null;
        return (
          <li key={index}>
            {labelled ? (
              <>
                <strong className="font-semibold text-foreground">{`${labelled[1] ?? ''}:`}</strong>
                {` ${labelled[2] ?? ''}`}
              </>
            ) : (
              part
            )}
          </li>
        );
      })}
    </ul>
  );
}

/* What a notice says, with no frame: open as the card while the request it came with runs, and inside the one
   "What is sent" disclosure once the result it came with is in. */
export function NoticeBody({
  notice,
  provider,
  parts,
}: {
  readonly notice: Row;
  readonly provider: string;
  readonly parts: readonly string[];
}) {
  const output = String(notice['tool_output'] || '');
  return (
    <>
      <p className="next-cockpit-reading-why">{NOTICE_SENT}</p>
      <DisclosureParts parts={parts} />
      <div>
        <p className="next-cockpit-reading-why">{noticeProvider(provider)}</p>
        <p className="next-cockpit-reading-why">
          {noticeDestination(String(notice['destination'] || ''))}
        </p>
        {output ? <p className="next-cockpit-reading-why">{noticeToolOutput(output)}</p> : null}
      </div>
    </>
  );
}

export function ModelNotice({
  notice,
  provider,
  parts,
  children,
  name = 'Model request notice',
}: {
  readonly notice: Row;
  readonly provider: string;
  readonly parts: readonly string[];
  readonly children: ReactNode;
  /** The region's name; two notices on one page must not share one. */
  readonly name?: string;
}) {
  return (
    <Card as="section" variant="reading-notice" data-next-reading-notice="" aria-label={name}>
      <NoticeBody notice={notice} provider={provider} parts={parts} />
      <div className="next-cockpit-reading-ask">{children}</div>
    </Card>
  );
}

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

export function ModelNotice({
  notice,
  provider,
  parts,
  children,
}: {
  readonly notice: Row;
  readonly provider: string;
  readonly parts: readonly string[];
  readonly children: ReactNode;
}) {
  const output = String(notice['tool_output'] || '');
  return (
    <Card variant="reading-notice" data-next-reading-notice="">
      <p className="next-cockpit-reading-why">{NOTICE_SENT}</p>
      <DisclosureParts parts={parts} />
      <div>
        <p className="next-cockpit-reading-why">{noticeProvider(provider)}</p>
        <p className="next-cockpit-reading-why">
          {noticeDestination(String(notice['destination'] || ''))}
        </p>
        {output ? <p className="next-cockpit-reading-why">{noticeToolOutput(output)}</p> : null}
      </div>
      <div className="next-cockpit-reading-ask">{children}</div>
    </Card>
  );
}

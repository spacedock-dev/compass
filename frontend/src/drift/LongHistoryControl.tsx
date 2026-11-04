import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import {
  readingLongHistory,
  readingLongDiscard,
  type LongHistory,
  type HistoryItem,
} from '../api/longHistory';
import { Disclosure } from '../controls/Disclosure';
import { ActionButton } from '../intent/ActionButton';
import { isSampleSession } from '../intent/liveMonitor';
import { useDrift } from './context';

const number = (n: number) => n.toLocaleString('en-US');
const date = (n: number | null) =>
  n === null
    ? 'Not recorded'
    : Number.isNaN(new Date(n * 1000).getTime())
      ? `${n} seconds since Unix epoch`
      : new Date(n * 1000).toLocaleString();
function Accounting({ item }: { readonly item: HistoryItem }) {
  const totals = item.accounting === 'exact' ? item.exact : item.minimum;
  if (!totals)
    return <p>Recorded accounting: unknown. Calls and reserved allocations are unknown.</p>;
  return (
    <p>
      {item.accounting === 'exact'
        ? 'Exact recorded accounting: '
        : 'Minimum recorded accounting: at least '}
      {number(totals.calls)} calls; {number(totals.prompt_bytes)} reserved prompt bytes;{' '}
      {number(totals.reply_bytes)} reserved reply bytes.
    </p>
  );
}

/** Only explicit open/Refresh/discard handlers send requests; restoration and polling are inert. */
export function LongHistoryControl() {
  const { ctx, model } = useDrift();
  const enabled = Boolean(model.annotate && model.identity && !isSampleSession(model.session));
  const allowed = useRef(enabled);
  const [history, setHistory] = useState<LongHistory | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const active = useRef(true);
  const request = useRef<AbortController | null>(null);
  const refreshKey = `long-history-refresh:${model.key}`;
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
      request.current?.abort();
    };
  }, []);
  useLayoutEffect(() => {
    allowed.current = enabled;
    if (!enabled) request.current?.abort();
  }, [enabled]);
  if (!enabled || !model.identity) return null;
  const identity = model.identity;
  const current = (controller: AbortController) =>
    active.current && allowed.current && !controller.signal.aborted;
  async function perform(job?: string) {
    if (request.current || !allowed.current) return;
    if (
      job &&
      !history?.items.some(
        (item) => item.job_id === job && item.state !== 'active' && item.accounting === 'exact',
      )
    )
      return;
    const controller = new AbortController();
    request.current = controller;
    setBusy(true);
    setMessage('');
    try {
      if (!job) {
        const reply = await ctx.shell.runtime.client.getReadingLongHistory(
          identity,
          controller.signal,
        );
        if (!current(controller)) return;
        const parsed = reply.kind === 'ok' ? readingLongHistory(reply.body) : null;
        if (parsed) setHistory(parsed);
        else
          setMessage(
            'Recovery records could not be read. Any earlier inspection remains below. Refresh to try again.',
          );
      } else {
        const reply = await ctx.shell.runtime.client.postReadingLongDiscard(
          { ...identity, job, press: true, observer_model: 1 },
          controller.signal,
        );
        if (!current(controller)) return;
        const parsed =
          reply.kind === 'ok' || reply.kind === 'http-error'
            ? readingLongDiscard(reply.body)
            : null;
        if (reply.kind === 'ok' && reply.status === 200 && parsed?.discarded) {
          setHistory((old) =>
            old ? { ...old, items: old.items.filter((item) => item.job_id !== job) } : old,
          );
          setMessage(
            parsed.reason === 'receipt-unresolved'
              ? 'The recovery record was removed, but some local cleanup remains unconfirmed. Recorded calls remain counted.'
              : 'The recovery record was removed. Recorded calls remain counted.',
          );
        } else if (parsed && !parsed.discarded) {
          setMessage(
            'The server did not confirm a discard. Refresh to inspect current records. Nothing will be retried automatically.',
          );
        } else {
          setMessage(
            'Could not confirm whether the record was removed. Refresh to inspect current records. Nothing will be retried automatically.',
          );
        }
      }
    } catch {
      if (current(controller))
        setMessage(
          job
            ? 'Could not confirm whether the record was removed. Refresh to inspect current records. Nothing will be retried automatically.'
            : 'Recovery records could not be read. Refresh to try again.',
        );
    } finally {
      if (request.current === controller) request.current = null;
      if (active.current) setBusy(false);
    }
  }
  return (
    <section data-next-long-history>
      <Disclosure
        disclosureKey={`long-history:${model.key}`}
        summary="Unfinished long analysis records"
        focusKey={`long-history:${model.key}`}
        onOpenPress={() => {
          if (!history) void perform();
        }}
      >
        <div className="flex flex-col gap-2">
          <p>
            This inspection shows recorded state. It does not establish whether a process is alive.
            Reserved allocations are not measured provider usage.
          </p>
          <p>
            Discard checks eligibility again on the server and removes only an eligible recovery
            record. It cannot stop a model or refund calls.
          </p>
          <ActionButton
            label={busy ? 'Checking recovery records…' : 'Refresh recovery records'}
            inert={busy}
            focusKey={refreshKey}
            onPress={() => {
              void perform();
            }}
          />
          {message ? <p role="status">{message}</p> : null}
          {!history ? (
            <p>Recovery records have not been read in this view.</p>
          ) : (
            <>
              {history.incomplete ? (
                <p>
                  This inspection is incomplete. Some records or accounting could not be
                  established.
                </p>
              ) : null}
              {!history.items.length ? <p>No records are listed in this inspection.</p> : null}
              {history.items.map((item) => (
                <div key={item.job_id} className="flex flex-col gap-2">
                  <p>
                    Record {item.job_id}. Recorded state: {item.state}. Settlement:{' '}
                    {item.unsettled === null ? 'unknown' : item.unsettled ? 'unsettled' : 'settled'}
                    .
                  </p>
                  <p>
                    Started: {date(item.started_at)}. Updated: {date(item.updated_at)}. Terminal
                    time: {date(item.terminal_at)}.
                  </p>
                  <Accounting item={item} />
                  {item.state !== 'active' && item.accounting === 'exact' ? (
                    <ActionButton
                      label="Check and discard superseded record"
                      inert={busy}
                      focusKey={`long-discard:${model.key}:${item.job_id}`}
                      fallbackKey={refreshKey}
                      onPress={() => {
                        void perform(item.job_id);
                      }}
                    />
                  ) : null}
                </div>
              ))}
            </>
          )}
        </div>
      </Disclosure>
    </section>
  );
}

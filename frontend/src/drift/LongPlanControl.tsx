import { useEffect, useId, useRef, useState } from 'react';
import { readingLongPlan, type LongPlanDescriptor } from '../api/longPlan';
import { nextNumber } from '../api/bootstrap';
import { isSampleSession } from '../intent/liveMonitor';
import { ActionButton } from '../intent/ActionButton';
import { Button } from '../ui/button';
import { useDrift } from './context';
import { askForReading } from './actions';
import type { Board } from './flip';

const amount = (n: number | null, unit = 'bytes') =>
  n === null ? 'Unknown' : `${n.toLocaleString('en-US')} ${unit}`;
const date = (n: number | null) =>
  n === null
    ? 'Unknown'
    : Number.isNaN(new Date(n * 1000).getTime())
      ? `${n} seconds since Unix epoch`
      : new Date(n * 1000).toLocaleString();
const REASONS: Readonly<Record<string, string>> = {
  'unsupported-source': 'Long analysis is not supported for this source.',
  'source-unavailable': 'A supported native source has not been confirmed.',
  'route-unavailable': 'The selected model route is unavailable.',
  'capacity-unavailable': 'The current prompt allowance is unknown.',
  'intent-unavailable': 'Save your intent before requesting a long preview.',
  'intent-ineligible': 'The saved intent is not ready to analyze yet.',
  'allowance-unavailable': 'Model calls are paused, unavailable, or out of allowance.',
};

function PlanDetails({ preview }: { readonly preview: LongPlanDescriptor }) {
  const { route, intent, source, allowance, plan, prompt } = preview;
  return (
    <div className="flex flex-col gap-2 next-cockpit-reading-why">
      <p>
        Reader: {route ? `${route.provider} · ${route.model}` : 'Unknown'}. Session words:{' '}
        {route?.words_destination || 'No destination reported'}. Tool output:{' '}
        {route?.destination || 'No destination reported'}.
      </p>
      <p>
        Saved intent revision: {intent.revision ?? 'Unknown'}. Read work from:{' '}
        {date(intent.start_at)}.
      </p>
      <p>
        Source:{' '}
        {source.kinds.length ? 'Native parent session and admitted subagents' : 'Not confirmed'}.
        Parent file extent: {amount(source.parent_bytes)}. Metadata observed:{' '}
        {date(source.observed_at)}. Stream and record counts: Unknown.
      </p>
      <p>
        This is an estimate. The source endpoint is frozen only when you press Start; parent file
        extent excludes subagents and repeated reads.
      </p>
      {plan ? (
        <>
          <p>
            At most {plan.max_evidence_passes} evidence calls + {plan.max_reconciliation_passes}{' '}
            reconciliation call ({plan.max_calls} calls total), sharing the ordinary daily
            allowance.
          </p>
          <p>
            Each assembled prompt: {amount(plan.limits.prompt_bytes)} maximum. Saved ceiling:{' '}
            {amount(prompt.saved_ceiling_bytes)}; route ceiling:{' '}
            {amount(prompt.route_ceiling_bytes)}. Fit is checked again for every actual prompt.
          </p>
          <p>
            All assembled prompts: {amount(plan.limits.input_bytes)} maximum, counting repeated
            input. Captured reply allocation: {amount(plan.limits.reply_bytes)} per call;{' '}
            {amount(plan.limits.output_bytes)} total. These allocations are not measured provider
            usage.
          </p>
          <p>
            Native source I/O: {amount(plan.limits.source_bytes)} maximum, including repeated
            verification reads; {amount(plan.limits.source_pages, 'pages')} maximum.
          </p>
          <p>
            Retained object graph: {amount(plan.limits.retained_bytes)} and{' '}
            {amount(plan.limits.retained_units, 'units')} maximum, not process RSS.
          </p>
          <p>
            Source collection and revalidation: {amount(plan.limits.prepare_ms / 1000, 'seconds')}.
            Whole job: {amount(plan.limits.job_ms / 1000, 'seconds')} maximum.
          </p>
        </>
      ) : null}
      <p>
        Current shared allowance: {allowance.remaining ?? 'Unknown'} calls available of{' '}
        {allowance.limit} over {amount(allowance.window_seconds / 3600, 'hours')}. Calls are not
        reserved; this is not a guarantee that the whole plan can run.
      </p>
      {preview.reason ? <p>{REASONS[preview.reason]}</p> : null}
    </div>
  );
}

/** Fetch only in explicit handlers. Navigation/unmount cancels and ignores late answers. */
export function LongPlanControl({ board }: { readonly board: Board }) {
  const { ctx, model } = useDrift();
  const [open, setOpen] = useState(false);
  const [preview, setPreview] = useState<LongPlanDescriptor | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [used, setUsed] = useState(false);
  const attempted = useRef(false);
  const active = useRef(true);
  const request = useRef<AbortController | null>(null);
  const panel = useId();
  const focusKey = `long-start:${model.key}`;
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
      request.current?.abort();
    };
  }, []);
  if (
    !model.annotate ||
    !model.identity ||
    model.harness !== 'claude' ||
    isSampleSession(model.session)
  )
    return null;
  const identity = model.identity;
  async function load() {
    if (request.current) return;
    const controller = new AbortController();
    request.current = controller;
    setLoading(true);
    setError('');
    setPreview(null);
    try {
      const reply = await ctx.shell.runtime.client.getReadingLongPlan(identity, controller.signal);
      if (!active.current || controller.signal.aborted) return;
      const parsed = reply.kind === 'ok' ? readingLongPlan(reply.body) : null;
      setPreview(parsed);
      if (parsed) {
        attempted.current = false;
        setUsed(false);
      } else
        setError('The long preview is unavailable or could not be read. Refresh it to try again.');
    } catch {
      if (active.current && !controller.signal.aborted)
        setError('The long preview could not be read. Refresh it to try again.');
    } finally {
      if (request.current === controller) request.current = null;
      if (active.current) setLoading(false);
    }
  }
  const blocked =
    used || loading || !preview?.can_start || Boolean(board.reason || model.job || model.unsettled);
  const answer = ctx.intent.held.requests.get(model.key)?.message;
  return (
    <section className="flex flex-col gap-2" data-next-long-plan>
      <Button
        type="button"
        aria-expanded={open}
        aria-controls={panel}
        onClick={() => {
          setOpen(!open);
          if (!open && !preview) void load();
        }}
      >
        Long analysis options
      </Button>
      {open ? (
        <div id={panel} className="flex flex-col gap-2">
          {loading ? <p role="status">Reading the long analysis preview…</p> : null}
          {error ? <p role="status">{error}</p> : null}
          {preview ? <PlanDetails preview={preview} /> : null}
          {preview?.supported ? (
            <ActionButton
              label="Start long analysis"
              busyLabel="Starting…"
              pendingKey={`reading:${model.key}`}
              focusKey={focusKey}
              inert={blocked}
              onPress={() => {
                if (blocked || attempted.current || !preview) return;
                attempted.current = true;
                setUsed(true);
                void askForReading(ctx, identity, {
                  route: model.route,
                  revision: nextNumber(model.annotation?.['revision']) || 0,
                  longPlan: preview,
                  focusKey,
                });
              }}
            />
          ) : null}
          {used ? (
            <p>Refresh the long preview before another Start. Nothing is retried automatically.</p>
          ) : null}
          {used && answer ? <p role="status">{answer}</p> : null}
          {board.reason ? <p>{board.reason}</p> : null}
          {!loading ? (
            <ActionButton
              label="Refresh long preview"
              focusKey={`long-refresh:${model.key}`}
              onPress={() => {
                void load();
              }}
            />
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

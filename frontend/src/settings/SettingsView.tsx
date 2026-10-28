import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react';
import type { ApiClient } from '../api/client';
import type { ApiResult, SettingsBody } from '../api/types';
import { useShell } from '../shell/context';
import { Alert } from '../ui/alert';
import { Button } from '../ui/button';
import { Input } from '../ui/input';
import { Label } from '../ui/label';
import {
  changedValues,
  fieldsOf,
  parseDraft,
  rangeText,
  settingsBody,
  textOf,
  withUnit,
  type Field,
} from './model';

/* The Settings screen: the reader's limits on how much of a session an Analyze drift press reads. It reads
   them once on arrival and writes only on a press. What the reader typed survives a refused write, and an
   accepted one redraws from the server's answer rather than from what was sent, because the answer is what
   the next press will use. */

export type SettingsClient = Pick<ApiClient, 'getSettings' | 'postSettings'>;

type Load =
  | { readonly state: 'loading' }
  | { readonly state: 'failed' }
  | { readonly state: 'ready'; readonly body: SettingsBody };

type Outcome = { readonly tone: 'saved' | 'refused'; readonly text: string } | null;

/** Which press is in flight: Save, Restore all, or one field's Restore default. */
type Pending = 'save' | 'restore-all' | `restore:${string}` | null;

const INTRO =
  'These limits decide how much of a session an Analyze drift press reads. A change applies to the next press; nothing already read changes.';

function refusal(result: Exclude<ApiResult<unknown>, { kind: 'ok' }>): string {
  if (result.kind === 'http-error' && result.status === 400)
    return 'The server refused these values, so nothing was saved. Each must be a whole number inside its range.';
  if (result.kind === 'http-error' && result.status === 503)
    return 'The settings could not be written, so nothing changed. Try again.';
  if (result.kind === 'http-error')
    return `The server answered ${String(result.status)}, so nothing was saved.`;
  if (result.kind === 'malformed')
    return 'The server answered in a form this page cannot read. Reload to see the values in force.';
  return 'The server could not be reached, so nothing was saved.';
}

/* A field's words after an accepted write: what was sent, and what the reader had not touched, take the
   answer; an edit the write did not include is the reader's and stays. */
function redraw(
  before: readonly Field[],
  after: readonly Field[],
  drafts: Readonly<Record<string, string>>,
  sent: ReadonlySet<string>,
): Record<string, string> {
  const next: Record<string, string> = {};
  for (const field of after) {
    const old = before.find((candidate) => candidate.key === field.key);
    const draft = drafts[field.key];
    const untouched = draft === undefined || !old || draft === textOf(old.value);
    next[field.key] = sent.has(field.key) || untouched ? textOf(field.value) : draft;
  }
  return next;
}

function SettingField({
  field,
  draft,
  pending,
  onChange,
  onRestore,
}: {
  readonly field: Field;
  readonly draft: string;
  readonly pending: Pending;
  readonly onChange: (value: string) => void;
  readonly onRestore: () => void;
}) {
  const id = `next-setting-${field.key}`;
  const parsed = draft === textOf(field.value) ? null : parseDraft(field, draft);
  const error = parsed && !parsed.ok ? parsed.error : null;
  const describedBy = [
    field.help ? `${id}-help` : null,
    `${id}-bounds`,
    error ? `${id}-error` : null,
  ]
    .filter(Boolean)
    .join(' ');
  const restoring = pending === `restore:${field.key}`;
  return (
    <div className="flex flex-col gap-2" data-next-setting={field.key}>
      <Label htmlFor={id} className="text-body font-bold text-foreground">
        {/* The unit is named where the reader types in one the server does not store. */}
        {field.scale === 1 ? field.label : `${field.label} (${field.unit})`}
      </Label>
      {field.help ? (
        <p id={`${id}-help`} className="m-0 text-body text-muted-foreground">
          {field.help}
        </p>
      ) : null}
      <p id={`${id}-bounds`} className="m-0 text-label text-muted-foreground">
        {`In force: ${withUnit(field, field.value)}. Default ${withUnit(field, field.fallback)}. ${rangeText(field)}`}
      </p>
      <div className="flex flex-wrap items-center gap-3">
        <Input
          id={id}
          name={field.key}
          type="number"
          inputMode="numeric"
          min={field.minimum}
          max={field.maximum}
          step={1}
          value={draft}
          aria-invalid={error ? true : undefined}
          aria-describedby={describedBy}
          className="max-w-[12rem]"
          onChange={(event) => onChange(event.currentTarget.value)}
        />
        {field.value === field.fallback ? null : (
          <Button
            type="button"
            variant="quiet"
            aria-busy={restoring ? true : undefined}
            busyLabel="Restoring…"
            disabled={pending !== null && !restoring}
            onClick={onRestore}
          >
            {`Restore default (${withUnit(field, field.fallback)})`}
          </Button>
        )}
      </div>
      {error ? (
        <p id={`${id}-error`} className="m-0 text-body text-foreground">
          {error}
        </p>
      ) : null}
    </div>
  );
}

export function SettingsScreen({ client }: { readonly client: SettingsClient }) {
  const [load, setLoad] = useState<Load>({ state: 'loading' });
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [pending, setPending] = useState<Pending>(null);
  const [outcome, setOutcome] = useState<Outcome>(null);
  const [attempt, setAttempt] = useState(0);
  const write = useRef<AbortController | null>(null);
  const form = useRef<HTMLFormElement | null>(null);

  // biome-ignore lint/correctness/useExhaustiveDependencies: a Try again press is the trigger, not a value the body reads.
  useEffect(() => {
    const controller = new AbortController();
    void client.getSettings({ signal: controller.signal }).then((result) => {
      if (result.kind === 'aborted') return;
      const body = result.kind === 'ok' ? settingsBody(result.body) : null;
      if (!body) {
        setLoad({ state: 'failed' });
        return;
      }
      setLoad({ state: 'ready', body });
      setDrafts(
        Object.fromEntries(fieldsOf(body).map((field) => [field.key, textOf(field.value)])),
      );
    });
    return () => controller.abort();
  }, [client, attempt]);

  // A write still in flight when the screen goes away is abandoned, not drawn into a screen nobody sees.
  useEffect(() => () => write.current?.abort(), []);

  const fields = load.state === 'ready' ? fieldsOf(load.body) : [];

  const send = useCallback(
    async (press: Exclude<Pending, null>, values: Record<string, number | null>, done: string) => {
      if (load.state !== 'ready' || write.current) return;
      const controller = new AbortController();
      write.current = controller;
      setPending(press);
      setOutcome(null);
      const result = await client.postSettings({ values }, controller.signal);
      write.current = null;
      if (result.kind === 'aborted') return;
      setPending(null);
      const body = result.kind === 'ok' ? settingsBody(result.body) : null;
      if (result.kind !== 'ok') {
        setOutcome({ tone: 'refused', text: refusal(result) });
        return;
      }
      if (!body) {
        setOutcome({
          tone: 'refused',
          text: refusal({ kind: 'malformed', status: result.status }),
        });
        return;
      }
      const before = fieldsOf(load.body);
      setLoad({ state: 'ready', body });
      setDrafts((current) => redraw(before, fieldsOf(body), current, new Set(Object.keys(values))));
      setOutcome({ tone: 'saved', text: done });
    },
    [client, load],
  );

  const onSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (pending !== null) return;
    const { values, invalid } = changedValues(fields, drafts);
    if (invalid.length > 0) {
      setOutcome({
        tone: 'refused',
        text: 'Nothing was saved. Correct the value marked below first.',
      });
      form.current?.querySelector<HTMLInputElement>(`[name="${invalid[0] ?? ''}"]`)?.focus();
      return;
    }
    if (Object.keys(values).length === 0) {
      setOutcome({ tone: 'saved', text: 'Nothing changed, so nothing was sent.' });
      return;
    }
    void send('save', values, 'Saved. The next Analyze drift press reads with these limits.');
  };

  if (load.state === 'loading')
    return (
      <section
        className="next-view"
        data-next-view-body="settings"
        data-next-settings-state="loading"
      >
        <h1>Settings</h1>
        <p className="next-absence">Reading the settings in force.</p>
      </section>
    );
  if (load.state === 'failed')
    return (
      <section
        className="next-view"
        data-next-view-body="settings"
        data-next-settings-state="failed"
      >
        <h1>Settings</h1>
        <p className="next-absence">The settings could not be read, so none are shown.</p>
        <div className="mt-4">
          <Button
            type="button"
            variant="retry"
            onClick={() => {
              setLoad({ state: 'loading' });
              setAttempt((count) => count + 1);
            }}
          >
            Try again
          </Button>
        </div>
      </section>
    );

  const anyChanged = fields.some((field) => field.value !== field.fallback);
  return (
    <section className="next-view" data-next-view-body="settings" data-next-settings-state="ready">
      <h1>Settings</h1>
      <form
        ref={form}
        noValidate
        aria-labelledby="next-settings-reading"
        className="mt-4 flex max-w-[var(--measure)] flex-col gap-6"
        onSubmit={onSubmit}
      >
        <div className="flex flex-col gap-2">
          <h2 id="next-settings-reading" className="m-0 text-value font-bold">
            Analyze drift reading limits
          </h2>
          <p className="m-0 text-body text-muted-foreground">{INTRO}</p>
        </div>
        {fields.map((field) => (
          <SettingField
            key={field.key}
            field={field}
            draft={drafts[field.key] ?? textOf(field.value)}
            pending={pending}
            onChange={(value) => setDrafts((current) => ({ ...current, [field.key]: value }))}
            onRestore={() =>
              void send(
                `restore:${field.key}`,
                { [field.key]: null },
                `${field.label} is back to its default, ${withUnit(field, field.fallback)}.`,
              )
            }
          />
        ))}
        <div className="flex flex-wrap items-center gap-3">
          <Button
            type="submit"
            variant="primary"
            aria-busy={pending === 'save' ? true : undefined}
            busyLabel="Saving…"
            disabled={pending !== null && pending !== 'save'}
          >
            Save
          </Button>
          {anyChanged ? (
            <Button
              type="button"
              aria-busy={pending === 'restore-all' ? true : undefined}
              busyLabel="Restoring…"
              disabled={pending !== null && pending !== 'restore-all'}
              onClick={() =>
                void send(
                  'restore-all',
                  Object.fromEntries(fields.map((field) => [field.key, null])),
                  'Every limit is back to its default.',
                )
              }
            >
              Restore all defaults
            </Button>
          ) : null}
        </div>
        {/* Mounted before it has anything to say: a status node that arrives carrying its words is the one
            a screen reader skips. */}
        <Alert as="p" variant="intent-note" data-next-settings-outcome={outcome?.tone ?? 'none'}>
          {outcome?.text ?? ''}
        </Alert>
      </form>
    </section>
  );
}

export function SettingsView() {
  const { runtime } = useShell();
  return <SettingsScreen client={runtime.client} />;
}

import { useId, useState } from 'react';
import type { PromptCapacityPreview, SettingsBody } from '../api/types';
import { Disclosure, useControls } from '../controls';
import { useControlledDisclosureState } from '../controls/useDisclosureState';
import { GLOSSARY } from '../language/glossary';
import { Button } from '../ui/button';
import { Card } from '../ui/card';
import { Icon } from '../ui/icons';
import { Slider } from '../ui/slider';
import { kilobytes, stopsFor, withUnit, type Field } from './model';

const ESTIMATE_NOTES: Readonly<Partial<Record<PromptCapacityPreview['reason'], string>>> = {
  'settings-refused': 'Claude Code cannot run a progress check while managed-mcp.json is present.',
  'context-config': 'The context settings could not be checked.',
  'context-no-room': 'The current context settings leave no room for a progress check.',
  'context-dynamic':
    'The policy can change when it starts, so Compass cannot estimate the capacity.',
  'context-compaction':
    'Managed settings conflict with keeping compaction off for a progress check.',
  'context-fallback':
    'Managed settings conflict with keeping automatic model switching off for a progress check.',
  unavailable: 'No route is selected for progress checks.',
};

function RouteEstimates({
  capacities,
  field,
}: {
  readonly capacities: SettingsBody['capacities'];
  readonly field: Field;
}) {
  return (
    <ul
      className="m-0 grid list-none gap-2 p-0 text-label text-muted-foreground"
      aria-label="Progress check capacity"
    >
      {(['claude', 'codex'] as const).map((provider) => {
        const estimate = capacities?.[provider];
        return (
          <li key={provider}>
            <strong>{provider === 'claude' ? 'Claude Code' : 'Codex'}: </strong>
            {estimate?.reason === 'estimated' ? (
              <>
                <span>{`Estimated capacity: ${kilobytes(estimate.maximum_prompt_bytes)}.`}</span>
                {estimate.window_source === 'unknown'
                  ? ' This is a cautious estimate. The context window is unknown.'
                  : ''}
                {estimate.maximum_prompt_bytes < field.minimum ? (
                  <p className="m-0">
                    This estimate is below the minimum prompt size. A smaller actual prompt may
                    still fit.
                  </p>
                ) : null}
              </>
            ) : (
              <span>
                {estimate
                  ? ESTIMATE_NOTES[estimate.reason]
                  : 'Capacity unknown. Compass did not receive a usable estimate.'}
              </span>
            )}
          </li>
        );
      })}
    </ul>
  );
}

export function LimitSlider({
  field,
  locked,
  onWrite,
}: {
  readonly field: Field;
  readonly locked: boolean;
  readonly onWrite: (value: number | null) => Promise<void>;
}) {
  const id = useId();
  const [draft, setDraft] = useState<number | null>(null);
  const stops = stopsFor(field);
  const index = stops.indexOf(draft ?? field.value);
  const changed = field.value !== field.fallback;
  const text = (stop: number) => withUnit(field, stops[stop] ?? field.value);
  return (
    <div
      className="min-w-0 py-2"
      data-settings-limit={field.key}
      data-authored={field.help ? undefined : ''}
    >
      <div className="flex flex-wrap items-baseline justify-between gap-x-2">
        <span className="font-semibold" data-authored={field.help ? undefined : ''}>
          {field.label}
        </span>
        <strong className="tabular-nums">{withUnit(field, draft ?? field.value)}</strong>
      </div>
      {field.help ? (
        <p id={id} className="m-0 text-muted-foreground">
          {field.help}
        </p>
      ) : null}
      {stops.length > 1 ? (
        <Slider
          label={field.label}
          {...(field.help ? { description: id } : {})}
          value={index < 0 ? stops.indexOf(field.value) : index}
          lastStop={stops.length - 1}
          recommended={stops.indexOf(field.fallback)}
          valueText={text}
          disabled={locked}
          onChange={(stop) => setDraft(stops[stop] ?? null)}
          onCancel={() => setDraft(null)}
          onRelease={(stop) => {
            const value = stops[stop];
            if (value === undefined || value === field.value) {
              setDraft(null);
              return;
            }
            void onWrite(value).finally(() => setDraft(null));
          }}
        />
      ) : null}
      <div className="grid grid-cols-[1fr_auto_1fr] items-start gap-1 text-label text-muted-foreground [overflow-wrap:anywhere]">
        <span>{withUnit(field, field.minimum)}</span>
        <span className="text-center">{`Recommended: ${withUnit(field, field.fallback)}`}</span>
        <span className="text-end">{withUnit(field, field.maximum)}</span>
      </div>
      {changed ? (
        <div className="mt-1 flex flex-wrap items-center gap-2 text-label">
          <span className="rounded-pill bg-accent px-2 py-1 font-semibold">Changed</span>
          <Button
            type="button"
            variant="quiet"
            className="[border-color:var(--line-hi)]"
            aria-label={`Reset ${field.label}`}
            disabled={locked}
            onClick={() => void onWrite(null)}
          >
            <Icon name="reset" /> Reset
          </Button>
        </div>
      ) : null}
    </div>
  );
}

const KEY = 'settings:customize';

export function SettingsLimitsCard({
  fields,
  capacities,
  locked,
  onWrite,
  outcome,
}: {
  readonly fields: readonly Field[];
  readonly capacities: SettingsBody['capacities'];
  readonly locked: boolean;
  readonly onWrite: (values: Record<string, number | null>) => Promise<void>;
  readonly outcome: string;
}) {
  const name = useId();
  const { disclosures } = useControls();
  const open = useControlledDisclosureState(disclosures, KEY);
  const changed = fields.filter((field) => field.value !== field.fallback).length;
  const prompt = fields.find((field) => field.key === 'analyze_prompt_bytes');
  const codex = capacities?.codex;
  const warning =
    prompt && codex?.reason === 'estimated' && prompt.value > codex.maximum_prompt_bytes;
  const row = (field: Field) => (
    <LimitSlider
      key={field.key}
      field={field}
      locked={locked}
      onWrite={(value) => onWrite({ [field.key]: value })}
    />
  );
  return (
    <Card as="section" aria-labelledby={name} className="relative mt-4 p-4 sm:p-6">
      <div className="sm:pe-32">
        <h2 id={name} className="m-0 text-value font-bold">
          {GLOSSARY.progressCheckReadSize.plain}
        </h2>
        <p className="mt-1 mb-0 text-body text-muted-foreground">
          {changed
            ? `${changed} ${changed === 1 ? 'limit' : 'limits'} changed.`
            : 'Using the recommended limits.'}{' '}
          Bigger limits read more but take longer.
        </p>
      </div>
      <Disclosure
        disclosureKey={KEY}
        searchable={false}
        summary={open ? 'Done' : 'Customize'}
        triggerClassName="my-2 rounded-control border border-solid border-[var(--line)] px-3 text-body font-semibold sm:absolute sm:inset-e-6 sm:top-6 sm:m-0 [&_[data-slot=disclosure-chevron]]:hidden"
      >
        <div className="mt-3 flex flex-col gap-3 text-body">
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-control bg-muted p-3">
            <p className="m-0 max-w-[38ch] text-label text-muted-foreground">
              Changes apply to the next progress check. A dot marks each recommended limit.
            </p>
            <Button
              type="button"
              variant="quiet"
              className="[border-color:var(--line-hi)]"
              disabled={locked}
              onClick={() => void onWrite(Object.fromEntries(fields.map(({ key }) => [key, null])))}
            >
              Reset all to recommended
            </Button>
          </div>
          {prompt ? (
            <div className="[border-block-end:1px_solid_var(--rule)] pb-3">
              <h3 className="m-0 text-label font-semibold">
                What a progress check sends to the AI
              </h3>
              {row(prompt)}
              <RouteEstimates capacities={capacities} field={prompt} />
              <p className="mt-2 mb-0 text-label text-muted-foreground">
                These estimates cannot confirm that a prompt will fit. Compass refuses a prompt
                above the route's estimate before contacting the model, and keeps your saved
                setting.
              </p>
              {warning ? (
                <p className="mt-2 mb-0 text-body font-semibold">{`The saved prompt size exceeds the Codex estimate of ${kilobytes(codex.maximum_prompt_bytes)}.`}</p>
              ) : null}
            </div>
          ) : null}
          <div>
            <h3 className="m-0 text-label font-semibold">
              What a progress check gathers from the session
            </h3>
            {fields.filter((field) => field !== prompt).map(row)}
          </div>
        </div>
      </Disclosure>
      <p role="status" className="m-0 text-label">
        {outcome}
      </p>
    </Card>
  );
}

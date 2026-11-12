import { Card } from '../ui/card';
import { Button } from '../ui/button';
import { useId, useState, type FormEvent, type KeyboardEvent } from 'react';
import { CharacterCount } from '../ui/CharacterCount';
import { DraftInput } from '../controls/DraftField';
import { useShell } from '../shell/context';
import { useFocusKey } from '../controls/useFocusKey';
import { useControls } from '../controls/kit';
import { RailHeader } from './RailHeader';
import { GUARDRAIL_LIMIT, type GuardrailChange, type GuardrailRule } from '../storage';
import { TEXT_LIMIT, useHeldVersion, useSteeringHeld } from './held';
import './steering.css';

/* The tripwires a reader keeps for a project: browser preferences, never instructions sent to a session. The
   panel says so in its heading and again beneath the rows, because nothing on this page enforces them, and a
   control that looks like a guard and is not one is the false reassurance this board exists to avoid.

   The rules live in the guardrail store (the released `compass.next.guardrails.` family, older string rules
   still readable); what is typed and not yet added, and whether the add box is open, live in the held state
   by the exact project label. */
export function Tripwires({ project }: { readonly project: string }) {
  const { runtime } = useShell();
  const held = useSteeringHeld();
  useHeldVersion(held);
  const rules = runtime.storage.guardrails.rules(project);
  const [staleProject, setStaleProject] = useState<string | null>(null);
  const changed = (change: GuardrailChange) => {
    setStaleProject(change.refused === 'stale' ? project : null);
    held.notify();
  };
  return (
    <Card
      as="section"
      variant="rail-panel"
      className="next-control next-guardrails next-rail-panel"
      data-next-guardrails
      data-next-rail-panel="tripwires"
    >
      <RailHeader
        label="TRIPWIRES"
        note="local only · nothing enforces these"
        tone="amber"
        sentence
      />
      <div className="next-guardrail-rows">
        {rules.length === 0 ? (
          <p className="next-guardrail-empty">No tripwires saved in this browser.</p>
        ) : (
          rules.map((rule, index) => (
            <RuleRow key={index} project={project} index={index} rule={rule} onChange={changed} />
          ))
        )}
      </div>
      {staleProject === project ? (
        <p role="status">
          Tripwires changed in another tab. Review the refreshed list and try again.
        </p>
      ) : null}
      <AddRule key={project} project={project} />
      <p className="next-rail-reason">
        C1 would let an observer act on these. Until it ships they are a note to yourself, held in
        this browser.
      </p>
    </Card>
  );
}

function RuleRow({
  project,
  index,
  rule,
  onChange,
}: {
  readonly project: string;
  readonly index: number;
  readonly rule: GuardrailRule;
  readonly onChange: (change: GuardrailChange) => void;
}) {
  const { runtime } = useShell();
  const controls = useControls();
  const held = useSteeringHeld();
  const fallback = held.adding(project) ? `guardrail-draft:${project}` : `guardrail-add:${project}`;
  const toggle = useFocusKey<HTMLButtonElement>(
    controls.focusLane,
    `guardrail:${project}:${index}:toggle`,
    { fallback },
  );
  const remove = useFocusKey<HTMLButtonElement>(
    controls.focusLane,
    `guardrail:${project}:${index}:remove`,
    { fallback },
  );
  return (
    <div className="flex items-center gap-2">
      <Button
        variant="native"
        ref={toggle}
        type="button"
        className="next-guardrail-row"
        role="switch"
        aria-checked={rule.enabled}
        data-next-guardrail-toggle={index}
        data-next-controls-project={project}
        onClick={() => {
          onChange(runtime.storage.guardrails.toggle(project, rule));
        }}
      >
        <span className="next-guardrail-glyph" aria-hidden="true">
          ◇
        </span>
        <span className="next-guardrail-copy">
          <strong>{rule.text}</strong>
          {rule.enabled ? null : <small>Disabled in this browser.</small>}
        </span>
      </Button>
      <Button
        ref={remove}
        type="button"
        aria-label={`Remove tripwire: ${rule.text}`}
        onClick={(event) => {
          const focused = document.activeElement === event.currentTarget;
          onChange(runtime.storage.guardrails.remove(project, rule));
          // A positional row may be reused for its successor; move off that removed rule explicitly.
          if (focused) queueMicrotask(() => controls.focusLane.focus(fallback));
        }}
      >
        Remove
      </Button>
    </div>
  );
}

const LIMIT_SENTENCE = 'You have 50 tripwires on this project. Remove one to add another.';

function AddRule({ project }: { readonly project: string }) {
  const { runtime } = useShell();
  const controls = useControls();
  const held = useSteeringHeld();
  const adding = held.adding(project);
  const addKey = `guardrail-add:${project}`;
  const addRef = useFocusKey<HTMLButtonElement>(controls.focusLane, addKey);
  const draftKey = `guardrail-draft:${project}`;
  const atLimit = runtime.storage.guardrails.rules(project).length >= GUARDRAIL_LIMIT;
  const countId = useId();
  const limitId = useId();
  const [length, setLength] = useState(() => [...held.draft(project, 'guardrail')].length);
  const [refused, setRefused] = useState(false);
  const over = length > TEXT_LIMIT;

  /* A refused add keeps the words for another attempt. Added or abandoned, the box must clear too, or
     reopening it would offer the committed rule and one Enter would write it again. */
  const finish = (input: HTMLInputElement | null, add: boolean) => {
    if (add && input && [...input.value].length > TEXT_LIMIT) return;
    if (add && input && runtime.storage.guardrails.add(project, input.value).refused) {
      setRefused(true);
      held.notify();
      return;
    }
    held.setAdding(project, false);
    held.clearDraft(project, 'guardrail');
    if (input) input.value = '';
    setLength(0);
    setRefused(false);
    held.notify();
  };

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key !== 'Enter' && event.key !== 'Escape') return;
    /* The Enter that commits a composition belongs to the input method, not to the form: acting on it would
       add a rule from words the reader has not finished choosing. 229 is what browsers that report the
       key after the composition has ended send in its place. */
    if (event.nativeEvent.isComposing || event.keyCode === 229) return;
    event.preventDefault();
    event.stopPropagation();
    finish(event.currentTarget, event.key === 'Enter');
  };

  const onSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const input = event.currentTarget.elements.namedItem('guardrail');
    finish(input instanceof HTMLInputElement ? input : null, true);
  };

  if (adding) {
    return (
      <form
        className="next-guardrail-add-input"
        data-next-guardrail-form
        data-next-controls-project={project}
        onSubmit={onSubmit}
      >
        <label>
          <span className="next-visually-hidden">New local tripwire</span>
          <DraftInput
            memoryKey={draftKey}
            focusKey={draftKey}
            focusFallback={addKey}
            name="guardrail"
            aria-label="New local tripwire"
            aria-describedby={`${countId} ${limitId}`}
            aria-invalid={over || undefined}
            placeholder="alert me when…"
            data-next-guardrail-input
            data-next-draft="guardrail"
            data-next-controls-project={project}
            defaultValue={held.draft(project, 'guardrail')}
            onKeyDown={onKeyDown}
            onInput={(event) => {
              const text = event.currentTarget.value;
              held.setDraft(project, 'guardrail', text);
              setLength([...text].length);
            }}
          />
          <CharacterCount id={countId} length={length} limit={TEXT_LIMIT} />
          <span id={limitId}>{atLimit && !refused ? LIMIT_SENTENCE : ''}</span>
          <span role="status">{atLimit && refused ? LIMIT_SENTENCE : ''}</span>
        </label>
        <Button type="submit" disabled={over}>
          add ↵
        </Button>
      </form>
    );
  }
  return (
    <Button
      ref={addRef}
      type="button"
      tone="muted"
      className="next-guardrail-add"
      data-next-guardrail-add
      data-next-controls-project={project}
      onClick={() => {
        held.setAdding(project, true);
        /* The control that was pressed is gone, and a reader who opened the box is about to type in it. The
           legacy page leaves focus on the document; a keyboard reader would then have to find the box. */
        queueMicrotask(() => controls.focusLane.focus(draftKey));
      }}
    >
      + set a tripwire
    </Button>
  );
}

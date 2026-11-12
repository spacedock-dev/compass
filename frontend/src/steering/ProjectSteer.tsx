import { Card } from '../ui/card';
import { Button } from '../ui/button';
import { useId, useState, type FormEvent } from 'react';
import { CharacterCount } from '../ui/CharacterCount';
import { DraftInput } from '../controls/DraftField';
import { useHeldVersion, useSteeringHeld, TEXT_LIMIT } from './held';
import './steering.css';

/* The project's steering bar. A note to oneself: Compass has no write path into a session, and the bar says
   so before the first keystroke rather than after the press, because a control that promises delivery
   ("Tell this project what to do next", submit "send") and says nothing about what it does would be believed.

   The box is a native, uncontrolled input held by the project's exact label. What is typed is recorded as it
   is typed and handed back as the box's first words when the route returns, and the caret, the selection and
   the scroll travel through the field memory under the same key, so a redraw, a tab change and a trip to
   another page leave the words, the caret and the undo history where they were. Sending clears the draft AND
   the live node: a node left holding the sentence would be read back as the draft. */
export function ProjectSteer({
  project,
  layout = 'next-steer--bar',
}: {
  /** The exact project label. A project with no label is the empty string, a project of its own. */
  readonly project: string;
  readonly layout?: string;
}) {
  const held = useSteeringHeld();
  useHeldVersion(held);
  return (
    <section className={`next-control next-steer${layout ? ` ${layout}` : ''}`} data-next-steer>
      <header>
        <span className="next-steer-label">Your note (this tab only)</span>
        <p className="next-steer-caveat">
          Compass has no write path into a session. Anything you type here is a note to yourself,
          kept in this browser tab.
        </p>
      </header>
      <SteerEditor key={project} project={project} />
      {held.steersDropped(project) ? (
        <p className="next-steer-caveat">Older notes are not kept.</p>
      ) : null}
      {held.steers(project).length ? (
        <div className="next-steer-receipts">
          {held.steers(project).map((record, index) => (
            // The receipts only grow at the end and drop from the front, so a position is not an identity;
            // the tab never reorders them, and nothing in one is editable.
            <Card
              variant="steer-receipt"
              className="next-steer-receipt"
              data-next-steer-receipt
              key={index}
            >
              <strong>{record.text}</strong>
              <p>
                Draft recorded in this tab. Not delivered. Compass has no write path into a session.
              </p>
            </Card>
          ))}
        </div>
      ) : null}
    </section>
  );
}

function SteerEditor({ project }: { readonly project: string }) {
  const held = useSteeringHeld();
  const key = `steer-draft:${project}`;
  const countId = useId();
  const [length, setLength] = useState(() => [...held.draft(project, 'steer')].length);
  const over = length > TEXT_LIMIT;
  const onSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const input = event.currentTarget.elements.namedItem('steer');
    if (!(input instanceof HTMLInputElement)) return;
    if ([...input.value].length > TEXT_LIMIT) return;
    const text = input.value.trim();
    if (!text) return;
    held.recordSteer(project, text);
    // The receipt below carries the sentence now. Leaving it in the box too would show it twice and record
    // it again on the next press.
    held.clearDraft(project, 'steer');
    input.value = '';
    setLength(0);
    held.notify();
  };
  return (
    <form data-next-steer-form data-next-controls-project={project} onSubmit={onSubmit}>
      <label>
        <span className="next-visually-hidden">Steer draft</span>
        <DraftInput
          memoryKey={key}
          focusKey={key}
          name="steer"
          aria-label="Steer draft"
          aria-describedby={countId}
          aria-invalid={over || undefined}
          placeholder="Draft a next step — kept in this tab only"
          data-next-draft="steer"
          data-next-controls-project={project}
          defaultValue={held.draft(project, 'steer')}
          onInput={(event) => {
            const text = event.currentTarget.value;
            held.setDraft(project, 'steer', text);
            setLength([...text].length);
          }}
        />
        <CharacterCount id={countId} length={length} limit={TEXT_LIMIT} />
      </label>
      <Button type="submit" tone="muted" disabled={over}>
        save draft ⏎
      </Button>
    </form>
  );
}

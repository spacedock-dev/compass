import { Alert } from '../ui/alert';
import { Card } from '../ui/card';
import { Button } from '../ui/button';
import { useFocusKey } from '../controls';
import { useDisplayed, useShell } from '../shell/context';
import type { ObservedSession, Row } from '../observed';
import { ANSWER_FAILURE } from './detail';
import { answerNotesFor, useStore } from './heldState';
import { askResponsibility } from './rows';

/* The reader's answer to one exact request. Every request stays in payload order, and one numeric option
   index is posted: the server takes `index` and never `option`, because an answer is a choice among the
   options the session itself offered. A press is one explicit act: nothing here posts on mount, a second
   mount, a poll or a reconnect, and only a confirmed answer clears the failure sentence. The question
   itself leaves when the next payload no longer carries it, because the server drops an answered request
   and the page does not guess. */

const key = (id: string, index: number): string => `answer:${id}:${String(index)}`;

function AnswerButton({
  id,
  index,
  option,
}: {
  readonly id: string;
  readonly index: number;
  readonly option: unknown;
}) {
  const shell = useShell();
  const { runtime, controls } = shell;
  const pending = useDisplayed((snapshot) => snapshot.pending);
  const control = key(id, index);
  const ref = useFocusKey<HTMLButtonElement>(controls.focusLane, control, {
    fallback: 'session-title',
  });
  const busy = pending.includes(control);
  const label = String(option == null ? '' : option);

  const press = async () => {
    if (!id || !Number.isInteger(index) || index < 0) return;
    // One answer to one question at a time: another option waits for this one.
    if (runtime.store.getSnapshot().pending.some((held) => held.startsWith(`answer:${id}:`)))
      return;
    const token = runtime.pending.start(control, 'Sending…');
    if (!token) return;
    const notes = answerNotesFor(runtime);
    const confirmed = await runtime.client.postAnswer({ id, index }, token.signal).then(
      (result) => result.kind === 'ok' && result.body.answered === true,
      () => false,
    );
    if (confirmed) notes.delete(id);
    else notes.set(id, ANSWER_FAILURE);
    // The control stays busy until the board that drops the question has been read: ending it at the confirmation
    // would leave the answered card on screen with live buttons for a second option.
    try {
      if (confirmed) await runtime.refresh();
    } finally {
      runtime.pending.end(control, token);
    }
  };

  return (
    <Button
      ref={ref}
      type="button"
      variant="answer"
      busyLabel="Sending…"
      data-next-answer={id}
      data-next-answer-index={index}
      data-next-focus={control}
      {...(busy ? { 'aria-disabled': true, 'aria-busy': true, 'data-next-pending': '' } : {})}
      onClick={() => void press()}
    >
      {label}
    </Button>
  );
}

export function AnswerBlock({
  payload,
  asks,
  observed,
  title,
}: {
  readonly payload: Row;
  readonly observed: ObservedSession;
  readonly asks: readonly Row[];
  readonly title: string;
}) {
  const { runtime } = useShell();
  const notes = answerNotesFor(runtime);
  const held = useStore(notes);
  return (
    <Card
      as="section"
      variant="session-ask"
      className="next-session-section"
      aria-label="Asked you"
      data-next-session-section="ask"
    >
      <div className="next-session-ask-callout">
        <span>
          {'ASKED YOU · '}
          <span className="next-session-wait" data-known={String(observed.waitedKnown === true)}>
            {observed.waitedText}
          </span>
        </span>
        <strong className="next-visually-hidden">{`AGENT IS ASKING · ${title}`}</strong>
        <section data-next-session-command-fact="request">
          <h2>{askResponsibility(payload, asks[0] ?? {})}</h2>
        </section>
      </div>
      {asks.length ? (
        asks.map((ask, position) => {
          const id = String(ask['id'] || '');
          const options = Array.isArray(ask['options']) ? (ask['options'] as unknown[]) : [];
          const failure = held.get(id);
          return (
            <article
              key={`${id}#${String(position)}`}
              className="next-session-ask"
              data-next-session-ask={id}
            >
              <p className="next-session-ask-question">
                {asks.length === 1
                  ? observed.askText
                  : String(ask['question'] == null ? '' : ask['question'])}
              </p>
              {options.length ? (
                <div className="next-session-answer-options">
                  {options.map((option, index) => (
                    <AnswerButton key={index} id={id} index={index} option={option} />
                  ))}
                </div>
              ) : (
                <p className="next-session-answer-empty">No answer options were supplied.</p>
              )}
              {failure ? (
                <Alert as="p" variant="answer-failure" className="next-session-answer-failure">
                  {failure}
                </Alert>
              ) : null}
            </article>
          );
        })
      ) : (
        <p className="next-session-ask-question">{observed.askText}</p>
      )}
    </Card>
  );
}

import { Card as SurfaceCard } from '../ui/card';
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from '../ui/select';
import { Label } from '../ui/label';
import { Button } from '../ui/button';
import { useEffect, useLayoutEffect, useState, type MouseEvent } from 'react';
import { isRecord, type Row } from '../observed';
import { useControls } from '../controls/kit';
import { useFocusKey } from '../controls/useFocusKey';
import { useDisplayed, useShell } from '../shell/context';
import { useBoardSelector } from '../store/hooks';
import { useHeldVersion, useSteeringHeld } from './held';
import {
  defaultStamp,
  stageCard,
  stageData,
  stageIntro,
  stagePairs,
  type StageCardModel,
  type StageData,
  type StageRule,
  type StageSource,
} from './stage';
import './steering.css';

const SAVE_FAILED = 'Could not save the stage condition.';

export interface StageConditionsProps {
  /** The exact sessions in scope: the focused one, or the project's. Null is every workflow, as the Projects page shows them. */
  readonly sessions: readonly { readonly harness: string; readonly sid: string }[] | null;
  /** The browser notification lane's permission where that lane owns delivery, else null. The notification step supplies it. */
  readonly notifyLane?: (payload: Row) => string | null;
}

/* The lane as the page names it when nothing better is supplied: the browser owns delivery unless the server
   delivers natively, and only where the browser has a Notification to ask. */
function browserLane(payload: Row): string | null {
  if (payload['native_notify']) return null;
  if (typeof Notification === 'undefined') return null;
  return Notification.permission || 'default';
}

export function StageConditions({ sessions, notifyLane = browserLane }: StageConditionsProps) {
  const held = useSteeringHeld();
  useHeldVersion(held);
  const { controls } = useShell();
  const payload = useDisplayed((snapshot) => snapshot.data);
  const data = stageData(payload);

  // A keystroke or a pointer press anywhere means the reader has moved on from the press that asked for
  // focus back. Listened for only while a card is on the page.
  useEffect(() => {
    const release = held.stage.mounted();
    const interacted = () => held.stage.interacted();
    document.addEventListener('pointerdown', interacted, true);
    document.addEventListener('keydown', interacted, true);
    return () => {
      document.removeEventListener('pointerdown', interacted, true);
      document.removeEventListener('keydown', interacted, true);
      release();
    };
  }, [held]);

  /* Focus comes back to the control the reader pressed once the final enabled render has drawn, and only if
     nothing has taken it and they have not touched the page since. The press disables its own button, which
     drops focus to the body, and the redraw that follows is not the reader's doing. */
  useLayoutEffect(() => {
    const request = held.stage.takeFocus();
    if (!request) return;
    const active = document.activeElement;
    const free = !active || active === document.body;
    if (free && request.interaction === held.stage.interaction())
      controls.focusLane.focus(request.key);
  });

  if (!data.enabled) return null;
  const cards = stagePairs(data, sessions);
  const lane = notifyLane((payload ?? {}) as Row);
  return (
    <section className="next-stage-conditions" aria-label="Stage alerts">
      <h2>Stage alerts</h2>
      <p>{stageIntro(data)}</p>
      {cards.length ? (
        cards.map(({ source, rule }) => (
          <Card
            key={(source ?? (rule as StageRule)).id}
            source={source}
            rule={rule}
            data={data}
            lane={lane}
          />
        ))
      ) : (
        <p>Workflow stage source unavailable. Saved conditions remain in Projects.</p>
      )}
    </section>
  );
}

function Card({
  source,
  rule,
  data,
  lane,
}: {
  readonly source: StageSource | null;
  readonly rule: StageRule | null;
  readonly data: StageData;
  readonly lane: string | null;
}) {
  const { runtime } = useShell();
  const held = useSteeringHeld();
  const id = (source ?? (rule as StageRule)).id;
  const pendingKey = `tripwire:${id}`;
  const [owner] = useState(() => Symbol('stage card'));
  useEffect(() => held.stage.cardMounted(owner), [held, owner]);
  const busy = useBoardSelector(runtime.store, (board) => board.pending.includes(pendingKey));
  const model = stageCard({
    source,
    rule,
    draft: held.stage.draft(id),
    busy,
    data,
    lane,
    stamp: defaultStamp,
  });
  const cue = held.stage.cue(id);

  /* A press names what the reader SAW: the rule, the source and the choice this card was drawn with. The
     board that arrives while it is out is a newer reading the reader has not seen, and the server refuses a
     stale revision rather than overwriting it. */
  const press = async (
    action: 'save' | 'rearm' | 'remove',
    event: MouseEvent<HTMLButtonElement>,
  ) => {
    const stage = action === 'save' ? (model.editor?.choice ?? '') : (rule?.stage ?? '');
    if (action === 'save' && !(source && source.stages.includes(stage))) {
      held.stage.setCue(id, 'Choose an available stage before saving.');
      return;
    }
    const token = runtime.pending.start(pendingKey, 'Saving…');
    if (!token) return;
    const key = `stage:${id}:${action}`;
    const focused = document.activeElement === event.currentTarget;
    const interaction = held.stage.interaction();
    held.stage.setCue(id, 'Saving…');
    let cueText = SAVE_FAILED;
    try {
      const result = await runtime.client.postTripwire(
        { action, id, stage, expected_revision: rule?.revision || '' },
        token.signal,
      );
      const body: Row =
        result.kind === 'ok' || result.kind === 'http-error'
          ? ((isRecord(result.body) ? result.body : {}) as Row)
          : {};
      /* An answer the page never read says nothing about whether the server kept the save: the 15 s bound
         abandons the request, not the write. One refresh, which the shell makes explicit, shows what the
         server holds; the cue stays as weak as it was. */
      const unknown =
        result.kind === 'aborted' || result.kind === 'network-error' || result.kind === 'malformed';
      if (result.kind === 'ok' && body['ok']) {
        held.stage.dropDraft(id);
        cueText =
          action === 'remove'
            ? 'Removed.'
            : action === 'rearm'
              ? 'Rearmed; baseline reset.'
              : 'Saved.';
        held.stage.setCue(id, cueText);
        await runtime.refresh();
      } else {
        cueText = typeof body['error'] === 'string' && body['error'] ? body['error'] : SAVE_FAILED;
        held.stage.setCue(id, cueText);
        if (unknown) await runtime.refresh();
      }
    } catch {
      held.stage.setCue(id, cueText);
      await runtime.refresh();
    } finally {
      runtime.pending.end(pendingKey, token);
      if (focused) held.stage.requestFocus({ key, interaction, owner });
    }
  };

  return (
    <CardView
      model={model}
      cue={cue}
      press={press}
      onChoose={(value) => held.stage.setDraft(id, value)}
    />
  );
}

function CardView({
  model,
  cue,
  press,
  onChoose,
}: {
  readonly model: StageCardModel;
  readonly cue: string;
  readonly press: (
    action: 'save' | 'rearm' | 'remove',
    event: MouseEvent<HTMLButtonElement>,
  ) => void;
  readonly onChoose: (value: string) => void;
}) {
  const controls = useControls();
  const id = model.id;
  const choice = useFocusKey<HTMLButtonElement>(controls.focusLane, `stage:${id}:choice`);
  const save = useFocusKey<HTMLButtonElement>(controls.focusLane, `stage:${id}:save`);
  const rearm = useFocusKey<HTMLButtonElement>(controls.focusLane, `stage:${id}:rearm`);
  const remove = useFocusKey<HTMLButtonElement>(controls.focusLane, `stage:${id}:remove`);
  return (
    <SurfaceCard as="article" variant="stage-rule" className="next-stage-rule" data-stage-rule={id}>
      <h3>{model.workflow}</h3>
      <p>{model.scopeLine}</p>
      {model.savedLine === null ? null : <p>{model.savedLine}</p>}
      <p>{model.why}</p>
      <p>{model.coverage}</p>
      <p>{model.times}</p>
      <p>{model.delivery}</p>
      <div className="next-stage-editor">
        {model.editor ? (
          <>
            <Label>
              Alert once when an observed entity enters{' '}
              <Select
                value={model.editor.choice}
                disabled={model.editor.disabled}
                items={model.editor.options}
                onValueChange={(value) => {
                  if (value !== null) onChoose(value);
                }}
              >
                <SelectTrigger
                  ref={choice}
                  data-stage-choice={id}
                  data-next-focus={`stage:${id}:choice`}
                  aria-label="Alert once when an observed entity enters"
                  title={
                    model.editor.options.find((option) => option.value === model.editor?.choice)
                      ?.label ?? model.editor.choice
                  }
                  className="font-medium ps-[6.4px]"
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent data-stage-options={id}>
                  {model.editor.options.map((option, index) => (
                    <SelectItem
                      key={`${String(index)}\u0000${option.value}`}
                      value={option.value}
                      disabled={option.stale}
                    >
                      {option.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Label>
            <Button
              variant="bare"
              ref={save}
              type="button"
              data-stage-id={id}
              data-stage-action="save"
              disabled={model.editor.saveDisabled}
              onClick={(event) => void press('save', event)}
            >
              Save
            </Button>
          </>
        ) : null}
        {model.rearmDisabled === null ? null : (
          <>
            <Button
              variant="bare"
              ref={rearm}
              type="button"
              data-stage-id={id}
              data-stage-action="rearm"
              disabled={model.rearmDisabled}
              onClick={(event) => void press('rearm', event)}
            >
              Rearm
            </Button>
            <Button
              variant="bare"
              ref={remove}
              type="button"
              data-stage-id={id}
              data-stage-action="remove"
              disabled={model.removeDisabled === true}
              onClick={(event) => void press('remove', event)}
            >
              Remove
            </Button>
          </>
        )}
      </div>
      <p role="status">{cue}</p>
    </SurfaceCard>
  );
}

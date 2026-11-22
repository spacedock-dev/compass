import { Textarea } from '../ui/textarea';
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from '../ui/select';
import { Label } from '../ui/label';
import { DraftInput } from './DraftField';
import { Collapsible, CollapsibleTrigger, CollapsibleContent } from '../ui/collapsible';
import { useControlledDisclosureState } from './useDisclosureState';
import { useRevealFragment } from './useRevealFragment';
import { Button, buttonVariants } from '../ui/button';
import { useState } from 'react';
import { memoKey } from '../storage';
import { selectSessions } from '../store/selectors';
import { useBoardRuntime } from '../transport/hooks';
import { CopyControl } from './CopyControl';
import { DraftTextarea } from './DraftField';
import { Disclosure } from './Disclosure';
import { disclosureKey } from './disclosureStore';
import type { World } from './galleryWorld';
import { HumanContextField } from './HumanContextField';
import { useControls } from './kit';
import { MoreMenu } from './MoreMenu';
import { RaiseControl } from './RaiseControl';
import { useChoiceRelease } from './useChoiceRelease';
import { useDisplayedSelector } from './useDisplayed';
import { useFocusKey } from './useFocusKey';

/* Replaced on every paint (its key is the board revision), so a browser test can watch the focus
   lane put focus back on a keyed control that a redraw swapped, with and without a scroll. */
function ParkedControl() {
  const { focusLane } = useControls();
  const ref = useFocusKey<HTMLButtonElement>(focusLane, 'parked');
  return (
    <Button variant="bare" type="button" ref={ref}>
      Parked control
    </Button>
  );
}

function GalleryCollapsible() {
  const controls = useControls();
  const key = 'gallery-collapsible';
  const open = useControlledDisclosureState(controls.disclosures, key);
  const panelRef = useRevealFragment(key);
  return (
    <Collapsible
      className="ctl-disclosure"
      open={open}
      onOpenChange={(next, detail) => {
        if (detail.reason === 'trigger-press') controls.noteToggle();
        controls.disclosures.set(key, next);
      }}
    >
      <CollapsibleTrigger>Collapsible section</CollapsibleTrigger>
      <CollapsibleContent ref={panelRef} hiddenUntilFound>
        <p id="collapsible-fragment">Small collapsible body</p>
      </CollapsibleContent>
    </Collapsible>
  );
}

export function GalleryBoard({ world }: { world: World }) {
  useBoardRuntime(world.runtime);
  useChoiceRelease(world.gate);
  const sessions = useDisplayedSelector(world.gate, selectSessions);
  const displayedAccepted = useDisplayedSelector(world.gate, (snapshot) => snapshot.acceptedCount);
  const displayedGenerated = useDisplayedSelector(
    world.gate,
    (snapshot) => snapshot.data?.generated ?? 0,
  );
  const [choice, setChoice] = useState('');
  const [reservedBusy, setReservedBusy] = useState(false);
  const [draftShown, setDraftShown] = useState(true);
  // The words belong to the caller (here, this state); the field keeps only caret, scroll and size.
  const [draftText, setDraftText] = useState('');
  const [disclosuresShown, setDisclosuresShown] = useState(true);
  const first = sessions.rows[0];
  const second = sessions.rows[1];
  const project = first?.project_key ?? first?.project ?? 'alpha/app';

  return (
    <main id="gallery" data-gallery-project={project}>
      <h1>Shared controls</h1>
      <section aria-label="Button gallery" data-button-gallery style={{ maxWidth: '100%' }}>
        <Button data-example="default">Default action</Button>
        <Button data-example="hover">Hover action</Button>
        <Button data-example="focus">Focus action</Button>
        <Button data-example="pending" aria-busy="true" aria-disabled="true" busyLabel="Saving…">
          Save intent
        </Button>
        <Button data-example="disabled" disabled>
          Unavailable action
        </Button>
        <Button data-example="retry" variant="retry" aria-disabled="true">
          Retry now
        </Button>
        <Button data-example="long">
          Save the long intent that explains every expected outcome to the reader
        </Button>
        <Button data-example="primary" variant="primary">
          Primary action
        </Button>
        <Button data-example="quiet" variant="quiet">
          Quiet action
        </Button>
        <Button data-example="raise-primary" variant="raise-primary">
          RAISE
        </Button>
        <Button
          data-example="reserved"
          reserve="Saving the intent…"
          busyLabel="Saving…"
          {...(reservedBusy ? { 'aria-busy': true, 'aria-disabled': true } : {})}
          onClick={() => setReservedBusy(true)}
        >
          Save
        </Button>
        <a href="#gallery" data-example="link" data-slot="button-link" className={buttonVariants()}>
          Linked action
        </a>
      </section>
      <p>
        Displayed board revision{' '}
        <output data-readout="displayed-accepted">{displayedAccepted}</output>, generated{' '}
        <output data-readout="displayed-generated">{displayedGenerated}</output>
      </p>

      <section aria-label="Field gallery" data-field-gallery>
        {(['prompt', 'stage', 'direction'] as const).map((appearance) => (
          <div key={appearance}>
            <Label htmlFor={`gallery-${appearance}`}>{appearance} choice</Label>
            <Select
              defaultValue="long"
              items={{
                long: "A long choice whose chevron must leave room for the reader's text",
                short: 'Short choice',
              }}
            >
              <SelectTrigger
                id={`gallery-${appearance}`}
                className={
                  appearance === 'prompt'
                    ? 'font-medium ps-[12px]'
                    : appearance === 'stage'
                      ? 'font-medium ps-[6.4px]'
                      : undefined
                }
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="long">
                  A long choice whose chevron must leave room for the reader's text
                </SelectItem>
                <SelectItem value="short">Short choice</SelectItem>
              </SelectContent>
            </Select>
          </div>
        ))}
        <Label htmlFor="gallery-intent">Intent words</Label>
        <Textarea id="gallery-intent" rows={3} defaultValue="Reader's intent" />
        <Label htmlFor="gallery-correction">Correction words</Label>
        <Textarea
          id="gallery-correction"
          appearance="correction"
          rows={6}
          defaultValue="Reader's correction"
        />
        <Label htmlFor="gallery-invalid">Invalid words</Label>
        <Textarea id="gallery-invalid" aria-invalid="true" defaultValue="Invalid words" />
        <Label htmlFor="gallery-unavailable">Unavailable words</Label>
        <Textarea id="gallery-unavailable" disabled defaultValue="Unavailable words" />
        <Label htmlFor="gallery-input">Native input</Label>
        <DraftInput
          id="gallery-input"
          memoryKey="gallery:input"
          defaultValue=""
          autoComplete="off"
          placeholder="Native input"
        />
      </section>
      <section aria-label="Select">
        <Label htmlFor="stage-choice">Stage condition</Label>
        <Select
          value={choice || null}
          onValueChange={(value) => setChoice(value ?? '')}
          items={sessions.rows.map((row) => ({
            value: `${row.harness}:${row.sid}`,
            label: `${row.title ?? row.sid} · ${String(row.harness)} · board ${String(displayedAccepted)}`,
          }))}
        >
          <SelectTrigger id="stage-choice" className="ctl-select">
            <SelectValue placeholder="Choose a session" />
          </SelectTrigger>
          <SelectContent>
            {sessions.rows.map((row) => (
              <SelectItem
                key={`${row.harness}:${row.sid}`}
                value={`${row.harness}:${row.sid}`}
              >{`${row.title ?? row.sid} · ${String(row.harness)} · board ${String(displayedAccepted)}`}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        <output className="ctl-wrap" data-readout="choice">
          {choice}
        </output>
      </section>

      <section aria-label="Session controls">
        {first ? (
          <div>
            <CopyControl kind="id" harness={first.harness} sid={first.sid} value={first.sid} />
            <CopyControl
              kind="link"
              harness={first.harness}
              sid={first.sid}
              value={`${location.origin}/#n=session:${first.sid}`}
            />
            <CopyControl
              kind="command"
              harness={first.harness}
              sid={first.sid}
              value={`claude --resume ${first.sid}`}
            />
            <RaiseControl harness={first.harness} sid={first.sid} focusable />
          </div>
        ) : null}
        {second ? (
          <div>
            <CopyControl kind="id" harness={second.harness} sid={second.sid} value={second.sid} />
            <RaiseControl harness={second.harness} sid={second.sid} focusable />
          </div>
        ) : null}
      </section>

      <section aria-label="Disclosures">
        <Button variant="bare" type="button" onClick={() => setDisclosuresShown(!disclosuresShown)}>
          {disclosuresShown ? 'Hide disclosures' : 'Show disclosures'}
        </Button>
        {disclosuresShown ? (
          <>
            <Disclosure
              disclosureKey={disclosureKey({ project, scope: null, name: 'plan' })}
              summary="Project plan"
              focusKey="gallery-plan"
            >
              <p
                id="disclosure-fragment"
                data-readout="plan-body"
              >{`Plan as of board ${String(displayedAccepted)}`}</p>
              <Button variant="bare" type="button">
                Inside the plan
              </Button>
            </Disclosure>
            <Disclosure
              disclosureKey={disclosureKey({ project, scope: null, name: 'other' })}
              summary="Independent section"
            >
              <p>Another small section</p>
            </Disclosure>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
              <Disclosure
                disclosureKey={disclosureKey({ project, scope: null, name: 'why' })}
                summary="Why"
                variant="popover"
              >
                <p>{`Because of board ${String(displayedAccepted)}`}</p>
                <Button variant="bare">Inside why</Button>
                <a href="#gallery">Popup link</a>
              </Disclosure>
              <Disclosure
                disclosureKey={disclosureKey({ project, scope: null, name: 'another-why' })}
                summary="Another why"
                variant="popover"
              >
                <Button variant="bare">Inside another why</Button>
              </Disclosure>
            </div>
          </>
        ) : null}
      </section>

      <GalleryCollapsible />

      <section aria-label="Project menu">
        <MoreMenu
          projectKey={project}
          focus={null}
          briefingText={() => `Briefing for ${project}`}
          addHumanContext={{ memoKey: memoKey(project, null, 'outcome') }}
        />
      </section>

      <section aria-label="Human context">
        <HumanContextField
          memoKey={memoKey(project, null, 'outcome')}
          kind="outcome"
          label="OUTCOME"
          placeholder="What result should this scope achieve?"
        />
        <HumanContextField
          memoKey={memoKey(project, null, 'focus')}
          kind="focus"
          label="FOCUS"
          placeholder="What are you concentrating on now?"
        />
      </section>

      <section aria-label="Draft">
        <Button variant="bare" type="button" onClick={() => setDraftShown(!draftShown)}>
          {draftShown ? 'Hide draft' : 'Show draft'}
        </Button>
        {draftShown ? (
          <>
            <Label htmlFor="gallery-draft">Draft note</Label>
            <DraftTextarea
              id="gallery-draft"
              memoryKey={`gallery:draft:${project}`}
              focusKey="gallery-draft"
              className="ctl-draft"
              rows={4}
              defaultValue={draftText}
              onInput={(event) => setDraftText(event.currentTarget.value)}
            />
          </>
        ) : null}
      </section>

      <div aria-hidden="true" style={{ blockSize: 2400 }} />
      <ParkedControl key={displayedAccepted} />
    </main>
  );
}

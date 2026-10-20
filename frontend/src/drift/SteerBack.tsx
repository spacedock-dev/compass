import { SampleMark } from '../sample/SampleMark';
import { Card } from '../ui/card';
import { Textarea } from '../ui/textarea';
import { Label } from '../ui/label';
import { Button } from '../ui/button';
import { useCallback, useEffect, useState, type ReactNode } from 'react';
import { useFocusKey } from '../controls';
import { openPendingDirection } from '../intent/api';
import { DirectionActionButton } from '../intent/DirectionActionButton';
import { useDrift } from './context';
import { correctionLength, type HeldCorrection } from './correction';
import { attachEditor } from './editor';
import { CORRECTION_CAP, CORRECTION_HINT, CORRECTION_OLDER } from './sentences';
import {
  copyCorrection,
  correctionDraft,
  recomposeCorrection,
  rememberShown,
  steerBack,
} from './steerActions';

/* Steer back: the button that opens the correction, and the box that holds it. The box is Copy only: the
   words are the reader's to edit and to paste where they choose, and nothing here is ever sent to the
   session ([DEC-16](../../../docs/design-reading-a-session.md#dec-16-compass-does-not-write-into-a-session)). */

export function SteerButton({
  primary,
  from = '',
}: {
  readonly primary: boolean;
  /** Which check the correction comes from, "from the check at 09:16", where it comes from one. */
  readonly from?: string;
}) {
  const { ctx, model } = useDrift();
  const ref = useFocusKey<HTMLButtonElement>(
    ctx.shell.controls.focusLane,
    `steer-back:${model.key}`,
  );
  const held = ctx.drift.corrections.get(model.key);
  const { identity } = model;
  return (
    <>
      <Button
        ref={ref}
        type="button"
        variant={primary ? 'primary' : 'default'}
        data-next-cockpit-action="steer-back"
        aria-expanded={Boolean(held?.open)}
        data-next-focus={`steer-back:${model.key}`}
        onClick={(event) => {
          event.preventDefault();
          if (identity) void steerBack(ctx, identity);
        }}
      >
        Steer back
      </Button>
      {from ? (
        <span className="next-cockpit-reading-why" data-next-steer-from>
          {from}
        </span>
      ) : null}
      <SampleMark id="steer" />
    </>
  );
}

/* "Update intent instead": the offered direction opens as the pending line through Add's own path, so the
   reader reviews and saves it as one outcome line, and the goal is never touched. */
export function UpdateIntentButton({ factId }: { readonly factId: string }) {
  const { ctx, model } = useDrift();
  const { identity } = model;
  return (
    <DirectionActionButton
      feedbackKey={`update-intent:${model.key}`}
      weight="secondary"
      label="Update intent instead"
      busyLabel="Opening…"
      pendingKey={`update-intent:${model.key}`}
      action="update-intent"
      arg={factId}
      focusKey={`update-intent:${model.key}`}
      onPress={() => {
        if (identity) void openPendingDirection(ctx.shell, identity, factId || null);
      }}
    />
  );
}

/* Tall enough to show the composed text without scrolling, up to a bound: with each departure's explanation
   on its own line (owner, 2026-10-20) a two-departure correction ran past the six rows the box had, and its
   closing request sat below the fold. Counted from the text the box opened with, so typing never resizes it. */
const CORRECTION_ROWS_MIN = 6;
const CORRECTION_ROWS_MAX = 16;
function correctionRows(text: string): number {
  return Math.min(CORRECTION_ROWS_MAX, Math.max(CORRECTION_ROWS_MIN, text.split('\n').length + 1));
}

function CorrectionBox({ held }: { readonly held: HeldCorrection }) {
  const { ctx, model } = useDrift();
  const { key, identity } = model;
  const draft = correctionDraft(held);
  /* What the box last drew, for a recomposition to freeze before the record can renumber its parts. */
  useEffect(() => rememberShown(held, draft));
  /* The node is mounted once per composition and keeps its caret, selection and undo across every redraw. It
     is replaced only where the page changed the words for a reason other than typing: a new composition, or
     a record that renumbered an unedited text, where there is no reader text to lose. */
  const own = held.edited || typeof held.text === 'string';
  const [mounted, setMounted] = useState({ id: held.id, text: draft });
  let current = mounted;
  if (current.id !== held.id || (!own && current.text !== draft)) {
    current = { id: held.id, text: draft };
    setMounted(current);
  }
  const initial = current.text;
  const [count, setCount] = useState(() => correctionLength(initial));
  const attach = useCallback(
    (node: HTMLTextAreaElement | null) => {
      if (!node) return undefined;
      return attachEditor(ctx, key, node, { onCount: setCount });
    },
    [ctx, key],
  );
  const focusRef = useFocusKey<HTMLTextAreaElement>(
    ctx.shell.controls.focusLane,
    `correction:${key}`,
  );
  const ref = useCallback(
    (node: HTMLTextAreaElement | null) => {
      const detach = attach(node);
      const unfocus = focusRef(node);
      return () => {
        detach?.();
        if (typeof unfocus === 'function') unfocus();
      };
    },
    [attach, focusRef],
  );
  const label =
    held.cue === 'copied' ? 'Copied' : held.cue === 'failed' ? 'Copy unavailable' : 'Copy';
  const stale = Boolean(held.stale);
  return (
    <Card variant="steer-box" className="next-cockpit-steer-box" data-next-steer-box>
      <Label className="next-cockpit-held-label" htmlFor="next-cockpit-correction">
        Correction to copy
      </Label>
      {/* No `maxlength`: it counts UTF-16 units, and the cap is in characters. The editor holds the cap and
          the count says where it stands. */}
      <Textarea
        appearance="correction"
        key={`${String(held.id)}\n${initial}`}
        ref={ref}
        id="next-cockpit-correction"
        rows={correctionRows(initial)}
        defaultValue={initial}
        data-next-cockpit-correction-key={key}
        data-next-focus={`correction:${key}`}
        aria-describedby="next-cockpit-correction-hint"
      />
      <div className="next-cockpit-steer-tools">
        <Button
          type="button"
          data-next-cockpit-action="correction-copy"
          data-next-copy-correction={key}
          data-next-focus={`correction-copy:${key}`}
          data-next-correction-cue
          onClick={(event) => {
            event.preventDefault();
            if (identity) void copyCorrection(ctx, identity);
          }}
        >
          {label}
        </Button>
        <span className="next-cockpit-held-count" data-next-correction-count>
          {`${String(count)}/${String(CORRECTION_CAP)}`}
        </span>
        {stale ? (
          <>
            <p className="next-cockpit-reading-why" data-next-correction-older>
              {CORRECTION_OLDER}
            </p>
            <Button
              type="button"
              data-next-cockpit-action="correction-recompose"
              data-next-focus={`correction-recompose:${key}`}
              onClick={(event) => {
                event.preventDefault();
                if (identity) void recomposeCorrection(ctx, identity);
              }}
            >
              Recompose
            </Button>
          </>
        ) : null}
        <p
          className="next-cockpit-reading-why"
          data-next-correction-edit-why
          {...(held.editWhy ? {} : { hidden: true })}
        >
          {held.editWhy || ''}
        </p>
        <p
          className="next-cockpit-reading-why"
          data-next-correction-paint-why
          {...(held.paintWhy ? {} : { hidden: true })}
        >
          {held.paintWhy || ''}
        </p>
        <p className="next-cockpit-reading-why" id="next-cockpit-correction-hint">
          {CORRECTION_HINT}
        </p>
      </div>
    </Card>
  );
}

/* The design's steer box with Copy-only wording: "Correction to copy" and the hint the issue gives in place of
   the Send hint. Copy's label is its cue, the More menu's "Copied" and "Copy unavailable". */
export function SteerBox(): ReactNode {
  const { ctx, model } = useDrift();
  const held = ctx.drift.corrections.get(model.key);
  if (!held || !held.open || held.pending) return null;
  if (held.why) {
    return (
      <p className="next-cockpit-reading-why" role="status" data-next-steer-refused>
        {held.why}
      </p>
    );
  }
  if (!Array.isArray(held.parts)) return null;
  return <CorrectionBox held={held} />;
}

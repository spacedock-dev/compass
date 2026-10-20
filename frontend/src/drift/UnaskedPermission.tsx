import { useState, useSyncExternalStore } from 'react';
import { payloadSessions } from '../api/bootstrap';
import { exactIdentity } from '../api/identity';
import { annotationOf } from '../intent/annotation';
import { answered } from '../intent/context';
import { isRecord, type Row } from '../observed';
import { RouteAnchor } from '../sessions';
import { useDisplayed, useShell } from '../shell/context';
import { Button } from '../ui/button';
import { DisclosureParts } from './ModelNotice';
import { overlaid, showReading } from './overlay';
import { policyReason, unaskedRoute } from './route';
import { driftCtxFor } from './state';

function typedGoal(session: Row): boolean {
  const annotation = annotationOf(session);
  return Boolean(
    annotation &&
      !annotation['discarded_at'] &&
      (annotation['goal_source'] ?? 'typed') === 'typed' &&
      String(annotation['goal'] ?? '').trim(),
  );
}

const REFUSED: Readonly<Record<string, string>> = {
  'destination-changed':
    'Where Codex sends your words changed. Check the destination shown here and try again.',
  'provider-changed': 'Codex no longer runs unasked checks of this session. Nothing was saved.',
  'no-grant-needed': 'Claude Code runs unasked checks of this session, so no permission is needed.',
};

function granted(payload: Row): boolean {
  const policy = payload['reading'];
  return isRecord(policy) && isRecord(policy['words']) && policy['words']['codex'] === true;
}

function unaskedRefusal(payload: Row): string {
  const policy = payload['reading'];
  if (isRecord(policy) && policy['reason'] === 'daily-cap' && policy['off'] !== true) return '';
  return policyReason(policy);
}

export function UnaskedPermission({
  payload,
  session,
}: {
  readonly payload: Row;
  readonly session: Row;
}) {
  const shell = useShell();
  const ctx = driftCtxFor(shell);
  const overlay = useSyncExternalStore(ctx.drift.subscribe, ctx.drift.getOverlay);
  const count = useDisplayed((snapshot) => snapshot.acceptedCount);
  const current = overlaid(payload, overlay, count);
  const route = unaskedRoute(current, session);
  const [message, setMessage] = useState('');
  const pending = useDisplayed((snapshot) => snapshot.pending.includes('unasked-grant:codex'));
  if (current['unasked'] !== true) return null;
  const provider = route?.['provider'];
  const allowed = granted(current);
  /* A stored Codex grant keeps its revoke switch on every session page, whichever provider checks this session
     today: a grant that could be revoked only while Codex held the route would take effect again the day Codex
     returned, with no control left to stop it. */
  if (provider !== 'codex' && !allowed)
    return provider === 'claude' && route ? <ClaudeUnasked route={route} /> : null;
  const codexRoute = provider === 'codex' ? route : null;
  const refusal = unaskedRefusal(current);
  const blocked = Boolean(refusal);
  const parts = codexRoute?.['disclosure_parts'];
  const change = async () => {
    const identity = exactIdentity(session);
    if (!identity || blocked) return;
    const press = shell.runtime.pending.start(
      'unasked-grant:codex',
      'Saving unasked check permission',
    );
    if (!press) return;
    setMessage('');
    try {
      const response = answered(
        await shell.runtime.client.postReading(
          {
            ...identity,
            provider: 'codex',
            model: String(codexRoute?.['model'] ?? ''),
            words_destination: String(codexRoute?.['words_destination'] ?? ''),
            unasked_grant: !allowed,
            press: true,
            observer_model: 1,
          },
          press.signal,
        ),
      );
      if (response.kind === 'answered' && response.body) {
        const body = response.body as Row;
        if (isRecord(body['reading'])) showReading(ctx, body['reading']);
        if (!response.ok || body['ok'] !== true)
          setMessage(
            REFUSED[String(body['reason'] ?? '')] ||
              (isRecord(body['reading']) ? policyReason(body['reading']) : '') ||
              'Permission was not saved. Try again.',
          );
        else
          shell.announcer.announce(
            'unasked-grant',
            allowed
              ? 'Codex permission for unasked checks revoked.'
              : 'Codex permission for unasked checks granted.',
          );
      } else setMessage('Permission could not be confirmed. Refresh before trying again.');
      await shell.runtime.refresh();
    } finally {
      shell.runtime.pending.end('unasked-grant:codex', press);
    }
  };
  const labelId = `unasked-grant-${String(session['harness'] ?? '')}-${String(session['sid'] ?? '')}`;
  return (
    <>
      {provider === 'claude' && route ? <ClaudeUnasked route={route} /> : null}
      <section aria-label="Unasked checks" className="next-session-drift-check">
        <p className="next-cockpit-reading-why">
          {!codexRoute
            ? 'Codex still has your permission to run unasked checks, though it does not check this session. Turn the switch off to revoke it.'
            : allowed
              ? 'Codex has permission to check this session while you are away. Turn the switch off to revoke it.'
              : typedGoal(session)
                ? blocked
                  ? 'Unasked checks of this session are waiting for your permission.'
                  : 'Unasked checks of this session are waiting for your permission. Turn on the switch below to let Codex check it against your goal while you are away.'
                : 'Codex needs your permission for unasked checks. Save a typed goal for this session to give those checks something to read against.'}
        </p>
        <div className="flex items-center gap-2">
          <Button
            variant="native"
            type="button"
            className="next-session-drift-switch"
            role="switch"
            aria-checked={allowed}
            aria-labelledby={labelId}
            disabled={blocked || pending}
            onClick={() => void change()}
          >
            <span className="next-session-drift-track" aria-hidden="true">
              <span />
            </span>
          </Button>
          <span id={labelId}>Allow Codex to run unasked checks</span>
        </div>
        {blocked ? <p className="next-cockpit-reading-why">{refusal}</p> : null}
        <p className="next-cockpit-reading-why">
          This permission covers every session Codex reads at this destination.
        </p>
        {Array.isArray(parts) ? <DisclosureParts parts={parts.map(String)} /> : null}
        {message ? <p role="status">{message}</p> : null}
      </section>
    </>
  );
}

/* Claude Code needs no grant, so nothing here asks; but a reader who turned on unasked checks when only a Codex
   Allow could start one would otherwise begin sending words to a second provider with no sign of it. */
function ClaudeUnasked({ route }: { readonly route: Row }) {
  const parts = route['disclosure_parts'];
  return (
    <section aria-label="Unasked checks by Claude Code" className="next-session-drift-check">
      <p className="next-cockpit-reading-why">
        Claude Code checks this session against your typed goal while you are away. It needs no
        separate permission. Pause model calls stops it. Each check sends:
      </p>
      {Array.isArray(parts) ? <DisclosureParts parts={parts.map(String)} /> : null}
    </section>
  );
}

export function UnaskedAttentionCue({ payload }: { readonly payload: Row }) {
  const shell = useShell();
  const ctx = driftCtxFor(shell);
  const overlay = useSyncExternalStore(ctx.drift.subscribe, ctx.drift.getOverlay);
  const count = useDisplayed((snapshot) => snapshot.acceptedCount);
  const current = overlaid(payload, overlay, count);
  if (current['unasked'] !== true || granted(current)) return null;
  const refusal = unaskedRefusal(current);
  const waiting = payloadSessions(current as never).rows.filter(
    (session) =>
      typedGoal(session as unknown as Row) &&
      unaskedRoute(current, session as unknown as Row)?.['provider'] === 'codex',
  );
  if (!waiting.length) return null;
  // Derived from the rows listed: a session checked before a revoke has been checked.
  const never = waiting.every(
    (session) => (session as unknown as Row)['departure_checked'] !== true,
  );
  return (
    <section
      aria-label="Unasked checks waiting for permission"
      className="next-attention-section"
      data-next-attention-section="unasked"
    >
      <div className="next-attention-section-heading">
        <h2>Unasked checks waiting for permission</h2>
      </div>
      <p>
        Compass is set to check these sessions against the goal you typed while you are away, and
        Codex runs those checks. Codex needs your permission first, so{' '}
        {never ? 'none of them has been checked yet.' : 'they are not being checked now.'} Open a
        session below and use “Allow Codex to run unasked checks” in its Drift card.
      </p>
      {refusal ? <p>{refusal}</p> : null}
      <ul>
        {waiting.map((session) => (
          <li key={`${session.harness}:${session.sid}`}>
            <RouteAnchor
              route={{
                view: 'session',
                project: String(session.project ?? ''),
                harness: String(session.harness),
                session: String(session.sid),
                from: 'attention',
              }}
            >
              {String(session.title || session.sid)}
            </RouteAnchor>
          </li>
        ))}
      </ul>
    </section>
  );
}

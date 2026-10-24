import { nextNumber } from '../api/bootstrap';
import { compatSessKey } from '../api/identity';
import type { GoalFindRequest, SessionIdentity } from '../api/types';
import { policyReason, readingRoute, routeRefusal } from '../drift/route';
import { DESTINATION_CHANGED, PAGE_OUTDATED, PROVIDER_CHANGED } from '../drift/sentences';
import { isRecord, type Row } from '../observed';
import {
  announce,
  answered,
  liveRow,
  pendingEnd,
  pendingHas,
  pendingStart,
  readInput,
  refresh,
  type Ctx,
} from './context';
import { findGoalOffered, goalBaseline, goalKey, intentKey } from './derive';
import type { FoundCite, FoundGoal } from './held';
import {
  FIND_GOAL_FAILED,
  FIND_GOAL_LEFT,
  FIND_GOAL_LOST,
  FIND_GOAL_NO_PROMPTS,
  FIND_GOAL_NOTHING,
  FIND_GOAL_OUTRANKED,
  FIND_GOAL_REFUSED,
  FIND_GOAL_RUNNING,
  FIND_GOAL_UNAVAILABLE,
  INTENT_FOUND_SAID,
} from './sentences';

/* "Find goal": the reader's prompts read for a goal, on one press of one control. A mount, a second mount under
   StrictMode, a poll, a reconnect, a hover or a keypress reaches none of it, and a lost answer is never retried,
   because it does not establish that the model never ran. The server refuses while model calls are paused and
   charges the press against the day's analysis limit at the model, so the page checks nothing it cannot read
   from the board and takes the server's word for the rest. The press stores nothing: what comes back is words
   in the goal box, kept, edited or discarded like any others. */

export const findKey = (session: Row): string => `${goalKey(session)}:find`;

const textOf = (value: unknown): string => (typeof value === 'string' ? value : '');

function cite(raw: unknown): FoundCite | null {
  if (!isRecord(raw)) return null;
  const factId = textOf(raw['fact_id']);
  const quotes = Array.isArray(raw['quotes']) ? raw['quotes'].map(textOf).filter(Boolean) : [];
  return factId && quotes.length
    ? { factId, ordinal: nextNumber(raw['ordinal']), at: nextNumber(raw['at']), quotes }
    : null;
}

/* The found goal as the server answered it, or null where it is not whole: words, the time, and at least one
   prompt it quotes. A goal the page cannot tie to a prompt is not shown, as the server would not have sent it. */
export function parseFound(raw: unknown, label: string): FoundGoal | null {
  if (!isRecord(raw)) return null;
  const text = textOf(raw['goal']).trim();
  const foundAt = nextNumber(raw['found_at']);
  /* One entry per prompt: a response that names the same prompt once per quoted sentence is one citation
     with each sentence under it, in the order they came. */
  const cites: FoundCite[] = [];
  for (const entry of Array.isArray(raw['cites']) ? raw['cites'].map(cite) : []) {
    if (!entry) continue;
    const at = cites.findIndex((held) => held.factId === entry.factId);
    const held = cites[at];
    if (held) {
      cites[at] = {
        ...held,
        quotes: [...held.quotes, ...entry.quotes.filter((q) => !held.quotes.includes(q))],
      };
    } else cites.push(entry);
  }
  return text && foundAt !== null && foundAt > 0 && cites.length
    ? { text, foundAt, label, cites }
    : null;
}

/* What an answered refusal says: the policy's own sentence where it carries one, so a pause and a spent day
   read as they do on the Analyze card, and otherwise the reason. */
function refusal(status: number, body: Record<string, unknown> | null, label: string): string {
  const policy = body && isRecord(body['reading']) ? policyReason(body['reading']) : '';
  if (policy) return policy;
  const reason = textOf(body?.['reason']);
  if (status === 409 && reason === 'provider-changed') return PROVIDER_CHANGED;
  if (status === 409 && reason === 'destination-changed') return DESTINATION_CHANGED;
  if (status === 409 && reason === 'in-flight') return FIND_GOAL_RUNNING;
  if (status === 400 && reason === 'page-outdated') return PAGE_OUTDATED;
  if (status === 502) return FIND_GOAL_FAILED(label);
  if (status === 503 && textOf(body?.['why']) === 'model-unavailable')
    return FIND_GOAL_UNAVAILABLE(label);
  return FIND_GOAL_REFUSED;
}

export async function findGoal(ctx: Ctx, identity: SessionIdentity): Promise<void> {
  const row = liveRow(ctx, identity);
  const input = row ? readInput(ctx, identity, row) : null;
  if (!row || !input || !findGoalOffered(input)) return;
  const key = compatSessKey(row);
  const control = findKey(row);
  if (pendingHas(ctx, control)) return;
  const said = (message: string): void => {
    ctx.held.finds.set(key, { message });
    announce(ctx, control, message);
    ctx.held.notify();
  };
  ctx.held.finds.delete(key);
  /* Answered on the page where the board already says so, with nothing sent: a control that goes silent reads
     as a dead one. The server still decides, so a board that is behind is refused there too. */
  const policy = isRecord(input.payload['reading']) ? policyReason(input.payload['reading']) : '';
  const route = readingRoute(input.payload, row);
  const unread = routeRefusal(input.payload, row);
  if (policy || unread || !route) {
    said(policy || unread);
    return;
  }
  const provider = textOf(route['provider']);
  const label = textOf(route['label']) || 'the model';
  const press = pendingStart(ctx, control, 'Finding…', 'Looking for a goal in your prompts.');
  if (!press) return;
  ctx.held.notify();
  let applied = false;
  try {
    const body: GoalFindRequest = {
      ...identity,
      provider,
      ...(provider === 'claude' ? { model: textOf(route['model']) } : {}),
      press: true,
      observer_model: 1,
    };
    const reply = answered(await ctx.shell.runtime.client.postGoalFind(body, press.signal));
    if (reply.kind === 'lost') {
      said(FIND_GOAL_LOST);
      return;
    }
    const answer = reply.body as Record<string, unknown> | null;
    if (!reply.ok || !answer || answer['ok'] !== true || typeof answer['produced'] !== 'boolean') {
      said(reply.ok ? FIND_GOAL_LOST : refusal(reply.status, answer, label));
      await refresh(ctx);
      return;
    }
    const named = isRecord(answer['route']) ? textOf(answer['route']['label']) : '';
    const found = parseFound(answer['found'], named || label);
    if (!found) {
      said(answer['why'] === 'no-prompts' ? FIND_GOAL_NO_PROMPTS : FIND_GOAL_NOTHING);
      await refresh(ctx);
      return;
    }
    applied = apply(ctx, identity, found, said);
    await refresh(ctx);
  } finally {
    pendingEnd(ctx, control, press);
    ctx.held.requestFocus(applied ? goalKey(row) : control);
  }
}

/* The found goal into the box, read against the board as it stands now: a goal saved or a /goal set while the
   search ran outranks it, and words the reader began typing are theirs and stay. */
function apply(
  ctx: Ctx,
  identity: SessionIdentity,
  found: FoundGoal,
  said: (message: string) => void,
): boolean {
  const input = readInput(ctx, identity);
  if (!input) return false;
  const gk = goalKey(input.session);
  if (!findGoalOffered(input)) {
    said(FIND_GOAL_OUTRANKED);
    return false;
  }
  const typed = ctx.held.goals.get(gk);
  if (typed !== undefined && typed !== goalBaseline(input)) {
    said(FIND_GOAL_LEFT);
    return false;
  }
  ctx.held.found.set(compatSessKey(input.session), found);
  ctx.held.cleared.delete(gk);
  ctx.held.chosen.delete(gk);
  ctx.held.goals.set(gk, found.text);
  ctx.held.drop(gk);
  ctx.held.drop(intentKey(input.session));
  ctx.held.finds.delete(compatSessKey(input.session));
  announce(ctx, `${gk}:found`, INTENT_FOUND_SAID);
  ctx.held.notify();
  return true;
}

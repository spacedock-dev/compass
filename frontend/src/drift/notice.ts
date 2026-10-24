import type { Row } from '../observed';
import { isRecord } from '../observed';
import { useDrift } from './context';
import { readingsOff } from './route';
import {
  NOTICE_WORDS,
  NOTICE_WORDS_AND_MESSAGES,
  noticeDestination,
  noticeToolOutput,
} from './sentences';

/* The notice names the provider it was recorded for, not the route drawn now: a notice is held for the life of
   the tab, and a fallback or a provider change afterwards must not relabel where these words went. The labels
   are the server's own (`reading_route.LABELS`). */
const PROVIDER_LABELS: Readonly<Record<string, string>> = { codex: 'Codex', claude: 'Claude Code' };

export function noticeLabel(notice: Row): string {
  const provider = String(notice['provider'] || '');
  return PROVIDER_LABELS[provider] ?? provider;
}

/* The neutral account of what was sent, from the record's content tier alone, for when the route's own parts
   describe another provider. Tier 4 carries the agent's messages; tier 1 does not.
   [Consent notice payload](../../../docs/design-session-summary.md#consent-notice-payload) */
export function noticeContentParts(notice: Row): readonly string[] {
  return [Number(notice['content']) >= 4 ? NOTICE_WORDS_AND_MESSAGES : NOTICE_WORDS];
}

/* One polite announcement per notice, keyed by its kind, provider and time: the card is not focused, so a
   screen reader would otherwise never hear what was sent and where. */
export function noticeAnnouncement(notice: Row): {
  readonly key: string;
  readonly sentence: string;
} {
  const destination = String(notice['destination'] || '');
  const output = String(notice['tool_output'] || '');
  return {
    key: `notice:${String(notice['kind'] || '')}:${String(notice['provider'] || '')}:${String(notice['at'] ?? '')}`,
    sentence: [
      `Notice: this request sends to ${noticeLabel(notice) || 'a model'}.`,
      `${noticeDestination(destination)}.`,
      output ? `${noticeToolOutput(output)}.` : '',
    ]
      .filter(Boolean)
      .join(' '),
  };
}

export function sessionNotice(
  request: { readonly notice?: Readonly<Record<string, unknown>> | null } | undefined,
  job: Row | null,
): Row | null {
  const notice = isRecord(job?.['notice']) ? job['notice'] : request?.notice;
  return isRecord(notice) ? notice : null;
}

/* Whether a notice is drawn for this session, so a control beside it can leave the off switch to it. */
export function useNoticeShown(): boolean {
  const { ctx, model } = useDrift();
  const notice = sessionNotice(ctx.intent.held.requests.get(model.key), model.job);
  return Boolean(notice) && !readingsOff(model.payload);
}

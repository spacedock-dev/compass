import { sessionKey, type BoardRisk, type Row } from '../observed';
import type { RouteInput } from '../router/grammar';
import type { AttentionModel, Subject } from './model';
import {
  checkpointRows,
  identityText,
  kindLabel,
  subjectNow,
  subjectRoute,
  subjectSource,
} from './text';

/* How a board risk finds the Attention subject that owns it, so the row can carry that subject's other
   signals and its published task instead of repeating them in a second place. The legacy page's
   `nextAttentionRiskSubject`; the three scopes it answers for are the three the observed model publishes. */
export function riskSubject(risk: BoardRisk, model: AttentionModel): Subject | undefined {
  if (risk.scope === 'session') {
    const key = sessionKey({ harness: risk.harness, sid: risk.sid });
    return [...model.needs, ...model.risk, ...model.close, ...model.next].find(
      (row) => row.key === key,
    );
  }
  if (risk.kind === 'collision' || risk.kind === 'checkout') {
    return model.risk.find(
      (row) =>
        row.kind === 'collision' &&
        row.primaryKind === risk.kind &&
        risk.identity ===
          `${String((row.identity as unknown as Row | undefined)?.['project'] || 'Across display labels ·')} ${risk.kind === 'checkout' ? 'checkout' : 'display label'}`,
    );
  }
  if (risk.kind === 'ask') {
    return model.needs.find(
      (row) => !row.session && row.asks.some((ask) => ask['id'] === risk.identity),
    );
  }
  return undefined;
}

export interface RiskRow {
  readonly key: string;
  readonly route: RouteInput;
  readonly signals: ReturnType<typeof subjectNow>;
  readonly checkpoints: string[];
  readonly subject: Subject | undefined;
}

/* One risk row's pieces. `retained` is a subject the observed model has no row for (a per-model quota
   window): the row is then drawn from the subject itself, past its first signal. A board-scope row keeps
   its subject's signals but not the collision one, which the row's own sentence already says. */
export function riskRow(
  risk: BoardRisk,
  model: AttentionModel,
  board: boolean,
  retained?: Subject,
): RiskRow {
  const subject = retained ?? riskSubject(risk, model);
  const key = subject
    ? subject.key
    : board
      ? `board:${JSON.stringify([risk.kind, risk.identity])}`
      : sessionKey({ harness: risk.harness, sid: risk.sid });
  const route: RouteInput = board
    ? subject
      ? subjectRoute(subject)
      : { view: 'sessions' }
    : {
        view: 'session',
        project: risk.project ?? null,
        harness: risk.harness ?? null,
        session: risk.sid ?? null,
      };
  const detailsSubject: Subject | undefined = retained
    ? { ...retained, signals: retained.signals.slice(1) }
    : subject && board
      ? {
          ...subject,
          signals: subject.signals.filter(
            (signal) => !['collision', 'checkout'].includes(signal.kind),
          ),
        }
      : subject;
  return {
    key,
    route,
    signals: detailsSubject ? subjectNow(detailsSubject, model) : [],
    checkpoints: subject ? checkpointRows(subject, model) : [],
    subject,
  };
}

/* The board-risk shape a retained per-model quota subject is drawn through. Per-model pressure is still a
   subject of its own; the observed model only puts window pressure in its board risks. */
export function modelQuotaRisk(
  subject: Subject,
  model: AttentionModel,
): BoardRisk & { readonly nowKnown: true } {
  const checkpoints = checkpointRows(subject, model);
  const [first] = subjectNow(subject, model);
  return {
    scope: 'board',
    kind: 'quota',
    title: kindLabel('quota'),
    identity: identityText(subject, model),
    src: subjectSource(subject, model),
    nowText: first?.text ?? '',
    nowKnown: true,
    nextText: checkpoints.join(' · '),
    nextKnown: checkpoints.length > 0,
    tone: 'unknown',
  };
}

/* Full-board transport only. Reader-authored words and each delivery's varying values stay literal. */
export const EXPLANATION_SLOTS = [
  'annotation_goal_why',
  'annotation_lines_why',
  'annotation_discarded_why',
  'annotation_binding_why',
  'delivery_why',
  'delivery_none_why',
  'delivery_mixed_why',
  'delivery_binding_why',
  'browser_lane_why',
  'departure_why',
] as const;
const deliverySlots = EXPLANATION_SLOTS.filter(
  (name) => !name.startsWith('annotation_') && name !== 'departure_why',
);
const record = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);

export function expandExplanations<T>(payload: T): T {
  if (!record(payload) || !record(payload['explanations']) || !Array.isArray(payload['sessions']))
    return payload;
  const vocabulary = payload['explanations'];
  const change = (value: unknown): unknown => {
    if (typeof value !== 'string' || !value.startsWith('why:')) return value;
    const sentence = vocabulary[value];
    return typeof sentence === 'string' ? sentence : '';
  };
  const slots = (row: Record<string, unknown>, names: readonly string[]) =>
    Object.fromEntries(
      Object.entries(row).map(([key, value]) => [key, names.includes(key) ? change(value) : value]),
    );
  return {
    ...payload,
    ...(record(payload['annotate_discard'])
      ? { annotate_discard: slots(payload['annotate_discard'], ['record']) }
      : {}),
    sessions: payload['sessions'].map((row: unknown) => {
      if (!record(row)) return row;
      const next = slots(row, EXPLANATION_SLOTS);
      if (record(row['reading_eligibility']))
        next['reading_eligibility'] = slots(row['reading_eligibility'], ['sentence']);
      if (record(row['delivery_departure']))
        next['delivery_departure'] = slots(row['delivery_departure'], deliverySlots);
      return next;
    }),
  };
}

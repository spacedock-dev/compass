import type { StorageAccess } from './backend';
import { STORAGE_KEYS } from './keys';

export const GUARDRAIL_LIMIT = 50;
export const GUARDRAIL_TEXT_LIMIT = 2000;

export interface GuardrailRule {
  readonly enabled: boolean;
  readonly text: string;
}

export interface GuardrailChange {
  readonly rules: readonly GuardrailRule[];
  /** False only when a write was attempted and refused; a no-op change attempts none. */
  readonly persisted: boolean;
  readonly refused?: 'limit' | 'stale';
}

export function guardrailKey(project: string): string {
  return `${STORAGE_KEYS.guardrailPrefix}${encodeURIComponent(project)}`;
}

/** Earlier builds stored bare strings; those read as enabled. Only an explicit `false` disables. */
export function normalizeGuardrail(value: unknown): GuardrailRule | null {
  const source = typeof value === 'string' ? { text: value, enabled: true } : value;
  if (!source || typeof (source as { text?: unknown }).text !== 'string') return null;
  const { text: raw, enabled } = source as { text: string; enabled?: unknown };
  const text = [...raw.trim()].slice(0, GUARDRAIL_TEXT_LIMIT).join('');
  if (!text) return null;
  return { enabled: enabled !== false, text };
}

/** The cap applies after invalid rules are dropped, so it keeps the first fifty usable ones. */
export function decodeGuardrails(raw: string | null): GuardrailRule[] {
  try {
    const parsed: unknown = raw == null ? [] : JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    const rules: GuardrailRule[] = [];
    for (const item of parsed) {
      const rule = normalizeGuardrail(item);
      if (rule) rules.push(rule);
    }
    return rules.slice(0, GUARDRAIL_LIMIT);
  } catch {
    return [];
  }
}

export interface GuardrailStore {
  rules(project: string): readonly GuardrailRule[];
  add(project: string, text: string): GuardrailChange;
  toggle(project: string, target: GuardrailRule): GuardrailChange;
  remove(project: string, target: GuardrailRule): GuardrailChange;
}

export function createGuardrailStore(access: StorageAccess): GuardrailStore {
  // Refresh before mutations. An unchanged stored value keeps even a failed write's in-tab words.
  const projects = new Map<
    string,
    { readonly rules: readonly GuardrailRule[]; readonly raw: string | null | undefined }
  >();
  const current = (project: string, refresh = false): readonly GuardrailRule[] => {
    const known = projects.get(project);
    if (known && !refresh) return known.rules;
    const read = access.attempt((backend) => backend.getItem(guardrailKey(project)));
    if (!read.ok) return known?.rules ?? [];
    if (known && known.raw === read.value) return known.rules;
    const loaded = decodeGuardrails(read.value);
    projects.set(project, { rules: loaded, raw: read.value });
    return loaded;
  };
  const commit = (project: string, rules: readonly GuardrailRule[]): GuardrailChange => {
    const raw = JSON.stringify(rules);
    const persisted = access.attempt((backend) => {
      backend.setItem(guardrailKey(project), raw);
    }).ok;
    projects.set(project, { rules, raw: persisted ? raw : projects.get(project)?.raw });
    return { rules: [...rules], persisted };
  };
  const locate = (project: string, target: GuardrailRule) => {
    const rendered = current(project);
    const rules = current(project, true);
    let index = rules.indexOf(target);
    const matches = (rule: GuardrailRule) =>
      rule.text === target.text && rule.enabled === target.enabled;
    // Unchanged snapshots distinguish identical duplicates by reference. After a refresh,
    // duplicates are ambiguous: ask the reader again rather than choose a different copy.
    if (index < 0 && rendered.filter(matches).length === 1) {
      const candidates = rules.filter(matches);
      const [candidate] = candidates;
      if (candidates.length === 1 && candidate) index = rules.indexOf(candidate);
    }
    return { rules, index };
  };
  return {
    rules: (project) => [...current(project)],
    add(project, text) {
      const rule = normalizeGuardrail({ enabled: true, text });
      const rules = current(project, true);
      if (!rule) return { rules: [...rules], persisted: true };
      if (rules.length >= GUARDRAIL_LIMIT)
        return { rules: [...rules], persisted: true, refused: 'limit' };
      return commit(project, [...rules, rule]);
    },
    toggle(project, target) {
      const { rules, index } = locate(project, target);
      if (index < 0) return { rules: [...rules], persisted: true, refused: 'stale' };
      return commit(
        project,
        rules.map((rule, at) =>
          at === index ? { enabled: !rule.enabled, text: rule.text } : rule,
        ),
      );
    },
    remove(project, target) {
      const { rules, index } = locate(project, target);
      if (index < 0) return { rules: [...rules], persisted: true, refused: 'stale' };
      return commit(
        project,
        rules.filter((_, at) => at !== index),
      );
    },
  };
}

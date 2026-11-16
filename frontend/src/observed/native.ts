import { isRecord, type Row } from './values';

/* A linked child's display hold cannot change what this session's work means. Project before
   narrowing a row to state alone, since that projection would lose the native snapshot. */
export function nativeSession<T extends object>(source: T): T {
  const snapshot = (source as Row)['declared_native_state'];
  if (!isRecord(snapshot)) return source;
  return {
    ...source,
    state: snapshot['state'],
    active: snapshot['active'],
    state_detail: snapshot['state_detail'],
  };
}

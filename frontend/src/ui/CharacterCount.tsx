export function CharacterCount({
  id,
  length,
  limit,
}: {
  readonly id: string;
  readonly length: number;
  readonly limit: number;
}) {
  const over = length > limit;
  return (
    <span id={id} className="block">
      {length >= limit * 0.8 ? (
        <span
          data-character-count
          data-over={over || undefined}
          className={`block text-label ${over ? 'text-destructive' : 'text-muted-foreground'}`}
        >
          {length}/{limit}
        </span>
      ) : null}
      <span role="status" className="block text-body text-destructive">
        {over ? `${String(length)} characters; the limit is ${String(limit)}.` : ''}
      </span>
    </span>
  );
}

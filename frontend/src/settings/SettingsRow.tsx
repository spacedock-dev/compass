import type { ReactNode } from 'react';

export function SettingsRow({
  title,
  description,
  children,
}: {
  readonly title: string;
  readonly description?: ReactNode;
  readonly children?: ReactNode;
}) {
  return (
    <div className="flex min-w-0 items-start justify-between gap-3 px-4 py-3 sm:px-6">
      <div className="min-w-0 self-center">
        <p className="m-0 text-body font-semibold">{title}</p>
        {description ? (
          <div className="mt-0.5 text-body text-muted-foreground [overflow-wrap:anywhere]">
            {description}
          </div>
        ) : null}
      </div>
      {children ? <div className="max-w-[54%] shrink-0">{children}</div> : null}
    </div>
  );
}

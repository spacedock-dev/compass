import { useId } from 'react';
import { Icon } from './icons';
import { STATUS_LEGEND } from './statusLegendEntries';

export function StatusLegend() {
  const heading = useId();
  return (
    <section className="mt-3 text-label text-muted-foreground">
      <h2 id={heading} className="font-semibold">
        What the icons mean
      </h2>
      <ul aria-labelledby={heading} className="flex flex-wrap gap-x-4 gap-y-1">
        {STATUS_LEGEND.map(([word, icon]) => (
          <li
            key={word}
            className={`inline-flex items-center gap-2${icon === 'worth-a-look' ? ' text-[var(--worth-a-look)]' : ''}`}
          >
            <Icon
              name={icon}
              className={icon === 'worth-a-look' ? 'text-[var(--worth-a-look)]' : ''}
            />
            {word}
          </li>
        ))}
      </ul>
    </section>
  );
}

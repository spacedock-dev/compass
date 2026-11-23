import { Card } from '../ui/card';
import { RailHeader } from '../steering/RailHeader';
import type { DelegationFigure } from './metric';
import './delegation.css';

/* How much of this project's observed time ran without the reader. Withheld, never zeroed: until one complete
   window has been observed the panel says "no figure yet" and why, because a percentage over no time is the
   schema speaking, not the project. */
export function DelegationPanel({ figure }: { readonly figure: DelegationFigure }) {
  const note = <p className="next-rail-reason">{figure.noteText}</p>;
  let body;
  if (!figure.pctKnown) {
    body = (
      <div className="next-delegation-withheld" data-next-delegation-withheld>
        <strong data-next-absent>{figure.pctText}</strong>
        {note}
      </div>
    );
  } else {
    const delta = figure.trendDelta;
    body = (
      <>
        <div className="next-delegation-figure">
          <strong data-next-delegation-percent>{figure.pctText}</strong>
          {figure.trendKnown && delta !== null ? (
            <span
              className={`next-delegation-trend next-delegation-trend--${delta > 0 ? 'up' : delta < 0 ? 'down' : 'flat'}`}
              data-next-delegation-trend
            >
              {figure.trendText}
            </span>
          ) : null}
          <span className="next-delegation-caption">
            of observed time
            <br />
            ran without you
          </span>
        </div>
        <progress max={100} value={figure.pct ?? 0} aria-label={`${figure.pctText} delegated`} />
        <div className="next-delegation-metrics">
          {figure.tpsKnown ? (
            <span data-next-delegation-rate>{figure.tpsText}</span>
          ) : (
            <span className="next-rail-reason" data-next-delegation-rate-withheld>
              {figure.tpsText}
            </span>
          )}
          <span data-next-delegation-turns>{figure.humanText}</span>
        </div>
        {note}
      </>
    );
  }
  return (
    <Card
      as="section"
      variant="rail-panel"
      className="next-delegation next-rail-panel"
      data-next-delegation
      data-next-rail-panel="delegation"
    >
      <RailHeader label="Time agents worked on their own" note={figure.windowText} />
      {body}
    </Card>
  );
}

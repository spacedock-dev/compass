import { allowanceText, capacityPreview } from '../api/promptCapacity';
import type { Row } from '../observed';

/** The current route preview describes the next press, never a stored assessment. */
export function ReadingAllowance({ route }: { readonly route: Row | null }) {
  const preview = capacityPreview(route?.['capacity']);
  return (
    <div data-next-reading-allowance className="next-cockpit-reading-why">
      <p className="m-0">
        <strong>Next Analyze prompt: </strong>
        {allowanceText(preview)}
      </p>
      {preview?.reason === 'estimated' ? (
        <>
          <p className="m-0">
            These estimates do not confirm model availability or that a prompt will fit. An
            assembled prompt above this allowance is refused before a model call; it is not
            automatically shortened.
          </p>
          {preview.window_source === 'unknown' ? (
            <p className="m-0">Conservative estimate; this route’s context window is unknown.</p>
          ) : null}
        </>
      ) : null}
    </div>
  );
}

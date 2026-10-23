import { useContext, useState } from 'react';
import { compatSessKey } from '../api/identity';
import { DriftContext } from '../drift/context';
import { openEntry } from '../drift/jumpToEntry';
import { CitationLink } from '../drift/CitationLink';
import { readingRoute } from '../drift/route';
import { clock as clockText } from '../observed';
import { missingSentence } from '../sessions/outline';
import { ActionButton } from './ActionButton';
import { foundGoal, findGoalOffered } from './derive';
import { findGoal, findKey } from './find';
import { identityOf } from './context';
import { FIND_GOAL_TITLE } from './sentences';
import { usePanel } from './useIntent';

/* "Find goal", beside the prompt list: it reads the reader's prompts for a goal, on this press and no other.
   Drawn only while no goal is saved, no /goal was detected and no found goal stands in the box, so what it offers
   is what the reader does not yet have. Its title says who reads the prompts, from the same route Analyze names. */
export function FindGoal() {
  const { ctx, input, session, payload } = usePanel();
  if (!findGoalOffered(input)) return null;
  const route = readingRoute(payload, session);
  const label = String(route?.['label'] || '') || 'the model';
  const identity = identityOf(session);
  const key = findKey(session);
  return (
    <ActionButton
      label="Find goal"
      busyLabel="Finding…"
      pendingKey={key}
      focusKey={key}
      action="goal-find"
      title={FIND_GOAL_TITLE(label)}
      onPress={() => {
        if (identity) void findGoal(ctx, identity);
      }}
    />
  );
}

/* What the last press said, under the heading row where the button is: nothing found, a pause, a spent day, a
   goal left alone. Gone with the next edit of the box or the next press. */
export function FindGoalNote() {
  const { ctx, session } = usePanel();
  const message = ctx.held.finds.get(compatSessKey(session))?.message ?? '';
  if (!message) return null;
  return (
    <p className="next-cockpit-held-absent" data-next-find-goal-note>
      {message}
    </p>
  );
}

/* The prompts a found goal was found in, each as its entry number with the words quoted from it beneath. The
   number is drawn as the Drift card draws a cited entry:
   hovering or focusing one shows the entry in place, and "See in context of the session" opens Full activity at
   that entry, reading older pages for it first where the page does not hold it yet. */
export function FoundCites() {
  const { input } = usePanel();
  const drift = useContext(DriftContext);
  const [missing, setMissing] = useState('');
  const found = foundGoal(input);
  if (!found) return null;
  const number = (id: string, ordinal: number | null): string | null => {
    const held = drift?.model.labels.get(id);
    return held ?? (ordinal === null ? null : String(ordinal));
  };
  return (
    <>
      <small className="next-cockpit-held-source" data-next-found-cites>
        {'From '}
        {found.cites.map((cite, index) => {
          const n = number(cite.factId, cite.ordinal);
          const where = n ? `#${n}` : `the entry at ${clockText(cite.at ?? found.foundAt)}`;
          return (
            <span key={cite.factId}>
              {index ? ' ' : ''}
              <CitationLink
                id={cite.factId}
                data-next-cockpit-action="finding-jump"
                data-next-finding="found-goal"
                data-next-cite={cite.factId}
                aria-label={`Show ${where} in Full activity for the detected goal`}
                onJump={() => {
                  if (!drift) return;
                  setMissing('');
                  void openEntry(drift, cite.factId).then((landed) => {
                    if (!landed) setMissing(missingSentence(n, false));
                  });
                }}
              >
                {n ? `[${n}]` : `[${clockText(cite.at ?? found.foundAt)}]`}
              </CitationLink>
            </span>
          );
        })}
      </small>
      {/* The words the goal was taken from, which the server checked as verbatim in each prompt. The popover
          shows the entry as the activity list abbreviates it, so these are what tie the goal to the prompt. */}
      {found.cites.map((cite) => {
        const n = number(cite.factId, cite.ordinal);
        const where = n ? `#${n}` : clockText(cite.at ?? found.foundAt);
        return (
          <small
            key={cite.factId}
            className="next-cockpit-held-source"
            data-next-found-quote
          >{`${where} ${cite.quotes.map((quote) => `“${quote}”`).join(' ')}`}</small>
        );
      })}
      {missing ? (
        <p className="next-cockpit-held-absent" data-next-found-cites-missing>
          {missing}
        </p>
      ) : null}
    </>
  );
}

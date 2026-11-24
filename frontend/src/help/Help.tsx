import { useId, type ReactNode } from 'react';
import { Disclosure } from '../controls';
import { EXPLANATIONS, GLOSSARY, SESSION_ROW_WORDS } from '../language/glossary';
import { SAMPLE_HARNESS, SAMPLE_PROJECT, SAMPLE_SID } from '../sample/ids';
import { RouteLink } from '../shell/RouteLink';
import { Card } from '../ui/card';
import { Icon } from '../ui/icons';
import { STATUS_LEGEND } from '../ui/statusLegendEntries';
import { SUPPORTED_AGENTS } from './agents';

const HELP_EXAMPLE = {
  view: 'session',
  project: SAMPLE_PROJECT,
  harness: SAMPLE_HARNESS,
  session: SAMPLE_SID,
  from: 'help',
} as const;

const ICON_MEANINGS: Readonly<Record<string, string>> = {
  [SESSION_ROW_WORDS.working]: 'The agent is working.',
  [SESSION_ROW_WORDS.waitingOnYou]: 'The session needs your input or approval to continue.',
  [SESSION_ROW_WORDS.quiet]: 'The agent finished its turn and is waiting for your next message.',
  [SESSION_ROW_WORDS.ended]: 'The session reported that it ended.',
  [SESSION_ROW_WORDS.stateNotKnown]:
    'The agent reports it is idle, but Compass saw no finished turn, so it cannot say whether it is quiet or stopped. It also shows when the agent publishes no state at all.',
  [SESSION_ROW_WORDS.worthALook]:
    'A flag for a session that may need a closer look, such as one that ended with uncommitted work.',
};

const LEVELS = [
  [GLOSSARY.onTrack.plain, 'No departure found in what Compass read'],
  [SESSION_ROW_WORDS.slightlyOffCourse, 'Some work wandered from the goal.'],
  [SESSION_ROW_WORDS.offCourse, 'The work no longer serves the goal.'],
  [SESSION_ROW_WORDS.wayOffCourse, 'The work has gone far from the goal.'],
] as const;

const ABSENCES = [
  [
    SESSION_ROW_WORDS.noGoalYet,
    'Open the session and add a goal there to give Compass something to read against.',
  ],
  [
    SESSION_ROW_WORDS.notCheckedYet,
    'Check progress to ask Compass to read the record against the goal.',
  ],
  [SESSION_ROW_WORDS.tooEarlyToTell, 'The session has recorded too little for a reading.'],
  [
    SESSION_ROW_WORDS.cantTell,
    'What Compass read found no departure and gives too little evidence to say the goal was met.',
  ],
  [SESSION_ROW_WORDS.goalTooVague, 'Say what should be true when the work is done.'],
  [
    SESSION_ROW_WORDS.outOfDate,
    'The earlier reading no longer describes the evidence Compass can use.',
  ],
] as const;

function HelpCard({
  title,
  intro,
  children,
}: {
  readonly title: string;
  readonly intro?: string;
  readonly children: ReactNode;
}) {
  const heading = useId();
  return (
    <Card
      as="section"
      className="overflow-hidden [&_p]:m-0 [&_p]:text-muted-foreground"
      aria-labelledby={heading}
    >
      <header className="p-6">
        <h2 id={heading} className="m-0 text-value font-bold">
          {title}
        </h2>
        {intro ? <p>{intro}</p> : null}
      </header>
      {children}
    </Card>
  );
}

export function Help() {
  return (
    <div className="mx-auto my-8 grid w-full max-w-[920px] gap-6" data-next-view-body="help">
      <header>
        <h1 className="mt-0 mb-2 text-hero font-extrabold">How Compass works</h1>
        <p className="m-0 text-value text-muted-foreground">
          Compass shows which coding agents on this computer are working, which need you, and how
          their work lines up with the goals you set.
        </p>
      </header>
      <Card
        as="section"
        className="flex flex-wrap items-center justify-between gap-4 bg-[var(--status-ended-bg)] p-6"
      >
        <div className="grow basis-[380px]">
          <h2 className="m-0 text-value font-bold">See it on a real example</h2>
          <p className="m-0">
            Open an ended session to see goals, progress checks and Steer back. The example stays on
            this page and saves no changes.
          </p>
        </div>
        <RouteLink route={HELP_EXAMPLE} variant="primary">
          See an example
        </RouteLink>
      </Card>
      <HelpCard
        title="What the icons mean"
        intro="The same icons appear on Sessions, Projects and Needs you."
      >
        <ul aria-label="Session icons" className="m-0 list-none p-0">
          {STATUS_LEGEND.map(([word, icon]) => (
            <li className="help-row" key={word}>
              <span
                /* The neutral State not known tile: quiet ink on the page ground, as on a row. */
                className={`help-icon grid h-9 basis-9 shrink-0 place-items-center rounded-card${icon === 'state-not-known' ? ' bg-[var(--bg)] text-[var(--ink2)]' : ''}`}
                data-help-icon={icon}
              >
                <Icon name={icon} size={20} />
              </span>
              <div>
                <strong>{word}</strong>
                <p>{ICON_MEANINGS[word]}</p>
              </div>
            </li>
          ))}
        </ul>
      </HelpCard>
      <HelpCard
        title="Goals and progress checks"
        intro="Give a session a goal that says what should be true when the work is done. A progress check compares its record with that goal."
      >
        <dl className="m-0 p-0">
          {LEVELS.map(([word, meaning], index) => (
            <div className="help-row" key={word}>
              <dt>
                <span
                  className="help-level rounded-pill border border-current px-2 py-0.5 text-label"
                  data-level={index}
                >
                  {word}
                </span>
              </dt>
              <dd>{meaning}</dd>
            </div>
          ))}
          {ABSENCES.map(([word, meaning]) => (
            <div className="help-row help-absence" key={word}>
              <dt>{word}</dt>
              <dd>{meaning}</dd>
            </div>
          ))}
        </dl>
        <p className="mx-6">
          On Sessions, a saved check can show {SESSION_ROW_WORDS.slightlyOffCourse} or{' '}
          {SESSION_ROW_WORDS.offCourse} while its evidence still matches. Use Filters to find those
          rows. Open the session to see what the check read.
        </p>
        <RouteLink route={{ ...HELP_EXAMPLE, explain: 'goal' }} className="mx-6 text-primary">
          {EXPLANATIONS.goals}
        </RouteLink>
      </HelpCard>
      <HelpCard title="Common questions">
        <Disclosure
          className="px-6"
          disclosureKey="help:ai"
          summary="What gets sent to an AI, and where?"
        >
          <p>
            Summaries and progress checks can send selected session text and your goal to the
            provider named on the session page. Open What is sent there to see the destination and
            scope. You can Pause all AI use in{' '}
            <RouteLink route={{ view: 'settings' }}>Settings</RouteLink>.
          </p>
        </Disclosure>
        <Disclosure
          className="px-6"
          disclosureKey="help:agents"
          summary="Which agents can Compass see?"
        >
          <p>{Object.values(SUPPORTED_AGENTS).join(', ')}.</p>
          <p>
            Some agents publish fewer signals. See What Compass can't see in{' '}
            <RouteLink route={{ view: 'attention' }}>Needs you</RouteLink>.
          </p>
        </Disclosure>
        <Disclosure
          className="px-6"
          disclosureKey="help:projects"
          summary="Why are some sessions in an Unnamed folder?"
        >
          <p>
            Compass groups sessions using the folder labels their agents report. Sessions without a
            folder label appear under Unnamed folder.
          </p>
        </Disclosure>
        <Disclosure
          className="px-6"
          disclosureKey="help:allowance"
          summary={EXPLANATIONS.aiAllowance}
        >
          <p>
            Compass reads your plan’s usage through the sign-ins on this computer. Usage requests
            carry no session text. See the available readings and controls under Usage and alerts on
            a <RouteLink route={{ view: 'projects' }}>project page</RouteLink>.
          </p>
        </Disclosure>
      </HelpCard>
    </div>
  );
}

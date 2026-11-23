import { useId, type ReactNode } from 'react';
import { Disclosure } from '../controls';
import { EXPLANATIONS, GLOSSARY, SESSION_ROW_WORDS } from '../language/glossary';
import { SAMPLE_HARNESS, SAMPLE_PROJECT, SAMPLE_SID } from '../sample/ids';
import { RouteLink } from '../shell/RouteLink';
import { Card } from '../ui/card';
import { Icon } from '../ui/icons';
import { STATUS_LEGEND } from '../ui/statusLegendEntries';
import { SUPPORTED_AGENTS } from './agents';
import './help.css';

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
  [SESSION_ROW_WORDS.noGoalYet, 'Add a goal to give Compass something to read against.'],
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
    <Card as="section" className="help-card" aria-labelledby={heading}>
      <header>
        <h2 id={heading}>{title}</h2>
        {intro ? <p>{intro}</p> : null}
      </header>
      {children}
    </Card>
  );
}

export function Help() {
  return (
    <div className="next-help" data-next-view-body="help">
      <header>
        <h1>How Compass works</h1>
        <p className="text-value text-muted-foreground">
          Compass shows which coding agents on this computer are working, which need you, and how
          their work lines up with the goals you set.
        </p>
      </header>
      <Card as="section" className="help-example">
        <div>
          <h2>See it on a real example</h2>
          <p>
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
        <ul aria-label="Session icons">
          {STATUS_LEGEND.map(([word, icon]) => (
            <li className="help-row" key={word}>
              <span className="help-icon" data-help-icon={icon}>
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
        <dl>
          {LEVELS.map(([word, meaning], index) => (
            <div className="help-row" key={word}>
              <dt>
                <span className="help-level" data-level={index}>
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
        <RouteLink route={{ ...HELP_EXAMPLE, explain: 'goal' }} className="help-link">
          {EXPLANATIONS.goals}
        </RouteLink>
      </HelpCard>
      <HelpCard title="Common questions">
        <Disclosure disclosureKey="help:ai" summary="What gets sent to an AI, and where?">
          <p>
            Summaries and progress checks can send selected session text and your goal to the
            provider named on the session page. Open What is sent there to see the destination and
            scope. You can Pause all AI use in{' '}
            <RouteLink route={{ view: 'settings' }}>Settings</RouteLink>.
          </p>
        </Disclosure>
        <Disclosure disclosureKey="help:agents" summary="Which agents can Compass see?">
          <p>{Object.values(SUPPORTED_AGENTS).join(', ')}.</p>
          <p>
            Some agents publish fewer signals. See What Compass can't see in{' '}
            <RouteLink route={{ view: 'attention' }}>Needs you</RouteLink>.
          </p>
        </Disclosure>
        <Disclosure
          disclosureKey="help:projects"
          summary="Why are some sessions in an Unnamed folder?"
        >
          <p>
            Compass groups sessions using the folder labels their agents report. Sessions without a
            folder label appear under Unnamed folder.
          </p>
        </Disclosure>
        <Disclosure disclosureKey="help:allowance" summary={EXPLANATIONS.aiAllowance}>
          <p>
            Compass reads your plan’s usage through the sign-ins on this computer. Usage requests
            carry no session text. You can control them in{' '}
            <RouteLink route={{ view: 'settings' }}>Settings</RouteLink>.
          </p>
        </Disclosure>
        <Disclosure disclosureKey="help:data" summary="Where can I forget everything?">
          <p>
            Open Your data in <RouteLink route={{ view: 'settings' }}>Settings</RouteLink> to see
            the commands and what they remove.
          </p>
        </Disclosure>
      </HelpCard>
    </div>
  );
}

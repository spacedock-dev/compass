/* The sample session's numbered notes, in the order a reader meets the parts of the page. Each says what
   a part is for and what it shows in this session. The same words are the popups and the text legend in the
   banner, so a popup never carries the only copy of a fact; a mark's own label names its note. */
export interface TourNote {
  readonly id: string;
  readonly title: string;
  readonly body: string;
}

export const TOUR: readonly TourNote[] = [
  {
    id: 'intent',
    title: 'Your intent',
    body: 'The goal and the outcome you expect, in your own words. Here the person set the goal once: burn a milestone down fully, with every issue in it closed. Compass reads the session against these words and never writes into the session.',
  },
  {
    id: 'summary',
    title: 'What the session has done',
    body: 'A summary a model wrote from the record when the finished session was opened, in phases, each line citing the entries it rests on. A line that says in its own voice that work was done is withheld and says so. A line may report what someone said, a tracker’s state or a check’s own reported result, but not claim the work is done. Compass checks that a cited entry exists, not that it supports the line. The outline below it is Compass’s own grouping, made with no model.',
  },
  {
    id: 'phase',
    title: 'A phase that holds a departure',
    body: 'A phase whose entries are evidence for a departure says so, and links to its card. Here three phases hold it: the milestone stood with issues still open, and at the end, short of closing every issue, the agent reported a blocker, and the person replied that the open issue stays and is to be finished.',
  },
  {
    id: 'departure',
    title: 'A departure, and its evidence',
    body: 'The analysis compares your words with the record. Each departure names what it rests on under What, by entry number, and says why in one sentence. Press a number and Full activity opens on that entry, with every cited entry lit up. It is an account of the evidence, never a verification that the work was done.',
  },
  {
    id: 'steer',
    title: 'Steer back',
    body: 'A correction written from your own goal and expected outcome, naming the entries by number. Copy it and paste it into the session yourself. Compass never sends anything into a session.',
  },
  {
    id: 'sent',
    title: 'What is sent, and Pause model calls',
    body: 'A summary or an analysis runs on your action, through your own Claude Code. The first of each kind says once what leaves your machine and where, and Pause model calls stops every one of them in one press. Each counts against a daily limit.',
  },
  {
    id: 'activity',
    title: 'Full activity: everything the session did',
    body: 'Collapsed at the foot of the page. Every message the agent wrote, every check it ran and every file it wrote, numbered from #1 for the oldest. A number never moves, so an entry a summary line or a correction cites still points at it later. A check or file takes the number of the message it follows, such as #50.1.',
  },
];

export const TOUR_BY_ID: ReadonlyMap<string, { readonly note: TourNote; readonly n: number }> =
  new Map(TOUR.map((note, index) => [note.id, { note, n: index + 1 }]));

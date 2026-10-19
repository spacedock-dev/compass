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
    body: 'The goal and the outcomes you expect, in your own words. Compass compares the session with these and never writes into the session. Here the goal says to leave the pull request’s code alone, so changing it is what drift looks like.',
  },
  {
    id: 'level',
    title: 'The drift level',
    body: 'None or low, Medium, High or Extreme. Here it is High. A live estimate reads only recorded checks and file paths, with no model involved (it is High because a check failed after the last message and nothing has fixed it), and the analysis below adds a stored reading of your goal against the record.',
  },
  {
    id: 'analysis',
    title: 'What the analysis found',
    body: 'One reading asks a model to compare your goal with what is on record. It found a departure: after a clean rebase the agent added a test and started changing code, when only history was meant to change. It is an account of the evidence, never a verification that the work was done.',
  },
  {
    id: 'cited',
    title: 'Check the evidence yourself',
    body: 'Every finding names the entries it rests on, by number. Press a number and Full activity opens on that entry, with every entry the finding cites lit up in the list and the words of the finding beside them, so you can see what the claim stands on.',
  },
  {
    id: 'steer',
    title: 'Steer back',
    body: 'A correction written from your own goal and expected outcomes, naming the entries by number. Copy it and paste it into the session yourself. Compass never sends anything into a session.',
  },
  {
    id: 'sent',
    title: 'What is sent',
    body: 'Before a reading runs you see exactly what would leave your machine and where it goes, and you allow it. A reading is one request, counted against a daily limit, and you can switch readings off.',
  },
  {
    id: 'activity',
    title: 'Full activity: everything the session did',
    body: 'Collapsed at the foot of the page. Every message the agent wrote, every check it ran and every file it wrote, numbered from #1 for the oldest. A number never moves, so a correction that names an entry still points at it later. A check or file takes the number of the message it follows, such as #12.1.',
  },
];

export const TOUR_BY_ID: ReadonlyMap<string, { readonly note: TourNote; readonly n: number }> =
  new Map(TOUR.map((note, index) => [note.id, { note, n: index + 1 }]));

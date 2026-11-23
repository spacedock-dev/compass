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
    title: 'Your goal',
    body: 'The goal for the session, written as what should be true when the work is done. Here the person set it once: “Every issue in the milestone is closed.” For your own session you can type it, choose one of your prompts, press Find goal, or let Compass pick up a goal you set with /goal in Claude Code. Compass checks the session against it and never writes into the session.',
  },
  {
    id: 'departure',
    title: 'A departure, and its evidence',
    body: 'Check progress compares your goal with the record. The card says where the work went off course. The quotes link opens Evidence, with each cited entry in its own words. Press a citation there to open Activity log on that entry, with every cited entry lit up. It is an account of the evidence, never a verification that the work was done.',
  },
  {
    id: 'steer',
    title: 'Steer back',
    body: 'An editable message based on your goal. Copy it and paste it into the session yourself. Compass never sends it for you.',
  },
  {
    id: 'sent',
    title: 'What is sent, and Pause all AI use',
    body: 'A summary or a progress check runs when you press its button, through your own Claude Code. What is sent explains what leaves your machine and where. Pause all AI use stops every one of them in one press. Each counts against a daily limit.',
  },
  {
    id: 'summary',
    title: "What's happened so far",
    body: 'A summary a model wrote from the record when the finished session was opened. Its phases start closed: open a phase to read its lines and their sources. Opening another phase closes the previous one. A line that claims in its own voice that work was done is held back and says so. Compass checks that a cited entry exists, not that it supports the line. The outline below the summary is Compass’s own grouping, made with no model.',
  },
  {
    id: 'phase',
    title: 'A phase that holds a departure',
    body: 'Off course here opens the evidence for a departure in that phase. Here three phases hold the one departure from the goal: the agent’s readback that the milestone stands at 97.3%, the walk finding a blocker so the milestone can’t close yet, and at the end the person replying that the open issue stays and is to be finished while a pull request is still behind main.',
  },
  {
    id: 'activity',
    title: 'Activity log',
    body: 'Open Show technical details at the foot of the page to see the recorded messages, commands and files. Sources and corrections open the same numbered entries. Earlier entries stay in the log even when they fall outside the progress check for your current goal.',
  },
];

export const TOUR_BY_ID: ReadonlyMap<string, { readonly note: TourNote; readonly n: number }> =
  new Map(TOUR.map((note, index) => [note.id, { note, n: index + 1 }]));

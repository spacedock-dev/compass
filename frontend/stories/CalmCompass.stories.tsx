import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, within } from 'storybook/test';
import type { CSSProperties, ReactNode } from 'react';
import { GLOSSARY } from '../src/language/glossary';
import { Alert } from '../src/ui/alert';
import { Button } from '../src/ui/button';
import { Card } from '../src/ui/card';
import { contrastOf } from './a11y.audit';

const palette = [
  ['Ground', '--bg'],
  ['Card', '--panel'],
  ['Ink', '--ink'],
  ['Quiet ink', '--ink2'],
  ['Compass green', '--accent'],
  ['Control border', '--line'],
  ['Working blue', '--status-working-ink'],
  ['Off-course orange', '--progress-off-course'],
] as const;
const radii = [
  ['Control', '--r-control'],
  ['Card', '--r-standard-card'],
  ['Shell', '--r-shell'],
  ['Pill', '--r-pill'],
] as const;

const columns: CSSProperties = {
  display: 'grid',
  gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 26rem), 1fr))',
  gap: 'var(--sp-5)',
};
const caption: CSSProperties = { color: 'var(--ink2)', fontSize: 'var(--fs-label)', margin: 0 };
const sampleList: CSSProperties = { listStyle: 'none', margin: 0, padding: 0 };
const panel: CSSProperties = {
  backgroundColor: 'var(--panel)',
  border: '1px solid var(--rule)',
  borderRadius: 'var(--r-shell)',
  padding: 'var(--sp-5)',
  minWidth: 0,
};
const subheading: CSSProperties = { fontSize: 'var(--fs-value)', fontWeight: 650, margin: 0 };
const row: CSSProperties = {
  borderBottom: '1px solid var(--rule)',
  paddingBlock: 'var(--sp-3)',
};

function Panel({
  id,
  title,
  children,
}: {
  readonly id: string;
  readonly title: string;
  readonly children: ReactNode;
}) {
  return (
    <section aria-labelledby={id} style={panel}>
      <h2
        id={id}
        style={{ fontSize: 'var(--fs-head)', fontWeight: 700, margin: '0 0 var(--sp-3)' }}
      >
        {title}
      </h2>
      {children}
    </section>
  );
}

function tokenReader() {
  const root = getComputedStyle(document.documentElement);
  const probe = document.createElement('canvas');
  probe.width = probe.height = 1;
  const context = probe.getContext('2d', { willReadFrequently: true });
  if (!context) throw new Error('Could not measure palette contrast');
  const value = (token: string) => root.getPropertyValue(token).trim();
  const color = (token: string): [number, number, number] => {
    context.clearRect(0, 0, 1, 1);
    context.fillStyle = value(token);
    context.fillRect(0, 0, 1, 1);
    const [red = 0, green = 0, blue = 0] = context.getImageData(0, 0, 1, 1).data;
    return [red, green, blue];
  };
  return { value, color };
}

function ColorSamples() {
  const tokens = tokenReader();
  const card = tokens.color('--panel');
  const ground = tokens.color('--bg');
  return (
    <Panel id="calm-color" title="Color">
      <ul
        role="list"
        style={{
          ...sampleList,
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 6.5rem), 1fr))',
          gap: 'var(--sp-3)',
        }}
      >
        {palette.map(([label, token]) => {
          const ink = tokens.color(token);
          const onCard = contrastOf(ink, card).toFixed(2);
          const onGround = contrastOf(ink, ground).toFixed(2);
          return (
            <li key={token} style={{ ...caption, overflowWrap: 'anywhere' }}>
              <div
                data-swatch={token}
                aria-hidden="true"
                style={{
                  height: '4rem',
                  marginBottom: 'var(--sp-1)',
                  backgroundColor: `var(${token})`,
                  border: '1px solid var(--rule)',
                  borderRadius: 'var(--r-card)',
                }}
              />
              <strong style={{ display: 'block', color: 'var(--ink)' }}>{label}</strong>
              <span style={{ display: 'block' }}>{tokens.value(token)}</span>
              <span>
                Card {onCard}:1 · Ground {onGround}:1
              </span>
            </li>
          );
        })}
      </ul>
      <p style={{ ...caption, marginTop: 'var(--sp-4)' }}>
        Control borders need at least 3:1 against their surface. Ground and card swatches show
        decorative surfaces.
      </p>
    </Panel>
  );
}

function TypeSamples() {
  const examples = [
    ['--fs-hero', 800, 'Good afternoon', '34 px · Page titles'],
    ['--fs-head', 700, 'All sessions', '24 px · Section titles'],
    ['--fs-value', 650, 'Session summary', '18 px · Card titles'],
    ['--fs-body', 400, 'Waiting for you to approve a command.', '15 px · Body'],
    ['--fs-label', 500, 'Last active 2 minutes ago', '13 px · Supporting text and badges'],
  ] as const;
  return (
    <Panel id="calm-type" title="Type">
      <div style={{ display: 'grid', gap: 'var(--sp-3)' }}>
        {examples.map(([step, weight, sample, use]) => (
          <div key={step}>
            <p
              data-type-sample
              style={{ fontSize: `var(${step})`, fontWeight: weight, lineHeight: 1.25, margin: 0 }}
            >
              {sample}
            </p>
            <p data-type-sample style={caption}>
              {use}
            </p>
          </div>
        ))}
        <div aria-label="Technical details only">
          <p style={caption}>Technical details only</p>
          <code data-type-sample style={{ ...caption, fontFamily: 'var(--mono)' }}>
            #81 · Agent said · 19:29
          </code>
        </div>
      </div>
    </Panel>
  );
}

function StatusLanguage() {
  return (
    <Panel id="calm-status-language" title="One status language">
      <div style={columns}>
        <section aria-labelledby="calm-status">
          <h3 id="calm-status" style={subheading}>
            Status
          </h3>
          <dl style={{ margin: 0 }}>
            {[
              [GLOSSARY.working.plain, 'The agent is busy.'],
              [GLOSSARY.waitingOnYou.plain, 'The agent needs your answer.'],
              [
                GLOSSARY.quiet.plain,
                'The agent finished its turn and is waiting for your next message.',
              ],
              [GLOSSARY.ended.plain, 'The session reported that it ended.'],
            ].map(([word, description]) => (
              <div
                key={word}
                style={{
                  ...row,
                  display: 'grid',
                  gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 10rem), 1fr))',
                  gap: 'var(--sp-1) var(--sp-3)',
                }}
              >
                <dt style={{ fontWeight: 650 }}>{word}</dt>
                <dd style={{ color: 'var(--ink2)', margin: 0 }}>{description}</dd>
              </div>
            ))}
          </dl>
        </section>
        <section aria-labelledby="calm-progress">
          <h3 id="calm-progress" style={subheading}>
            Progress pills
          </h3>
          <p style={caption}>A row shows a pill when a stored check found a departure.</p>
          <ul role="list" style={sampleList}>
            {[GLOSSARY.slightlyOffCourse, GLOSSARY.offCourse, GLOSSARY.wayOffCourse].map(
              ({ plain }) => (
                <li key={plain} style={row}>
                  {plain}
                </li>
              ),
            )}
          </ul>
          <p style={{ ...caption, marginTop: 'var(--sp-3)' }}>
            {[
              GLOSSARY.noGoalYet,
              GLOSSARY.notCheckedYet,
              GLOSSARY.tooEarlyToTell,
              GLOSSARY.cantTell,
              GLOSSARY.goalTooVague,
              GLOSSARY.outOfDate,
            ]
              .map(({ plain }) => plain)
              .join(' · ')}
          </p>
        </section>
      </div>
    </Panel>
  );
}

function Pieces() {
  const buttons: CSSProperties = {
    display: 'flex',
    alignItems: 'center',
    flexWrap: 'wrap',
    gap: 'var(--sp-3)',
  };
  return (
    <Panel id="calm-pieces" title="Pieces">
      <div style={buttons}>
        <Button emphasis="primary">{GLOSSARY.checkProgress.plain}</Button>
        <Button emphasis="secondary">Edit goal</Button>
        <Button emphasis="quiet">Not now</Button>
      </div>
      <p style={{ ...caption, marginBlock: 'var(--sp-2) var(--sp-4)' }}>
        Uses AI · The daily count appears when 10 or fewer checks remain.
      </p>
      <div style={buttons}>
        <Button emphasis="primary" disabled>
          {GLOSSARY.checkProgress.plain} unavailable
        </Button>
        <span style={caption}>Disabled</span>
      </div>
      <Card style={{ marginBlock: 'var(--sp-4)' }}>
        <h3 style={subheading}>Card</h3>
        <p style={{ margin: 0 }}>16 px radius, 1 px border and 24 px padding.</p>
      </Card>
      <Alert variant="notice" announce={false}>
        New to Compass? See a sample session.
      </Alert>
    </Panel>
  );
}

function RadiusSamples() {
  return (
    <Panel id="calm-radii" title="Radii">
      <ul
        role="list"
        style={{ ...sampleList, display: 'flex', flexWrap: 'wrap', gap: 'var(--sp-4)' }}
      >
        {radii.map(([label, token]) => (
          <li key={token} style={caption}>
            <div
              aria-hidden="true"
              data-radius={token}
              style={{
                borderRadius: `var(${token})`,
                width: '3.5rem',
                height: '2.5rem',
                backgroundColor: 'var(--sunk)',
                border: '1px solid var(--line)',
                marginBottom: 'var(--sp-1)',
              }}
            />
            {label}
          </li>
        ))}
      </ul>
    </Panel>
  );
}

function ReservedExamples() {
  return (
    <Panel id="calm-reserved" title="Reserved examples">
      <div style={columns}>
        {[
          ['Switch', 'The shared Switch will appear here when it ships.'],
          ['How … works', 'A short explanation opens beside the words it explains.'],
          [GLOSSARY.showTechnicalDetails.plain, 'Activity log, AI use, limits and raw evidence.'],
          ['Stepped slider', 'Choose how much a progress check reads.'],
          ['Forget everything', 'The explanation opens inline in the Your data card.'],
        ].map(([title, note]) => (
          <section key={title} style={row}>
            <h3 style={subheading}>{title}</h3>
            <p style={caption}>{note}</p>
          </section>
        ))}
      </div>
    </Panel>
  );
}

function WordsWeUseNow() {
  const cell: CSSProperties = { ...row, paddingInlineEnd: 'var(--sp-3)', textAlign: 'left' };
  return (
    <Panel id="calm-words" title="Words we use now">
      <table aria-labelledby="calm-words" style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead>
          <tr>
            <th scope="col" style={{ ...cell, width: '50%' }}>
              Plain word
            </th>
            <th scope="col" style={cell}>
              Replaces
            </th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(GLOSSARY).map(([key, { plain, replaces }]) => (
            <tr key={key}>
              <th scope="row" style={{ ...cell, fontWeight: 650 }}>
                {plain}
              </th>
              <td style={{ ...cell, color: 'var(--ink2)' }}>{replaces}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Panel>
  );
}

function Guide() {
  return (
    <main
      style={{
        marginInline: 'auto',
        maxWidth: '72rem',
        padding: 'clamp(1rem, 4vw, 3rem)',
        display: 'grid',
        gap: 'var(--sp-5)',
        backgroundColor: 'var(--bg)',
        color: 'var(--ink)',
        fontFamily: 'var(--sans)',
        fontSize: 'var(--fs-body)',
      }}
    >
      <header>
        <h1 style={{ fontSize: 'var(--fs-hero)', fontWeight: 800, margin: 0 }}>Calm Compass</h1>
        <p style={{ color: 'var(--ink2)', margin: 'var(--sp-2) 0 0' }}>
          Once signed off, the Storybook example is the reference for that piece.
        </p>
      </header>
      <div style={columns}>
        <ColorSamples />
        <TypeSamples />
      </div>
      <StatusLanguage />
      <div style={columns}>
        <RadiusSamples />
        <Pieces />
      </div>
      <ReservedExamples />
      <WordsWeUseNow />
    </main>
  );
}

function measuredLuminance(element: Element) {
  const channels = (getComputedStyle(element).backgroundColor.match(/[\d.]+/g) ?? [])
    .slice(0, 3)
    .map((value) => Number(value) / 255)
    .map((value) => (value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4));
  const [red, green, blue] = channels;
  if (red === undefined || green === undefined || blue === undefined)
    throw new Error('Expected an RGB swatch');
  return 0.2126 * red + 0.7152 * green + 0.0722 * blue;
}

const contrastRatio = (one: number, other: number) =>
  ((Math.max(one, other) + 0.05) / (Math.min(one, other) + 0.05)).toFixed(2);

const meta = { title: 'Design/Calm Compass' } satisfies Meta;
export default meta;
type Story = StoryObj<typeof meta>;

export const StyleGuide: Story = {
  render: () => <Guide />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole('heading', { level: 1, name: 'Calm Compass' })).toBeVisible();
    const colors = canvas.getByRole('region', { name: 'Color' });
    const swatches = colors.querySelectorAll<HTMLElement>('[data-swatch]');
    await expect(swatches).toHaveLength(8);
    const card = colors.querySelector('[data-swatch="--panel"]');
    const ground = colors.querySelector('[data-swatch="--bg"]');
    if (!card || !ground) throw new Error('Expected the Card and Ground swatches');
    const rootStyle = getComputedStyle(document.documentElement);
    const reference = document.createElement('span');
    colors.append(reference);
    try {
      for (const swatch of swatches) {
        const token = swatch.dataset['swatch'] ?? '';
        const value = rootStyle.getPropertyValue(token).trim();
        await expect(value, token).not.toBe('');
        reference.style.backgroundColor = value;
        await expect(getComputedStyle(swatch).backgroundColor, token).toBe(
          getComputedStyle(reference).backgroundColor,
        );
        await expect(swatch.style.backgroundColor, token).toBe(`var(${token})`);
        const luminance = measuredLuminance(swatch);
        const cardRatio = contrastRatio(luminance, measuredLuminance(card));
        const groundRatio = contrastRatio(luminance, measuredLuminance(ground));
        await expect(swatch.parentElement).toHaveTextContent(
          `Card ${cardRatio}:1 · Ground ${groundRatio}:1`,
        );
      }
    } finally {
      reference.remove();
    }

    const type = canvas.getByRole('region', { name: 'Type' });
    const steps = new Set<number>();
    for (const sample of type.querySelectorAll('[data-type-sample]')) {
      const { fontSize, fontFamily } = getComputedStyle(sample);
      const size = Number.parseFloat(fontSize);
      await expect([13, 15, 18, 24, 34], sample.textContent ?? '').toContain(size);
      steps.add(size);
      if (sample.closest('[aria-label="Technical details only"]'))
        await expect(fontFamily.split(',')[0]?.trim()).toBe('ui-monospace');
      else await expect(fontFamily.split(',')[0]?.trim()).toBe('Inter');
    }
    await expect([...steps].sort((a, b) => a - b)).toEqual([13, 15, 18, 24, 34]);
    await expect(
      type.querySelectorAll('[aria-label="Technical details only"] [data-type-sample]'),
    ).toHaveLength(1);

    const statusRegion = canvas.getByRole('region', { name: 'Status' });
    const status = within(statusRegion);
    for (const word of ['Working', 'Waiting on you', 'Quiet', 'Ended'])
      await expect(status.getByText(word, { exact: true })).toBeVisible();
    for (const word of ['Needs you', 'Finished', 'Paused', 'Idle'])
      await expect(status.queryByText(word, { exact: true })).toBeNull();
    await expect(statusRegion.querySelector('svg, img')).toBeNull();

    const words = within(canvas.getByRole('table', { name: 'Words we use now' }));
    await expect(words.getByRole('columnheader', { name: 'Plain word' })).toBeVisible();
    await expect(words.getByRole('columnheader', { name: 'Replaces' })).toBeVisible();
    for (const [plain, earlier] of [
      ['Goal', 'Intent, Intent and drift'],
      ['Helpers', 'Subagents'],
      ['Needs you', 'Attention'],
      ['Goal history', 'Intent log'],
      ['Quiet', 'Idle'],
      ['Update my goal instead', 'Update intent instead'],
    ] as const) {
      const item = within(words.getByRole('row', { name: plain + ' ' + earlier }));
      await expect(item.getByRole('rowheader', { name: plain })).toBeVisible();
      await expect(item.getByRole('cell', { name: earlier })).toBeVisible();
    }

    const radiusSamples = canvas.getByRole('region', { name: 'Radii' });
    const corners = radiusSamples.querySelectorAll<HTMLElement>('[data-radius]');
    await expect(corners).toHaveLength(4);
    const corner = document.createElement('span');
    radiusSamples.append(corner);
    try {
      for (const shape of corners) {
        const token = shape.dataset['radius'] ?? '';
        corner.style.borderRadius = rootStyle.getPropertyValue(token).trim();
        await expect(getComputedStyle(shape).borderTopLeftRadius, token).toBe(
          getComputedStyle(corner).borderTopLeftRadius,
        );
      }
    } finally {
      corner.remove();
    }

    const pieces = within(canvas.getByRole('region', { name: 'Pieces' }));
    const progress = pieces.getByRole('button', { name: 'Check progress' });
    await expect(progress).toHaveAttribute('data-slot', 'button');
    await expect(progress.getBoundingClientRect().height).toBeGreaterThanOrEqual(44);
    await expect(pieces.getByRole('button', { name: 'Check progress unavailable' })).toBeDisabled();
    const componentCard = pieces
      .getByRole('heading', { name: 'Card' })
      .closest('[data-slot="card"]');
    await expect(componentCard).toHaveStyle({
      borderLeftWidth: '1px',
      borderRadius: '16px',
      boxShadow: 'none',
    });
    await expect(pieces.getByText('New to Compass? See a sample session.')).toHaveStyle({
      backgroundColor: 'rgb(230, 242, 236)',
    });
    const reserved = within(canvas.getByRole('region', { name: 'Reserved examples' }));
    for (const heading of [
      'Switch',
      'How … works',
      'Show technical details',
      'Stepped slider',
      'Forget everything',
    ])
      await expect(reserved.getByRole('heading', { name: heading })).toBeVisible();
    await expect(
      reserved.getByText('The shared Switch will appear here when it ships.'),
    ).toBeVisible();
  },
};

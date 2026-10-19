import { useState } from 'react';
import { compatSessKey } from '../api/identity';
import {
  Select,
  SelectTrigger,
  SelectValue,
  SelectContent,
  SelectGroup,
  SelectLabel,
  SelectItem,
} from '../ui/select';
import { useFocusKey } from '../controls';
import { goalKey, goalSourceLine, promptClip, promptMenu, promptChoices } from './derive';
import { choosePrompt } from './edit';
import { closePromptMenu, loadPromptChoices } from './prompts';
import { usePanel } from './useIntent';

/* Two different absences, said apart. A long session's focused record holds only its newest events, so
   the reader's own prompts can all lie outside it; that is a limit of what is read, not a claim that
   none were written. */
const EMPTY_NONE = 'No usable prompts were found in the parts of this session Compass read.';
const EMPTY_FAILED = 'Compass could not read your prompts from this session.';
/* Enough of a prompt to tell two apart, as the designer's item shows it; the whole prompt stays in its title. */
const PROMPT_SHOWN = 140;

/* Open before the async read: a browser picker requested after that read loses the click's user
   activation. Base UI keeps the same popup while loading and across board revisions.
   docs/design-shadcn-adoption.md#form-controls-layer owns that reversal. */
export function PromptSelect() {
  const { ctx, input, session, projectKey } = usePanel();
  const menu = promptMenu(input);
  const texts = new Map(
    promptChoices(ctx.held, input.contexts, session).map((choice) => [choice.factId, choice.text]),
  );
  const bounded = ctx.held.prompts.get(compatSessKey(session))?.bounded;
  /* Beside "Typed · saved", the face said "Use your prompt", which read as the goal's source. The action is the
     same; the face names it as a replacement for the reader's own words. The accessible name stays the action. */
  const face = goalSourceLine(input).startsWith('Typed')
    ? 'Replace with your prompt'
    : 'Use your prompt';
  const [open, setOpen] = useState(false);
  const focusKey = `${goalKey(session)}:prompt`;
  const ref = useFocusKey<HTMLButtonElement>(ctx.shell.controls.focusLane, focusKey);
  // A last offer disappearing must state the absence in the popup the reader already opened.
  if (!menu.visible && !open) return null;
  return (
    <div className="next-intent-prompt-pick ms-auto flex min-w-0 max-w-full w-[18rem] max-[760px]:w-full">
      <Select
        value={menu.value || null}
        open={open}
        items={menu.options}
        onOpenChange={(next) => {
          setOpen(next);
          if (next) void loadPromptChoices(ctx, input, projectKey);
          else closePromptMenu(ctx, session);
        }}
        onValueChange={(value) => {
          if (!value) return;
          choosePrompt(ctx, input, value, promptChoices(ctx.held, input.contexts, session));
        }}
      >
        <SelectTrigger
          ref={ref}
          className="next-intent-prompt-select ps-[12px] font-medium"
          data-next-cockpit-prompt-select
          data-next-focus={focusKey}
          aria-label="Use your prompt"
          aria-busy={menu.pending}
          title={menu.options.find((option) => option.value === menu.value)?.label ?? face}
        >
          <SelectValue placeholder={face} />
        </SelectTrigger>
        <SelectContent>
          <SelectGroup className="p-0">
            <SelectLabel className="px-3.5 pt-2.5 pb-1 [font-family:var(--mono)] text-label text-muted-foreground">
              Your prompts in this session
            </SelectLabel>
            {!menu.pending && bounded ? (
              <SelectItem value="__bound" disabled>
                The prompt search reached its limit. Older prompts may be outside this read.
              </SelectItem>
            ) : null}
            {menu.pending ? (
              <SelectItem value="__loading" disabled>
                Loading your prompts
              </SelectItem>
            ) : menu.options.length ? (
              menu.options.map((option) => {
                /* The option's `label` is pinned by the recorded answers, so the menu splits its name and
                   time off it and takes the longer text from the choice it names, rather than widening the
                   option shape those answers compare. */
                const sep = option.label.indexOf(' — ');
                const head = sep >= 0 ? option.label.slice(0, sep) : '';
                const whole = texts.get(option.value);
                const body =
                  whole !== undefined
                    ? promptClip(whole, PROMPT_SHOWN)
                    : sep >= 0
                      ? option.label.slice(sep + 3)
                      : option.label;
                return (
                  <SelectItem
                    key={option.value}
                    value={option.value}
                    title={
                      whole !== undefined ? `${head ? `${head} — ` : ''}${whole}` : option.label
                    }
                    className="[&>div]:line-clamp-none"
                  >
                    {head ? (
                      <>
                        <span className="block [font-family:var(--mono)] text-label text-muted-foreground">
                          {head}
                        </span>{' '}
                      </>
                    ) : null}
                    <span className="line-clamp-3 [overflow-wrap:anywhere]">{body}</span>
                  </SelectItem>
                );
              })
            ) : (
              <SelectItem value="__empty" disabled>
                {menu.failed ? EMPTY_FAILED : EMPTY_NONE}
              </SelectItem>
            )}
          </SelectGroup>
        </SelectContent>
      </Select>
    </div>
  );
}

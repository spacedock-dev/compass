import { useState } from 'react';
import { Popover as PopoverPrimitive } from '@base-ui/react/popover';
import { compatSessKey } from '../api/identity';
import { buttonVariants } from '../ui/button';
import { Popover, PopoverContent } from '../ui/popover';
import { useFocusKey } from '../controls';
import { goalKey, promptClip, promptMenu, promptChoices } from './derive';
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

/* A button that opens a list, as the design draws it, and not a select: nothing here holds a value, because
   the chosen prompt shows in the goal and its source line. The popup opens before the async read, because a
   request made after that read loses the click's user activation, and stays the same popup while the
   prompts load and across board revisions. */
export function PromptSelect() {
  const { ctx, input, session, projectKey } = usePanel();
  const menu = promptMenu(input);
  const texts = new Map(
    promptChoices(ctx.held, input.contexts, session).map((choice) => [choice.factId, choice.text]),
  );
  const bounded = ctx.held.prompts.get(compatSessKey(session))?.bounded;
  /* One label whatever the box holds: the face used to change to "Replace with your prompt", which made the
     control read as two. */
  const face = 'Use your prompt';
  const [open, setOpen] = useState(false);
  const focusKey = `${goalKey(session)}:prompt`;
  const ref = useFocusKey<HTMLButtonElement>(ctx.shell.controls.focusLane, focusKey);
  // A last offer disappearing must state the absence in the popup the reader already opened.
  if (!menu.visible && !open) return null;
  const absent = (value: string, text: string) => (
    <div
      role="option"
      aria-selected={false}
      aria-disabled="true"
      data-value={value}
      className="px-3.5 py-2 text-body text-muted-foreground"
    >
      {text}
    </div>
  );
  return (
    <div className="next-intent-prompt-pick ms-auto flex min-w-0 max-w-full w-[18rem] max-[760px]:w-full">
      <Popover
        open={open}
        onOpenChange={(next) => {
          setOpen(next);
          if (next) void loadPromptChoices(ctx, input, projectKey);
          else closePromptMenu(ctx, session);
        }}
      >
        <PopoverPrimitive.Trigger
          ref={ref}
          data-slot="prompt-trigger"
          className={`${buttonVariants({ variant: 'default' })} next-intent-prompt-select w-full justify-between gap-2 font-medium`}
          data-next-cockpit-prompt-select
          data-next-focus={focusKey}
          aria-label={face}
          aria-haspopup="listbox"
          aria-busy={menu.pending}
          title={face}
        >
          {face}
          <svg
            aria-hidden="true"
            viewBox="0 0 10 10"
            width="10"
            height="10"
            fill="none"
            className="pointer-events-none shrink-0 text-muted-foreground"
          >
            <path d="m2 3.5 3 3 3-3" stroke="currentColor" strokeWidth="1.5" />
          </svg>
        </PopoverPrimitive.Trigger>
        <PopoverContent align="end" className="p-0 px-0 py-1 w-[min(24rem,calc(100vw-32px))]">
          <div className="px-3.5 pt-2.5 pb-1 [font-family:var(--mono)] text-label text-muted-foreground">
            Your prompts in this session
          </div>
          <div role="listbox" aria-label="Your prompts in this session" aria-busy={menu.pending}>
            {!menu.pending && bounded
              ? absent(
                  '__bound',
                  'The prompt search reached its limit. Older prompts may be outside this read.',
                )
              : null}
            {menu.pending
              ? absent('__loading', 'Loading your prompts')
              : menu.options.length
                ? menu.options.map((option) => {
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
                      <button
                        type="button"
                        role="option"
                        aria-selected={false}
                        key={option.value}
                        data-value={option.value}
                        title={
                          whole !== undefined ? `${head ? `${head} — ` : ''}${whole}` : option.label
                        }
                        className="box-border block w-full min-h-[44px] cursor-pointer border-0 bg-transparent px-3.5 py-2 text-start text-body text-foreground hover:bg-accent hover:text-accent-foreground focus-visible:bg-accent focus-visible:outline-none"
                        onClick={() => {
                          choosePrompt(
                            ctx,
                            input,
                            option.value,
                            promptChoices(ctx.held, input.contexts, session),
                          );
                          setOpen(false);
                          closePromptMenu(ctx, session);
                        }}
                      >
                        {head ? (
                          <>
                            <span className="block [font-family:var(--mono)] text-label text-muted-foreground">
                              {head}
                            </span>{' '}
                          </>
                        ) : null}
                        <span className="line-clamp-3 [overflow-wrap:anywhere]">{body}</span>
                      </button>
                    );
                  })
                : absent('__empty', menu.failed ? EMPTY_FAILED : EMPTY_NONE)}
          </div>
        </PopoverContent>
      </Popover>
    </div>
  );
}

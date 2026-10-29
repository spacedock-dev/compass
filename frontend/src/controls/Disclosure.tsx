import { Accordion, AccordionItem, AccordionTrigger, AccordionContent } from '../ui/accordion';
import { useRevealFragment } from './useRevealFragment';
import {
  createContext,
  useContext,
  useCallback,
  useLayoutEffect,
  useRef,
  useState,
  useId,
  type ComponentProps,
  type MouseEvent,
  type FocusEvent,
  type ReactNode,
  type SyntheticEvent,
} from 'react';
import { Popover, PopoverTrigger, PopoverContent } from '../ui/popover';
import { useControls } from './kit';
import { useFocusKey } from './useFocusKey';
import { useDisclosureState, useControlledDisclosureState } from './useDisclosureState';
import { registerPopoverEscape } from './popoverEscape';

export interface DisclosureProps {
  /** The reader-state identity: see `disclosureKey`. Changing it remounts, so a node never carries one key's state to another. */
  readonly disclosureKey: string;
  readonly summary: ReactNode;
  /** An accordion eases in flow; a popover floats out of flow beside its summary; a menu fades over the page. */
  readonly variant?: 'accordion' | 'popover' | 'menu';
  readonly className?: string;
  /** The summary's accessible name when its visible text is a glyph. */
  readonly summaryLabel?: string;
  /** Registers the summary with the focus lane. */
  readonly focusKey?: string;
  /** Chrome for the popover's trigger itself, such as a filter button's border. Popover only. */
  readonly triggerClassName?: string;
  /** Marks drawn on the summary's row, right-aligned and outside the trigger, so they stay in view while the
   * panel is closed and may hold controls of their own. Accordion only. */
  readonly aside?: ReactNode;
  /** The heading drawn around the trigger, for a summary that is a heading of the page. Accordion only. */
  readonly headerProps?: ComponentProps<typeof AccordionTrigger>['headerProps'];
  /** Opens the first time this key is drawn, and never again: a reader who closes it keeps it closed, because
   * the write that opened it is the store's own and the reader's close is the next one. Accordion only. */
  readonly openByDefault?: boolean;
  /** Opens the panel when something the reader must not miss is in it: on the first draw of a key nothing has
   * written yet, and again each time this turns from false to true. A reader's own close holds while it stays
   * true, because the opening is an edge and not a state. Accordion only. */
  readonly openWhen?: boolean;
  readonly children: ReactNode;
}

export function Disclosure(props: DisclosureProps) {
  if (props.variant === 'popover')
    return <PopoverDisclosure key={props.disclosureKey} {...props} />;
  return props.variant === 'menu' ? (
    <DisclosureNode key={props.disclosureKey} {...props} />
  ) : (
    <AccordionDisclosure key={props.disclosureKey} {...props} />
  );
}

function AccordionDisclosure({
  disclosureKey,
  summary,
  className,
  summaryLabel,
  focusKey,
  aside,
  headerProps,
  openByDefault = false,
  openWhen = false,
  children,
}: DisclosureProps) {
  const controls = useControls();
  const open = useControlledDisclosureState(controls.disclosures, disclosureKey);
  const wasWhen = useRef<boolean | null>(null);
  /* `version` is zero until some write names the key, so a key the reader has opened or closed is never opened
     again, and one never touched opens exactly once. */
  useLayoutEffect(() => {
    if (openByDefault && controls.disclosures.version(disclosureKey) === 0)
      controls.disclosures.set(disclosureKey, true);
  }, [openByDefault, controls.disclosures, disclosureKey]);
  /* A first draw honours a reader's earlier close (the key has a version), and a later rise does not: it is a
     new fact the reader has not yet seen the panel hold. */
  useLayoutEffect(() => {
    const before = wasWhen.current;
    wasWhen.current = openWhen;
    if (!openWhen || before === true) return;
    if (before === null && controls.disclosures.version(disclosureKey) !== 0) return;
    controls.disclosures.set(disclosureKey, true);
  }, [openWhen, controls.disclosures, disclosureKey]);
  const triggerRef = useFocusKey<HTMLButtonElement>(controls.focusLane, focusKey ?? null);
  const panelRef = useRevealFragment(disclosureKey);
  return (
    <Accordion
      className={className ? `ctl-disclosure ${className}` : 'ctl-disclosure'}
      data-open={open ? '' : undefined}
      multiple
      value={open ? [disclosureKey] : []}
      onValueChange={(value, detail) => {
        if (detail.reason === 'trigger-press') controls.noteToggle();
        controls.disclosures.set(disclosureKey, value.includes(disclosureKey));
      }}
    >
      <AccordionItem value={disclosureKey}>
        {aside ? (
          <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
            <div className="min-w-0 flex-1">
              <AccordionTrigger
                ref={triggerRef}
                {...(headerProps ? { headerProps } : {})}
                {...(summaryLabel ? { 'aria-label': summaryLabel } : {})}
              >
                {summary}
              </AccordionTrigger>
            </div>
            <div className="flex flex-wrap items-center justify-end gap-1.5">{aside}</div>
          </div>
        ) : (
          <AccordionTrigger
            ref={triggerRef}
            {...(headerProps ? { headerProps } : {})}
            {...(summaryLabel ? { 'aria-label': summaryLabel } : {})}
          >
            {summary}
          </AccordionTrigger>
        )}
        <AccordionContent ref={panelRef} hiddenUntilFound>
          {children}
        </AccordionContent>
      </AccordionItem>
    </Accordion>
  );
}

function DisclosureNode({
  disclosureKey,
  summary,
  className,
  summaryLabel,
  focusKey,
  children,
}: DisclosureProps) {
  const controls = useControls();
  const { open, binding } = useDisclosureState(controls.disclosures, disclosureKey);
  const summaryRef = useFocusKey<HTMLElement>(controls.focusLane, focusKey ?? null);

  const detailsRef = useCallback(
    (node: HTMLDetailsElement) => {
      const detach = binding.attach(node);
      return () => {
        detach();
      };
    },
    [binding],
  );

  const onToggle = (event: SyntheticEvent<HTMLDetailsElement>) => {
    binding.toggle(event.nativeEvent);
  };

  const onSummaryClick = (event: MouseEvent<HTMLElement>) => {
    event.preventDefault();
    controls.noteToggle();
    const details = event.currentTarget.parentElement;
    if (!(details instanceof HTMLDetailsElement)) return;
    const opening = !details.open;
    controls.disclosures.set(disclosureKey, opening);
  };

  return (
    <details
      className={className ? `ctl-menu ${className}` : 'ctl-menu'}
      ref={detailsRef}
      open={open}
      onToggle={onToggle}
    >
      <summary
        ref={summaryRef}
        onClick={onSummaryClick}
        {...(summaryLabel ? { 'aria-label': summaryLabel } : {})}
      >
        {summary}
      </summary>
      {children}
    </details>
  );
}

const PopoverAncestors = createContext<readonly string[]>([]);

function PopoverDisclosure({
  disclosureKey,
  summary,
  className,
  summaryLabel,
  focusKey,
  triggerClassName,
  children,
}: DisclosureProps) {
  const controls = useControls();
  const open = useControlledDisclosureState(controls.disclosures, disclosureKey);
  const focusRef = useFocusKey<HTMLButtonElement>(controls.focusLane, focusKey ?? null);
  const popupRef = useRef<HTMLDivElement>(null);
  const triggerNode = useRef<HTMLButtonElement>(null);
  const [container, setContainer] = useState<HTMLElement | null>(null);
  const triggerId = useId();
  const ancestors = useContext(PopoverAncestors);
  const triggerRef = useCallback(
    (node: HTMLButtonElement | null) => {
      if (!node) return;
      triggerNode.current = node;
      setContainer(node.closest<HTMLElement>('#app, #gallery') ?? node.parentElement);
      const releaseFocus = focusRef(node);
      const releaseEscape = registerPopoverEscape(
        node,
        () => popupRef.current,
        () => controls.disclosures.set(disclosureKey, false),
      );
      return () => {
        releaseEscape();
        releaseFocus?.();
      };
    },
    [controls, disclosureKey, focusRef],
  );
  // Base UI left a departure after window blur open in the Chromium proof.
  // A missing related target is window blur, not a departure within the page.
  const onBlur = (event: FocusEvent<HTMLElement>) => {
    const next = event.relatedTarget;
    if (!(next instanceof Node)) return;
    // Base UI's forward Tab guard is outside the trigger and popup. Nested portals
    // also leave the DOM subtree, so React ancestry supplies their popup owners.
    if (next instanceof Element && next.hasAttribute('data-base-ui-focus-guard')) return;
    const owners =
      next instanceof Element
        ? next.closest('[data-popover-owners]')?.getAttribute('data-popover-owners')?.split(' ')
        : undefined;
    if (owners?.includes(triggerId)) return;
    if (!popupRef.current?.contains(next) && !triggerNode.current?.contains(next))
      controls.disclosures.set(disclosureKey, false);
  };
  return (
    <PopoverAncestors.Provider value={[...ancestors, triggerId]}>
      <Popover
        open={open}
        triggerId={triggerId}
        onOpenChange={(next, detail) => {
          // The document handler chooses one return target for all open popovers.
          if (detail.reason === 'escape-key') {
            detail.cancel();
            return;
          }
          if (detail.reason === 'trigger-press') controls.noteToggle();
          controls.disclosures.set(disclosureKey, next);
          if (!next || detail.reason !== 'trigger-press') return;
          const reduce = controls.reducedMotion();
          requestAnimationFrame(() =>
            requestAnimationFrame(() => {
              if (!controls.disclosures.isOpen(disclosureKey)) return;
              popupRef.current?.scrollIntoView({
                block: 'nearest',
                behavior: reduce ? 'auto' : 'smooth',
              });
            }),
          );
        }}
      >
        <div
          data-slot="popover"
          data-open={open ? '' : undefined}
          className={
            className
              ? `ctl-disclosure ctl-disclosure--pop ${className}`
              : 'ctl-disclosure ctl-disclosure--pop'
          }
        >
          <PopoverTrigger
            id={triggerId}
            ref={triggerRef}
            onBlur={onBlur}
            {...(triggerClassName ? { className: triggerClassName } : {})}
            {...(summaryLabel ? { 'aria-label': summaryLabel } : {})}
          >
            {summary}
          </PopoverTrigger>
        </div>
        {container ? (
          <PopoverContent
            data-popover-owners={ancestors.join(' ')}
            container={container}
            ref={popupRef}
            onBlur={onBlur}
            initialFocus={false}
            finalFocus={false}
            aria-labelledby={triggerId}
          >
            {children}
          </PopoverContent>
        ) : null}
      </Popover>
    </PopoverAncestors.Provider>
  );
}

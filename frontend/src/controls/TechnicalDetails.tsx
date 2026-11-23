import { useSyncExternalStore, type ReactNode } from 'react';
import { GLOSSARY } from '../language/glossary';
import { Icon } from '../ui/icons';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../ui/tabs';
import { Disclosure } from './Disclosure';
import { useControls } from './kit';
import { useControlledDisclosureState } from './useDisclosureState';

interface TechnicalTab {
  readonly id: string;
  readonly label: string;
  readonly content: ReactNode;
}

type Content =
  | { readonly tabs: readonly [TechnicalTab, ...TechnicalTab[]]; readonly children?: never }
  | { readonly tabs?: never; readonly children: ReactNode };

export function TechnicalDetails({
  disclosureKey,
  tabs,
  children,
  caption,
  aside,
  focusKey,
}: Content & {
  readonly disclosureKey: string;
  readonly caption?: string;
  readonly aside?: ReactNode;
  readonly focusKey?: string;
}) {
  const { disclosures, technicalTabs } = useControls();
  const open = useControlledDisclosureState(disclosures, disclosureKey);
  const saved = useSyncExternalStore(technicalTabs.subscribe, () =>
    technicalTabs.read(disclosureKey),
  );
  const selected = tabs?.find((tab) => tab.id === saved)?.id ?? tabs?.[0].id;
  const note = caption ?? tabs?.map((tab) => tab.label).join(', ');
  return (
    <section className="technical-details" aria-label={GLOSSARY.showTechnicalDetails.plain}>
      <Disclosure
        disclosureKey={disclosureKey}
        variant="accordion"
        {...(focusKey ? { focusKey } : {})}
        aside={aside}
        triggerClassName="technical-details-trigger min-h-[60px] w-full flex flex-wrap items-center gap-2 rounded-card border border-dashed border-[var(--line)] bg-[var(--raise)] px-4 py-3 text-body font-semibold text-foreground [&_[data-slot=disclosure-chevron]]:hidden"
        summaryLabel={
          open ? GLOSSARY.hideTechnicalDetails.plain : GLOSSARY.showTechnicalDetails.plain
        }
        summary={
          <>
            <Icon name="details" className="text-primary" />
            <span>
              {open ? GLOSSARY.hideTechnicalDetails.plain : GLOSSARY.showTechnicalDetails.plain}
            </span>
            {note ? (
              <span className="grow text-end text-label font-normal text-muted-foreground">
                {note}
              </span>
            ) : null}
          </>
        }
      >
        <div
          className="mt-2 rounded-card border border-solid border-[var(--rule)] bg-[var(--raise)] px-4 pb-4 [--mono:ui-monospace,monospace]"
          data-layer="technical"
        >
          {tabs ? (
            <Tabs
              value={selected}
              onValueChange={(value) => technicalTabs.remember(disclosureKey, String(value))}
            >
              <TabsList
                aria-label="Technical details"
                activateOnFocus
                className="flex flex-wrap gap-x-4 px-0 [@media(max-width:420px)]:flex [@media(max-width:420px)]:gap-x-4 [@media(max-width:420px)]:gap-y-1 [@media(max-width:420px)]:px-0"
              >
                {tabs.map((tab) => (
                  <TabsTrigger
                    className="min-h-[44px] px-2 aria-selected:border-b-[var(--accent)] aria-selected:font-semibold"
                    key={tab.id}
                    value={tab.id}
                  >
                    {tab.label}
                  </TabsTrigger>
                ))}
              </TabsList>
              {tabs.map((tab) => (
                <TabsContent key={tab.id} value={tab.id} keepMounted>
                  {tab.content}
                </TabsContent>
              ))}
            </Tabs>
          ) : (
            children
          )}
        </div>
      </Disclosure>
    </section>
  );
}

/* shadcn Tabs, Base UI flavour. CLI: shadcn@4.21.4.
   Registry: https://ui.shadcn.com/r/styles/base-nova/tabs.json
   Upstream content SHA-256: 958b817b256cffae986d046168b70dd0153d542b4c521ee8bbdda349010011ef
   MIT; the full upstream notice ships in react-licenses.txt.
   Cockpit selection stays route-owned. Technical details own their inline panels. */
import { Tabs as TabsPrimitive } from '@base-ui/react/tabs';
import { cn } from '@/lib/utils';
import { buttonVariants } from './button';

function Tabs({ className, ...props }: TabsPrimitive.Root.Props) {
  return <TabsPrimitive.Root data-slot="tabs" className={cn('contents', className)} {...props} />;
}
function TabsList({ className, ...props }: TabsPrimitive.List.Props) {
  return (
    <TabsPrimitive.List
      data-slot="tabs-list"
      className={cn(
        'flex gap-[24px] [border-bottom:1px_solid_var(--rule)] px-[12px] py-0 [@media(max-width:420px)]:grid [@media(max-width:420px)]:gap-0 [@media(max-width:420px)]:px-[6px]',
        className,
      )}
      {...props}
    />
  );
}
function TabsTrigger({ className, ...props }: TabsPrimitive.Tab.Props) {
  return (
    <TabsPrimitive.Tab
      data-slot="tabs-trigger"
      className={cn(
        buttonVariants({ variant: 'native' }),
        'mb-[-1px] pt-[12px] px-px pb-[10px] [border-top:0] [border-right:0] [border-left:0] [border-bottom:2px_solid_transparent] rounded-none bg-transparent text-muted-foreground [font-family:var(--sans)] text-body font-normal leading-[normal] cursor-pointer aria-selected:border-b-[var(--ink2)] aria-selected:text-foreground [@media(max-width:420px)]:px-0 [@media(max-width:420px)]:text-label',
        className,
      )}
      {...props}
    />
  );
}
function TabsContent(props: TabsPrimitive.Panel.Props) {
  return <TabsPrimitive.Panel data-slot="tabs-content" {...props} />;
}
export { Tabs, TabsList, TabsTrigger, TabsContent };

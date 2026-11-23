import { clsx, type ClassValue } from 'clsx';
import { extendTailwindMerge } from 'tailwind-merge';
export const TYPE_STEPS = ['label', 'body', 'value', 'head', 'hero'] as const;
export const RADII = ['control', 'card', 'standard-card', 'shell', 'pill'] as const;
const merge = extendTailwindMerge({
  extend: { theme: { text: [...TYPE_STEPS], radius: [...RADII] } },
});
export function cn(...inputs: ClassValue[]) {
  return merge(clsx(inputs));
}

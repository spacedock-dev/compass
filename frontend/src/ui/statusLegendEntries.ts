import { SESSION_ROW_WORDS } from '../language/glossary';
import { SESSION_STATE_ICONS } from './icons';

export const STATUS_LEGEND = [
  ...Object.entries(SESSION_STATE_ICONS),
  [SESSION_ROW_WORDS.worthALook, 'worth-a-look'],
] as const;

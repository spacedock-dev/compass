import { Card } from '../ui/card';
import { useDrift } from './context';
import { missingCites, WORK_AS_REPORTED } from './sentences';
import {
  foldRuns,
  lastTurnLead,
  newestFirst,
  rowWords,
  rowsByNumber,
  workList,
  type CheckRunModel,
} from './workList';
import { EntryHead } from './EntrySource';
import { afterPanelSettles } from './panelSettle';
import { ActivityLegend } from './ActivityMarks';
import { CheckRun } from './CheckRun';
import { TooltipProvider } from '../ui/tooltip';
import { disclosureKey, useControls } from '../controls';
import { useControlledDisclosureState } from '../controls/useDisclosureState';
import { Why } from './Why';
import {
  useEffect,
  useLayoutEffect,
  useRef,
  useSyncExternalStore,
  type KeyboardEvent,
  type ReactNode,
} from 'react';
import { Button } from '../ui/button';
import { contextKey } from '../api/identity';
import { parseFocusedSummary } from '../api/summary';
import { activityStamp, entryWindow, personAuthored, recordPastWindow } from '../intent/work';
import { useDisplayed, useShell } from '../shell/context';
import { ShowMore } from './ShowMore';
import { ACTIVITY_LOG_FILTER_LABELS, GLOSSARY } from '../language/glossary';
import { fullActivityKey, TECHNICAL_EVIDENCE } from '../sessions/fullActivityKey';
import { readingCitationIds } from './citations';
import { summaryCitationIds } from '../sessions/summary';

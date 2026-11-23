import { useCallback } from 'react';
import { BriefingUnavailable } from '../controls/briefingUnavailable';
import { useControls } from '../controls/kit';
import { briefingOf, useProjectModel } from '../project/model';
import type { ProjectRoute } from '../router/grammar';

export function useProjectBriefing(route: ProjectRoute): () => string {
  const model = useProjectModel(route);
  const { memo } = useControls();
  return useCallback(() => {
    if (!model) throw new BriefingUnavailable('This project is no longer on the board.');
    return briefingOf(model, (key) => memo.read(key)).text;
  }, [model, memo]);
}

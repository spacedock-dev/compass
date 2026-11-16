import { describe, expect, it } from 'vitest';
import { locationBoard, locationRow, locationRows } from '../../test/location_boards';
import { observe, type BoardRisk } from '../observed';
import { attentionModel } from './model';
import { riskRow, riskSubject } from './subjects';

describe('location cards agree with their linked members', () => {
  it('shows no warning when a single unknown session is repeated', () => {
    const data = locationBoard(1);
    locationRow(data, 0)['project_identity_source'] = 'collector project label';
    locationRows(data).push({ ...locationRow(data, 0) });
    expect(observe(data).boardRisks).toHaveLength(0);
    expect(attentionModel(data).risk).toHaveLength(0);
  });

  it('counts each identity once and links both distinct unknown members', () => {
    const data = locationBoard(2);
    for (const row of locationRows(data))
      row['project_identity_source'] = 'collector project label';
    locationRows(data).push({ ...locationRow(data, 0) });
    const risks = observe(data).boardRisks;
    expect(risks).toHaveLength(1);
    expect(risks[0]?.nowText).toBe('Location not measured for 2 sessions with this display label');
    expect(riskSubject(risks[0] as BoardRisk, attentionModel(data))?.sessions).toHaveLength(2);
  });

  it('warns about root and subdirectory sessions sharing a measured checkout across labels', () => {
    const data = locationBoard(2);
    for (const row of locationRows(data))
      Object.assign(row, {
        state: 'working',
        project_key: 'git:audits',
        project_identity_source: 'git common directory',
      });
    locationRow(data, 1)['project'] = 'audits/src';
    const risks = observe(data).boardRisks.filter((risk) => risk.kind === 'checkout');
    const model = attentionModel(data);
    expect(risks).toHaveLength(1);
    expect(model.risk.filter((subject) => subject.primaryKind === 'checkout')).toHaveLength(1);
    const card = riskRow(risks[0] as BoardRisk, model, true);
    expect(card.subject?.sessions.map((row) => row['sid'])).toEqual(['audit-0', 'audit-1']);
    expect(card.route).toEqual({ view: 'sessions' });
    expect(risks[0]?.nowText).toBe('2 sessions working or waiting in the same checkout');
  });
});

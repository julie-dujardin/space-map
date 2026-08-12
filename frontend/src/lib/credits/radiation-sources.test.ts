import { describe, it, expect } from 'vitest';
import type { Hazard, HazardKind } from '$lib/travel/hazards';
import { radiationSources } from './radiation-sources';

function hazard(kind: HazardKind, extra: Partial<Hazard> = {}): Hazard {
	return {
		kind,
		severity: 'amber',
		startJd: 2460000,
		endJd: 2460100,
		peakJd: 2460050,
		peak: 1,
		...extra
	} as Hazard;
}

describe('radiationSources', () => {
	it('credits nothing for a trip with no dose row', () => {
		expect(radiationSources([hazard('signal-lag'), hazard('conjunction')])).toEqual([]);
	});

	it('credits the field model and the risk coefficient behind a cruise dose', () => {
		const titles = radiationSources([hazard('radiation')]).map((s) => s.title);
		expect(titles).toHaveLength(4);
		expect(titles.some((t) => t.startsWith('Guo'))).toBe(true);
		expect(titles.some((t) => t.startsWith('ICRP'))).toBe(true);
	});

	it('credits the belt profile and the lethal dose behind a pass in grays', () => {
		const titles = radiationSources([hazard('belt-crossing', { bodyId: 'naif-599' })]).map(
			(s) => s.title
		);
		expect(titles.some((t) => t.startsWith('Miller'))).toBe(true);
		expect(titles.some((t) => t.startsWith('CDC'))).toBe(true);
	});

	it('credits only what establishes the belt when the pass carries no figure', () => {
		const titles = radiationSources([
			hazard('belt-crossing', { bodyId: 'naif-799', unpriced: true })
		]).map((s) => s.title);
		expect(titles).toEqual(['Garrett et al. 2015 (JPL Publication 15-1), Uranus Radiation Model']);
	});

	it('leaves an unpriced pass past an unmodelled belt uncredited', () => {
		expect(
			radiationSources([hazard('belt-crossing', { bodyId: 'naif-399', unpriced: true })])
		).toEqual([]);
	});

	it('credits a work shared by two rows once', () => {
		const sources = radiationSources([
			hazard('radiation'),
			hazard('belt-crossing', { bodyId: 'naif-599' }),
			hazard('belt-crossing', { bodyId: 'naif-599' })
		]);
		expect(new Set(sources.map((s) => s.url)).size).toBe(sources.length);
	});
});

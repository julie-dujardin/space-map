/**
 * Reading a probe's real positions for the planner, for the ends whose conic
 * about their primary describes nothing — see `probe-samples.ts`.
 */

import { describe, it, expect, vi } from 'vitest';
import type { Probe } from '$lib/fetch/position/probes/parse';
import type { ProbeStore } from '$lib/fetch/position/probes/store';

const EARTH_MU = 398600.4355;
const DAY_S = 86400;

vi.mock('$lib/fetch/systems-global', () => ({
	getGmKm3s2: (naif: number) => (naif === 399 ? EARTH_MU : undefined)
}));

// A body sitting 1.45 million km out and drifting at 1 km/day along y — enough
// to tell the units apart, since the kernel wants km/s.
vi.mock('$lib/fetch/position/probes/propagate', () => ({
	probeStateKm: (_probe: Probe, jd: number) => ({
		position: [1447500, jd - 2451545, 0],
		velocity: [0, 1, 0]
	})
}));

const { probeSamples } = await import('./probe-samples');

const NOW = 2451545;

/** A store that holds the probe out to `coverEndJd` and nothing past it. */
function storeOf(coverEndJd: number, fitCenterNaifId = 399): ProbeStore {
	return {
		warmAt: async () => {},
		probeWithCenter: (_id: string, jd: number) =>
			jd <= coverEndJd ? { probe: {} as Probe, fitCenterNaifId } : null
	} as unknown as ProbeStore;
}

describe('probeSamples', () => {
	it('measures from now out to where coverage ends', async () => {
		const samples = (await probeSamples(storeOf(NOW + 100), 'probe-1', 'naif-399', NOW))!;

		expect(samples.centerId).toBe('naif-399');
		expect(samples.jds[0]).toBe(NOW);
		expect(samples.jds.at(-1)).toBe(NOW + 100);
		// Every other day across the covered span.
		expect(samples.jds).toHaveLength(51);
	});

	it('hands the kernel km per second, not per day', async () => {
		const samples = (await probeSamples(storeOf(NOW + 10), 'probe-1', 'naif-399', NOW))!;
		expect(samples.v[0]).toEqual([0, 1 / DAY_S, 0]);
	});

	// Elements about a different centre are a different trip, not a correction.
	it('stops where the probe starts going round something else', async () => {
		expect(await probeSamples(storeOf(NOW + 100, 599), 'probe-1', 'naif-399', NOW)).toBeNull();
	});

	it('answers nothing without a store, a probe, or a known primary', async () => {
		expect(await probeSamples(null, 'probe-1', 'naif-399', NOW)).toBeNull();
		expect(await probeSamples(storeOf(NOW + 100), 'naif-301', 'naif-399', NOW)).toBeNull();
		expect(await probeSamples(storeOf(NOW + 100), 'probe-1', 'naif-599', NOW)).toBeNull();
	});

	// One sample is not a curve, and the kernel would rather have the elements
	// than a series it cannot interpolate.
	it('answers nothing when coverage is too short to interpolate', async () => {
		expect(await probeSamples(storeOf(NOW), 'probe-1', 'naif-399', NOW)).toBeNull();
	});
});

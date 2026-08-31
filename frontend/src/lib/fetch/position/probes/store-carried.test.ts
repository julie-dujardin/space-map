import { describe, it, expect } from 'vitest';
import { ProbeStore, type ProbeZoneParams } from '$lib/fetch/position/probes/store';
import type { Probe } from '$lib/fetch/position/probes/parse';
import type { FetchedProbes } from '$lib/fetch/position/probes/fetch';
import { jdToEt } from '$lib/fetch/position/probes/propagate';

const ZONE = 'probes/interplanetary';
const START_JD = 2450000;
const END_JD = 2450100;

const params: ProbeZoneParams = {
	chunks: 1,
	chunk_days: 100,
	start_jd: START_JD,
	fit_center_naif_id: 10,
	float64_coeffs: true,
	present: [[0, 0]]
} as unknown as ProbeZoneParams;

function probe(id: string): Probe {
	return {
		id,
		probeId: 1,
		hasLocalized: false,
		objectType: 6,
		fitCenter: { id: 'naif-699' },
		subStartEt: [jdToEt(START_JD)],
		subEndEt: [jdToEt(END_JD)],
		subChunks: [{ method: 1 }],
		systemIntervals: [{ startEt: jdToEt(START_JD), endEt: jdToEt(END_JD), systemNaifId: 6 }]
	} as unknown as Probe;
}

/** Seed a parsed chunk straight into the store's cache — `resolve` is what's
 *  under test, not the fetch path that normally fills it. */
function storeWith(...ids: string[]): ProbeStore {
	const store = new ProbeStore(new Map([[ZONE, params]]));
	const chunk: FetchedProbes = {
		startJd: START_JD,
		endJd: END_JD,
		subchunkDays: 100,
		probes: ids.map(probe),
		ids: [...ids]
	};
	(store as unknown as { chunks: Map<string, Map<number, FetchedProbes>> }).chunks.set(
		ZONE,
		new Map([[0, chunk]])
	);
	return store;
}

const CARRIED = {
	id: 'probe-200',
	carriedFrom: { object_id: 'probe-100', start_jd: 2450010, end_jd: 2450050 }
};

describe('ProbeStore passenger emission', () => {
	it("emits the passenger off its carrier's record, alongside the carrier", () => {
		const store = storeWith('probe-100');
		store.registerCarried(CARRIED);
		const out = [...store.probesAt(2450020)];
		// Both: which of the two is drawn is the renderer's per-frame call, and
		// the carrier has to be in the scene to be the one left after separation.
		expect(out.map((e) => e.id).sort()).toEqual(['probe-100', 'probe-200']);
		const passenger = out.find((e) => e.id === 'probe-200');
		// The record is the carrier's: that is where the ephemeris comes from.
		expect(passenger?.probe.id).toBe('probe-100');
	});

	it('leaves the carrier alone outside the ride', () => {
		const store = storeWith('probe-100');
		store.registerCarried(CARRIED);
		expect([...store.probesAt(2450005)].map((e) => e.id)).toEqual(['probe-100']);
	});

	it('stands down once the passenger flies on its own record', () => {
		const store = storeWith('probe-100', 'probe-200');
		store.registerCarried(CARRIED);
		const out = [...store.probesAt(2450020)];
		expect(out.map((e) => e.id).sort()).toEqual(['probe-100', 'probe-200']);
		expect(out.find((e) => e.id === 'probe-200')?.probe.id).toBe('probe-200');
	});

	it('emits nothing extra when the carrier has no record loaded', () => {
		const store = storeWith('probe-999');
		store.registerCarried(CARRIED);
		expect([...store.probesAt(2450020)].map((e) => e.id)).toEqual(['probe-999']);
	});
});

describe('ProbeStore carried-craft fallback', () => {
	it('resolves a passenger to its carrier inside the ride', () => {
		const store = storeWith('probe-100');
		expect(store.probe('probe-200', 2450020)).toBeNull();
		store.registerCarried(CARRIED);
		expect(store.probe('probe-200', 2450020)?.id).toBe('probe-100');
	});

	it('does not resolve before the ride', () => {
		const store = storeWith('probe-100');
		store.registerCarried(CARRIED);
		expect(store.probe('probe-200', 2450005)).toBeNull();
	});

	it('keeps answering through the handover, then stops', () => {
		const store = storeWith('probe-100');
		store.registerCarried(CARRIED);
		expect(store.probe('probe-200', 2450055)?.id).toBe('probe-100');
		expect(store.probe('probe-200', 2450060)).toBeNull();
	});

	it("prefers the passenger's own record where it has one", () => {
		const store = storeWith('probe-100', 'probe-200');
		store.registerCarried(CARRIED);
		expect(store.probe('probe-200', 2450020)?.id).toBe('probe-200');
	});

	it('is null when the carrier itself has no record loaded', () => {
		const store = storeWith('probe-999');
		store.registerCarried(CARRIED);
		expect(store.probe('probe-200', 2450020)).toBeNull();
	});

	// Visibility, focus and the trail all ask these about the focused craft by
	// id. A passenger answering "nowhere" to them is hidden as out-of-system
	// however well its position resolves.
	it('answers the annotation lookups from the carrier too', () => {
		const store = storeWith('probe-100');
		expect(store.containingSystemAt('probe-200', 2450020)).toBeNull();
		expect(store.hasHeliocentricFit('probe-200', 2450020)).toBe(false);
		expect(store.stampedFitCenterAt('probe-200', 2450020)).toBeNull();
		store.registerCarried(CARRIED);
		expect(store.containingSystemAt('probe-200', 2450020)).toBe(6);
		expect(store.hasHeliocentricFit('probe-200', 2450020)).toBe(true);
		expect(store.stampedFitCenterAt('probe-200', 2450020)).toBe('naif-699');
	});

	it('answers the annotation lookups for itself once separated', () => {
		const store = storeWith('probe-100');
		store.registerCarried(CARRIED);
		expect(store.containingSystemAt('probe-200', 2450060)).toBeNull();
		expect(store.hasHeliocentricFit('probe-200', 2450060)).toBe(false);
	});
});

describe('ProbeStore.ridesAt', () => {
	it('reports the ride while the craft is bolted on', () => {
		const store = storeWith('probe-100');
		store.registerCarried(CARRIED);
		expect(store.ridesAt(2450020)).toEqual([
			{ passengerId: 'probe-200', carrierId: 'probe-100', attached: true }
		]);
	});

	it('runs on past separation, uncredited, while the archive has nothing of its own', () => {
		const store = storeWith('probe-100');
		store.registerCarried(CARRIED);
		expect(store.ridesAt(2450055)).toEqual([
			{ passengerId: 'probe-200', carrierId: 'probe-100', attached: false }
		]);
	});

	it("ends the moment the craft's own record answers", () => {
		const store = storeWith('probe-100', 'probe-200');
		store.registerCarried(CARRIED);
		expect(store.ridesAt(2450055)).toEqual([]);
	});

	it('is over once the handover has run out of rope', () => {
		const store = storeWith('probe-100');
		store.registerCarried(CARRIED);
		expect(store.ridesAt(2450060)).toEqual([]);
	});

	it("hands back the carrier's name for the credit line", () => {
		const store = storeWith('probe-100');
		store.registerCarried({ ...CARRIED, carrierName: 'Cassini' });
		expect(store.ridesAt(2450020)[0].carrierName).toBe('Cassini');
	});

	it('reports nothing before the ride starts', () => {
		const store = storeWith('probe-100');
		store.registerCarried(CARRIED);
		expect(store.ridesAt(2450005)).toEqual([]);
	});
});

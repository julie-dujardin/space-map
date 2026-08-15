import { describe, it, expect } from 'vitest';
import type { LandedRecord, Probe } from '$lib/fetch/position/probes/parse';
import type { ProbeStore } from '$lib/fetch/position/probes/store';
import { landedEnd } from './probe-end';

const J2000_ET = 0;
const DAY_S = 86400;

function record(over: Partial<LandedRecord> = {}): LandedRecord {
	return {
		bodyNaifId: 499,
		isStatic: true,
		startEt: J2000_ET,
		endEt: J2000_ET + 100 * DAY_S,
		latRefDeg: -23.9,
		lngRefDeg: -19.4,
		altRefM: 0,
		sampleEt: new Float64Array(),
		sampleLatDeg: new Float32Array(),
		sampleLngDeg: new Float32Array(),
		sampleAltM: new Float32Array(),
		...over
	};
}

/** A store holding one probe, however it is asked for. */
function storeOf(probe: Probe | null): ProbeStore {
	return {
		probeWithCenter: () => (probe ? { probe, fitCenterNaifId: 499 } : null)
	} as unknown as ProbeStore;
}

/** `subEndEt` past the landed phase is what makes a probe fly again. */
function probe(landed: LandedRecord | undefined, subEndEt: number[] = []): Probe {
	return { landed, subEndEt: new Float64Array(subEndEt) } as unknown as Probe;
}

describe('landedEnd', () => {
	const jd = 2451545.0 + 10;

	it('reads the host body and the place off the landed record', () => {
		const end = landedEnd(storeOf(probe(record())), 'probe-1', jd);
		expect(end).toEqual({ hostId: 'naif-499', latDeg: -23.9, lonDeg: -19.4 });
	});

	it('holds the site past the record it stops at, since nothing flies after', () => {
		const past = 2451545.0 + 200;
		expect(landedEnd(storeOf(probe(record())), 'probe-1', past)?.hostId).toBe('naif-499');
	});

	// An ascent stage, a recovered capsule: the probe was there for a window
	// rather than being there, and a trip is planned for whenever the reader likes.
	it('refuses a probe that flies again after its landing', () => {
		const flown = probe(record(), [J2000_ET + 400 * DAY_S]);
		expect(landedEnd(storeOf(flown), 'probe-1', jd)).toBeNull();
	});

	it('refuses a probe with no landed record, and anything that is not a probe', () => {
		expect(landedEnd(storeOf(probe(undefined)), 'probe-1', jd)).toBeNull();
		expect(landedEnd(storeOf(probe(record())), 'naif-499', jd)).toBeNull();
		expect(landedEnd(null, 'probe-1', jd)).toBeNull();
	});
});

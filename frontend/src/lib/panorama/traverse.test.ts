import { describe, expect, it } from 'vitest';
import type { PanoramaEntry } from '$lib/fetch/objects/object-data';
import { bearingDeg, findPanorama, groundDistanceM, neighboursOf, panoramaAt } from './traverse';

const MARS_RADIUS_KM = 3389.5;

function entry(over: Partial<PanoramaEntry>): PanoramaEntry {
	return { id: 'x', time: '2021-02-20T00:00:00Z', lat: 0, lon: 0, north_offset_deg: 0, ...over };
}

describe('panoramaAt', () => {
	it('round-trips through findPanorama', () => {
		const e = entry({ id: 'a', lat: 18.444627146, lon: 77.450885729 });
		expect(findPanorama([entry({ id: 'b', lat: 1 }), e], panoramaAt(e))).toBe(e);
		expect(findPanorama([e], null)).toBeNull();
	});

	it('tells apart two mosaics of one stop', () => {
		// A stop held for days dates every mosaic from the first frame, so time
		// and place alone name several panoramas.
		const first = entry({ id: 'sol59' });
		const second = entry({ id: 'sol93' });
		expect(panoramaAt(first)).not.toBe(panoramaAt(second));
		expect(findPanorama([first, second], panoramaAt(second))).toBe(second);
	});

	it('still resolves a link written with the old time and place key', () => {
		const e = entry({ id: 'a', lat: 18.4, lon: 77.4 });
		expect(findPanorama([e], `${e.time},${e.lat},${e.lon}`)).toBe(e);
	});
});

describe('ground geometry', () => {
	it('measures a step north and its bearing', () => {
		const a = entry({ lat: 18, lon: 77 });
		const b = entry({ lat: 18.001, lon: 77 });
		expect(groundDistanceM(a, b, MARS_RADIUS_KM)).toBeCloseTo(59.16, 1);
		expect(bearingDeg(a, b)).toBeCloseTo(0, 5);
		expect(bearingDeg(b, a)).toBeCloseTo(180, 5);
	});

	it('bears east for a step in longitude', () => {
		expect(bearingDeg(entry({ lat: 0, lon: 10 }), entry({ lat: 0, lon: 11 }))).toBeCloseTo(90, 5);
	});
});

describe('neighboursOf', () => {
	it('steps only within the mission', () => {
		const c = entry({ id: 'c', mission: 'curiosity' });
		const p1 = entry({ id: 'p1', mission: 'perseverance', lat: 18, lon: 77 });
		const p2 = entry({ id: 'p2', mission: 'perseverance', lat: 18.001, lon: 77 });
		const list = [c, p1, p2];
		expect(neighboursOf(list, p1, MARS_RADIUS_KM).previous).toBeNull();
		expect(neighboursOf(list, p1, MARS_RADIUS_KM).next?.entry).toBe(p2);
		expect(neighboursOf(list, p2, MARS_RADIUS_KM).next).toBeNull();
		expect(neighboursOf(list, p2, MARS_RADIUS_KM).previous?.bearingDeg).toBeCloseTo(180, 5);
	});
});

import { describe, it, expect } from 'vitest';
import { planRideMarkers } from '$lib/fetch/position/probes/passenger';
import type { Ride } from '$lib/fetch/position/probes/store';

const RIDE: Ride = {
	passengerId: 'probe-200',
	carrierId: 'probe-100',
	carrierName: 'Cassini',
	attached: true
};

/** No carrier in the scene: the credit falls back to the bundle's spelling. */
const NO_SCENE = () => undefined;

describe('planRideMarkers', () => {
	it('draws the carrier and credits nothing when neither is focused', () => {
		const { hidden, credits } = planRideMarkers([RIDE], 'naif-699', NO_SCENE);
		expect([...hidden]).toEqual(['probe-200']);
		expect(credits.size).toBe(0);
	});

	it('draws the passenger and credits its carrier once it is focused', () => {
		const { hidden, credits } = planRideMarkers([RIDE], 'probe-200', NO_SCENE);
		expect([...hidden]).toEqual(['probe-100']);
		expect(credits.get('probe-200')).toBe('Cassini');
	});

	it('drops the passenger when the carrier is the one focused', () => {
		const { hidden, credits } = planRideMarkers([RIDE], 'probe-100', NO_SCENE);
		expect([...hidden]).toEqual(['probe-200']);
		expect(credits.size).toBe(0);
	});

	// Position and credit part company here: the craft is drawn off the carrier
	// because the archive has nothing else, but it has physically let go.
	it('leaves a craft past separation drawn but uncredited', () => {
		const { hidden, credits } = planRideMarkers(
			[{ ...RIDE, attached: false }],
			'probe-200',
			NO_SCENE
		);
		expect([...hidden]).toEqual(['probe-100']);
		expect(credits.size).toBe(0);
	});

	it("repeats the carrier's own label rather than the bundle's spelling", () => {
		const { credits } = planRideMarkers([RIDE], 'probe-200', () => 'Cassini');
		expect(credits.get('probe-200')).toBe('Cassini');
	});

	it('hides nobody when no ride is live', () => {
		const { hidden, credits } = planRideMarkers([], 'probe-200', NO_SCENE);
		expect(hidden.size).toBe(0);
		expect(credits.size).toBe(0);
	});
});

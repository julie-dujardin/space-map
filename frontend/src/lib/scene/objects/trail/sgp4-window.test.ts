import { describe, expect, it } from 'vitest';
import type { Line } from 'three';
import type { PositionedBody } from '$lib/types/objects';
import { ObjectType } from '$lib/types/objects';
import { buildSatrec, sgp4PositionScene } from '$lib/math/orbit/sgp4';
import { makeTrail } from './builder';
import { NUM_TRAIL_POINTS } from './points';
import { refreshTrail } from './refresh';

const EPOCH_JD = 2461320.5;
const BASIS: [number, number, number] = [0, 0, 0];

/** Mean motion in rev/day and eccentricity, from low orbit to a Molniya orbit. */
const ORBITS: [string, number, number][] = [
	['low orbit', 15.5, 0.0005],
	['GPS', 2.0056, 0.01],
	['geostationary', 1.0027, 0.0002],
	['Molniya', 2.006, 0.72]
];

function satellite(meanMotion: number, eccentricity: number) {
	const satrec = buildSatrec({
		noradCatId: 25544,
		epochJd: EPOCH_JD,
		meanMotion,
		eccentricity,
		inclination: 51.64,
		raOfAscNode: 100,
		argOfPericenter: 80,
		meanAnomaly: 10,
		bstar: 1e-4,
		meanMotionDot: 0,
		meanMotionDdot: 0,
		elementSetNo: 1,
		revAtEpoch: 1
	})!;
	const body = {
		data: { satrec, n: meanMotion * 360, objectType: ObjectType.SPACECRAFT },
		position: sgp4PositionScene(satrec, EPOCH_JD + 1)
	};
	const place = (jd: number) => {
		body.position = sgp4PositionScene(satrec, jd);
	};
	return { body: body as unknown as PositionedBody, place };
}

/** Dot product of the first two segments of the trail. Negative: the trail
 *  leaves the body forward and turns back. */
function firstTurn(line: Line): number {
	const p = line.geometry.getAttribute('position').array;
	return (
		(p[3] - p[0]) * (p[6] - p[3]) + (p[4] - p[1]) * (p[7] - p[4]) + (p[5] - p[2]) * (p[8] - p[5])
	);
}

describe.each(ORBITS)('SGP4 trail of a %s satellite', (_name, meanMotion, eccentricity) => {
	const stepDays = 1 / meanMotion / NUM_TRAIL_POINTS;

	it.each([1, -1])('keeps the full window between two slides (direction %i)', (direction) => {
		const { body, place } = satellite(meanMotion, eccentricity);
		const jd0 = EPOCH_JD + 1;
		const line = makeTrail(body, '#fff', BASIS, jd0) as Line;
		expect(line.geometry.drawRange.count).toBe(NUM_TRAIL_POINTS);
		const curve = line.userData.sourceCurve;
		for (let f = 0.05; f < 1; f += 0.05) {
			const jd = jd0 + direction * f * stepDays;
			place(jd);
			refreshTrail(body, line, BASIS, jd);
			expect(line.userData.sourceCurve).toBe(curve);
			expect(line.geometry.drawRange.count).toBe(NUM_TRAIL_POINTS);
			expect(firstTurn(line)).toBeGreaterThan(0);
		}
	});

	it('slides the window after one sample step', () => {
		const { body, place } = satellite(meanMotion, eccentricity);
		const jd0 = EPOCH_JD + 1;
		const line = makeTrail(body, '#fff', BASIS, jd0) as Line;
		const curve = line.userData.sourceCurve;
		const jd = jd0 + 1.01 * stepDays;
		place(jd);
		refreshTrail(body, line, BASIS, jd);
		expect(line.userData.sourceCurve).not.toBe(curve);
		expect(line.geometry.drawRange.count).toBe(NUM_TRAIL_POINTS);
	});
});

import type { OrbitalElements } from '$lib/types/objects';
import fixtures from './elements.fixtures.json';

export { fixtures };

const AU_SCALE = 10;

export function toElements(f: (typeof fixtures)[keyof typeof fixtures]): OrbitalElements {
	return { a: f.a, e: f.e, i: f.i, om: f.om, w: f.w, ma: f.ma, n: f.n, epoch: f.epoch };
}

export function sceneDistances(pts: [number, number, number][]): number[] {
	return pts.map((p) => Math.sqrt(p[0] ** 2 + p[1] ** 2 + p[2] ** 2) / AU_SCALE);
}

export function maxGapRatio(pts: [number, number, number][]): number {
	const gaps: number[] = [];
	for (let i = 1; i < pts.length; i++) {
		gaps.push(
			Math.sqrt(
				(pts[i][0] - pts[i - 1][0]) ** 2 +
					(pts[i][1] - pts[i - 1][1]) ** 2 +
					(pts[i][2] - pts[i - 1][2]) ** 2
			)
		);
	}
	const mean = gaps.reduce((a, b) => a + b, 0) / gaps.length;
	return Math.max(...gaps) / mean;
}

export const EMB = toElements(fixtures.earthMoonBarycenter);
export const CERES = toElements(fixtures.ceres);
export const CHIRON = toElements(fixtures.chiron);
export const ERIS = toElements(fixtures.eris);
export const HALLEY = toElements(fixtures.halley);
export const MRKOS = toElements(fixtures.mrkos);
export const A2020H9 = toElements(fixtures.a2020h9);
export const CATALINA_HYP = toElements(fixtures.catalinaHyperbolic);
export const NEAR_CIRC = toElements(fixtures.nearCircularAsteroid);
export const PHOBOS = toElements(fixtures.phobos);

export const ELLIPTIC_ORBITS = [
	{ name: 'Earth-Moon Barycenter', el: EMB },
	{ name: 'Ceres', el: CERES },
	{ name: 'Chiron', el: CHIRON },
	{ name: 'Eris', el: ERIS },
	{ name: 'Halley', el: HALLEY },
	{ name: 'Mrkos', el: MRKOS },
	{ name: '2015 KK487', el: NEAR_CIRC },
	{ name: 'Phobos', el: PHOBOS }
];

/** A synthetic parabolic orbit (e=1, q-based). */
export const SYNTHETIC_PARABOLIC: OrbitalElements = {
	a: 0,
	e: 1.0,
	i: 45.0,
	om: 90.0,
	w: 180.0,
	ma: 0,
	n: 0,
	epoch: 2451545.0,
	q: 1.5,
	tp: 2451545.0
};

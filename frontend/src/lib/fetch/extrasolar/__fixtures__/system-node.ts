/**
 * Test-only System rows as the reader gives them, and a star system of three
 * stars: AB and C, with planets on B and on C.
 */

import type { StarSystem } from '$lib/state/star-system';
import type { Planet } from '../planets';
import type { HeldStarValues, PairOrbit, SystemMember, SystemNode } from '../systems';

export function member(id: number | null, values: Partial<SystemMember> = {}): SystemMember {
	return {
		id,
		kind: 'star',
		letter: null,
		inner: null,
		label: null,
		source: null,
		spectralType: null,
		vMag: null,
		gMag: null,
		mass: null,
		separation: null,
		positionAngle: null,
		period: null,
		eccentricity: null,
		semiMajorAxis: null,
		known: [],
		ids: [],
		...values
	};
}

export function systemNodeOf(id: number, values: Partial<SystemNode> = {}): SystemNode {
	return {
		id,
		point: false,
		depth: 0,
		stars: 2,
		ra: null,
		dec: null,
		label: null,
		spectralType: null,
		evidence: null,
		sources: [],
		treeSource: 'star-systems',
		parent: null,
		root: id,
		primary: null,
		distance: null,
		members: [],
		tree: null,
		orbit: null,
		star: null,
		paperRadius: false,
		radiusPapers: [],
		...values
	};
}

export function pairOrbit(values: Partial<PairOrbit> = {}): PairOrbit {
	return {
		a: 0.22431,
		e: 0.15944,
		i: 90,
		om: 0,
		w: 0,
		ma: 0,
		n: 8.8,
		epoch: 2455212.12316,
		phase: 'periastron',
		period: 41.07922,
		semiMajorAxis: 0.22431,
		semiMajorAxisArcsec: null,
		eccentricity: 0.15944,
		inclination: 90.30401,
		node: 8.19913,
		nodeAscending: true,
		argPeriastron: 83.464,
		periastronTime: 2455190.5693497015,
		barycentre: 0.227,
		centre: 'barycentre',
		massRatioSource: 'literature',
		periodSource: 'literature',
		semiMajorAxisSource: 'literature',
		eccentricitySource: 'literature',
		inclinationSource: 'literature',
		nodeSource: 'gaia-dr3-orbits',
		argPeriastronSource: 'literature',
		epochSource: 'literature',
		assumed: [],
		computed: [],
		references: [
			{
				source: 'literature',
				reference: 'doyle_2011',
				short: 'Doyle et al. 2011',
				title: 'Kepler-16: A Transiting Circumbinary Planet (Science 333, 1602)',
				url: 'https://doi.org/10.1126/science.1210923'
			}
		],
		...values
	};
}

export function heldValues(values: Partial<HeldStarValues> = {}): HeldStarValues {
	return {
		mass: 0.6897,
		teff: 4450,
		spectralType: 'K',
		massSource: 'literature',
		radiusSource: 'literature',
		hostRadiusError: null,
		teffSource: 'literature',
		spectralTypeSource: 'open-exoplanet-catalogue',
		references: pairOrbit().references,
		dominant: false,
		...values
	};
}

export const ROOT = 100;
export const AB = 101;
export const A = 201;
export const B = 202;
export const C = 203;

const planet = (host: number, number: number) => ({ host, number }) as Planet;

/** The root holds AB and C. AB holds A and B. */
export function threeStars(): StarSystem {
	const root = systemNodeOf(ROOT, {
		stars: 3,
		label: 'AB,C',
		members: [
			member(AB, { kind: 'system', letter: 'AB' }),
			member(C, { letter: 'C', spectralType: 'M5.5Ve', mass: 0.12, separation: 7860 })
		]
	});
	const ab = systemNodeOf(AB, {
		root: ROOT,
		parent: ROOT,
		depth: 1,
		label: 'AB',
		members: [member(A, { letter: 'A' }), member(B, { letter: 'B' })]
	});
	return {
		root,
		name: 'Alpha Centauri',
		nodes: new Map([
			[ROOT, root],
			[AB, ab]
		]),
		names: new Map([
			[ROOT, 'Alpha Centauri'],
			[AB, 'Alpha Centauri AB'],
			[A, 'Rigil Kentaurus'],
			[B, 'Toliman'],
			[C, 'Proxima Centauri']
		]),
		planets: new Map([
			[C, [planet(C, 1), planet(C, 2)]],
			[B, [planet(B, 1)]]
		])
	};
}

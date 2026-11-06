import { describe, expect, it } from 'vitest';
import { inSceneCredits } from '$lib/fetch/extrasolar/files';
import {
	columnBetween,
	densityAt,
	nestCredits,
	treeToNest,
	type Mat3Rows,
	type NestLevel,
	type NestMetadata
} from './nest';
import type { Vec3 } from './octahedral';

/** The rows of `rotation_to_icrs` in the metadata of the open nest. */
const ROTATION: Mat3Rows = [
	[-0.0548756577, 0.4941094372, -0.8676661376],
	[-0.873437052, -0.4448297212, -0.1980763373],
	[-0.4838350736, 0.746982184, 0.4559838137]
];

const FLOOR = 1e-6;
const SPAN = Math.log1p(0.1 / FLOOR);
const codeFor = (density: number) => (Math.log1p(density / FLOOR) / SPAN) * 255;

/** A level of one density, with a box of half extent `half`. */
function flatLevel(half: Vec3, density: number): NestLevel {
	const size: Vec3 = [8, 8, 8];
	return {
		half,
		floor: FLOOR,
		span: SPAN,
		size,
		codes: new Uint8Array(512).fill(Math.round(codeFor(density)))
	};
}

const decoded = (density: number) =>
	FLOOR * Math.expm1((Math.round(codeFor(density)) / 255) * SPAN);

describe('tree to nest axes', () => {
	it('takes the Galactic centre direction to +x', () => {
		// Sgr A*: RA 266.405°, Dec -28.936°.
		const ra = (266.405 * Math.PI) / 180;
		const dec = (-28.936 * Math.PI) / 180;
		const icrs: Vec3 = [Math.cos(dec) * Math.cos(ra), Math.cos(dec) * Math.sin(ra), Math.sin(dec)];
		const nest = treeToNest(ROTATION, icrs);
		expect(nest[0]).toBeGreaterThan(0.9999);
		expect(Math.abs(nest[1])).toBeLessThan(0.002);
		expect(Math.abs(nest[2])).toBeLessThan(0.002);
	});

	it('takes the north Galactic pole to +z', () => {
		// RA 192.8595°, Dec 27.1284°, J2000.
		const ra = (192.8595 * Math.PI) / 180;
		const dec = (27.1284 * Math.PI) / 180;
		const nest = treeToNest(ROTATION, [
			Math.cos(dec) * Math.cos(ra),
			Math.cos(dec) * Math.sin(ra),
			Math.sin(dec)
		]);
		expect(nest[2]).toBeGreaterThan(0.99999);
	});

	it('keeps lengths', () => {
		const v = treeToNest(ROTATION, [3, 4, 12]);
		expect(Math.hypot(...v)).toBeCloseTo(13, 6);
	});
});

describe('density', () => {
	const coarse = flatLevel([20_000, 20_000, 2_000], 1e-4);
	const fine = flatLevel([250, 250, 250], 1e-2);
	const levels = [coarse, fine];

	it('reads the finest level that holds a point', () => {
		expect(densityAt(levels, 10, 10, 10)).toBeCloseTo(decoded(1e-2), 8);
		expect(densityAt(levels, 1_000, 0, 0)).toBeCloseTo(decoded(1e-4), 8);
	});

	it('reads nothing outside every box', () => {
		expect(densityAt(levels, 0, 0, 2_500)).toBe(0);
	});

	it('filters the codes before the decode', () => {
		const level = flatLevel([4, 4, 4], 0);
		level.codes[3 + 8 * 3 + 64 * 3] = 200;
		level.codes[4 + 8 * 3 + 64 * 3] = 100;
		// Halfway between two voxel centres on x, on the centre of y and z.
		const value = densityAt([level], 0, -0.5, -0.5);
		expect(value).toBeCloseTo(FLOOR * Math.expm1((150 / 255) * SPAN), 10);
	});
});

describe('column', () => {
	it('sums a flat density along the ray', () => {
		const level = flatLevel([20_000, 20_000, 3_000], 1e-3);
		const sum = columnBetween([level], [0, 0, 0], [1_000, 0, 0]);
		// The midpoint rule on steps of the log reads 0.04% low.
		expect(sum / (decoded(1e-3) * 1_000)).toBeCloseTo(1, 3);
	});

	it('gives the same value to the last bit for the same two points', () => {
		const level = flatLevel([20_000, 20_000, 3_000], 1e-3);
		const a: Vec3 = [10, 20, 30];
		const b: Vec3 = [400, -300, 50];
		expect(columnBetween([level], a, b)).toBe(columnBetween([level], a, b));
	});

	it('skips the empty road to the box', () => {
		const level = flatLevel([20_000, 20_000, 3_000], 1e-3);
		const sum = columnBetween([level], [0, 0, 8_000], [0, 0, 0]);
		expect(sum / (decoded(1e-3) * 3_000)).toBeCloseTo(1, 3);
	});

	it('holds no dust on a ray that misses the box', () => {
		const level = flatLevel([20_000, 20_000, 3_000], 1e-3);
		expect(columnBetween([level], [0, 0, 8_000], [0, 0, 9_000])).toBe(0);
	});
});

describe('credits', () => {
	const credit = (key: string, citation: string, attribution?: string) => ({
		key,
		name: `${key} map`,
		citation,
		source: `https://example.org/${key}`,
		attribution,
		license: null,
		distribution: 'open'
	});
	const meta = {
		credits: [
			credit('paper', 'Edenhofer et al. 2024, arXiv:2308.01295'),
			credit('asks', 'Planck Collaboration XI 2014, doi:10.1051', 'Based on observations.'),
			credit('commas', 'Zhang, Green & Rix 2023, MNRAS 524, 1855')
		]
	} as unknown as NestMetadata;

	it('keeps a map cited as a paper off the credit bar', () => {
		const [paper] = nestCredits(meta);
		expect(paper.organisation).toBe('Edenhofer et al. 2024');
		expect(inSceneCredits(paper)).toBe(false);
	});

	it('reads a citation with commas in its author list to the year', () => {
		const commas = nestCredits(meta)[2];
		expect(commas.organisation).toBe('Zhang, Green & Rix 2023');
		expect(inSceneCredits(commas)).toBe(false);
	});

	it('keeps a source that asks for its attribution on the bar', () => {
		const [, asks] = nestCredits(meta);
		expect(asks.attribution).toBe('Based on observations.');
		expect(inSceneCredits(asks)).toBe(true);
	});
});

import { describe, expect, it } from 'vitest';
import { EARTH_OBLIQUITY_DEG } from '$lib/math/units';
import { temeToEcliptic, temeToEclipticMatrix } from './teme';

/** Rx(ε₀) · pmat76ᵀ · numat(obl80, nut80)ᵀ · R3(−Δψ·cos ε) from pyerfa, with the
 *  full 106-term nutation series. */
const ERFA: { jd: number; m: number[] }[] = [
	{
		jd: 2444239.5,
		m: [
			0.9999880805224708, -0.004472445355330471, -0.0019585825301933852, 0.004882467006393628,
			0.9174881117219571, 0.39773323517756093, 1.8136026948297977e-5, -0.3977380571197847,
			0.9174990123099117
		]
	},
	{
		jd: 2453101.82741,
		m: [
			0.9999994695092815, 0.0009531356217478676, 0.0003905299501648391, -0.0010298279890323162,
			0.9174674617934994, 0.39780949712708846, 2.0867880249357273e-5, -0.3978096882715159,
			0.9174679566512668
		]
	},
	{
		jd: 2461327.5,
		m: [
			0.9999786358263236, 0.00598948649319984, 0.0026180035279906463, -0.00653662917113411,
			0.9174469748017889, 0.39780437517217526, -1.9235484745883775e-5, -0.39781298932864595,
			0.917466525357412
		]
	},
	{
		jd: 2467796.5,
		m: [
			0.9999411013777258, 0.009950634855897467, 0.0043334329884452474, -0.010853270343573891,
			0.9174119721208738, 0.3977907489272951, -1.7272812353704856e-5, -0.3978143515199692,
			0.9174659347498394
		]
	}
];

describe('temeToEclipticMatrix', () => {
	it('matches the full IAU 1976/1980 model within 0.1″', () => {
		for (const { jd, m } of ERFA) {
			const got = temeToEclipticMatrix(jd);
			for (let k = 0; k < 9; k++) expect(Math.abs(got[k] - m[k])).toBeLessThan(5e-7);
		}
	});

	it("reproduces Vallado's TEME → J2000 example within 20 m", () => {
		// Vallado et al. 2006, AIAA 2006-6753: 2004-04-06 07:51:28.386 UTC.
		const jd = 2453101.82741;
		const [x, y, z] = temeToEcliptic(5094.1801621, 6127.6446595, 6380.3445327, jd);
		const eps = (EARTH_OBLIQUITY_DEG * Math.PI) / 180;
		const j2000 = [5102.5096, 6123.01152, 6378.1363];
		const want = [
			j2000[0],
			j2000[1] * Math.cos(eps) + j2000[2] * Math.sin(eps),
			-j2000[1] * Math.sin(eps) + j2000[2] * Math.cos(eps)
		];
		expect(Math.hypot(x - want[0], y - want[1], z - want[2])).toBeLessThan(0.02);
	});
});

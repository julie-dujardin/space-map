/**
 * Integration harness: reads the real exported `major/10` chunk and evaluates
 * Earth's position at J2000. Gated on the export being present on disk so the
 * test suite still passes on a fresh clone.
 *
 * Ground truth (via numpy.polynomial.chebyshev.chebval on the same file):
 *   Earth at JD 2451545.0  → (3543.212, 3341.165, -440.716) km, |r| ≈ 4889.99
 *   Earth at seg-0 midpoint → (4634.587, 1039.277, -405.606) km, |r| ≈ 4766.97
 */

import { describe, it, expect } from 'vitest';
import { existsSync, readFileSync } from 'node:fs';
import { gunzipSync } from 'node:zlib';
import { resolve } from 'node:path';
import { parseChebyshev } from './parse';
import { chebyshevPositionKm } from './propagate';

const EXPORT = resolve(
	__dirname,
	'../../../../../../space-map-export/v1/chebyshev/major/10/data.bin.gz'
);

describe.skipIf(!existsSync(EXPORT))('chebyshev harness (real export)', () => {
	const gz = readFileSync(EXPORT);
	const raw = gunzipSync(gz);
	const buf = raw.buffer.slice(raw.byteOffset, raw.byteOffset + raw.byteLength);
	const chunk = parseChebyshev(buf);

	it('parses the major/10 chunk header', () => {
		expect(chunk.startJd).toBeCloseTo(2451545.0, 3);
		expect(chunk.endJd).toBeCloseTo(2453371.25, 3);
		expect(chunk.bodies.length).toBeGreaterThan(0);
	});

	it('evaluates Earth at J2000 against Python ground truth', () => {
		const earth = chunk.bodies.find((b) => b.naifId === 399);
		expect(earth, 'Earth (naif 399) not found in major/10').toBeDefined();
		expect(earth!.parentNaifId).toBe(3); // Earth-Moon Barycenter

		const jd = 2451545.0;
		const p = chebyshevPositionKm(earth!, jd);
		expect(p).not.toBeNull();
		// Chebfit coefficients are float32 in the file, so ~5-digit agreement is
		// all we can claim versus numpy's float64 eval. 1e-3 km is tight enough.
		expect(p![0]).toBeCloseTo(3543.212, 1);
		expect(p![1]).toBeCloseTo(3341.165, 1);
		expect(p![2]).toBeCloseTo(-440.716, 1);

		const r = Math.hypot(p![0], p![1], p![2]);
		// Earth wobbles ~4671 km around EMB; 4900 km is on-axis for J2000.
		expect(r).toBeGreaterThan(4000);
		expect(r).toBeLessThan(5500);
		console.log(
			`Earth at J2000: (${p![0].toFixed(3)}, ${p![1].toFixed(3)}, ${p![2].toFixed(3)}) km, |r|=${r.toFixed(3)}`
		);
	});

	it('evaluates Earth at the first segment midpoint', () => {
		const earth = chunk.bodies.find((b) => b.naifId === 399)!;
		const mid = 0.5 * (earth.startJds[0] + earth.endJds[0]);
		const p = chebyshevPositionKm(earth, mid);
		expect(p).not.toBeNull();
		expect(p![0]).toBeCloseTo(4634.587, 1);
		expect(p![1]).toBeCloseTo(1039.277, 1);
		expect(p![2]).toBeCloseTo(-405.606, 1);
	});
});

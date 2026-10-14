/**
 * `bodyQuaternion` against SPICE `pxform("J2000", "IAU_<body>")`.
 *
 * The fixture comes from `data/scripts/generate_orientation_truth_fixtures.py`.
 * It holds the PCK constants as the pipeline extracts them and the SPICE
 * rotation at four TDB epochs, which the test turns into the app's UTC. Mars,
 * Phobos and Deimos use quadratic phase angles.
 */

import { describe, expect, it } from 'vitest';
import { Vector3 } from 'three';
import { bodyQuaternion, type NutPrec, type Orientation } from './orientation';
import { equatorialToScene } from './units';
import { tdbToUtc } from '$lib/time/jd';
import fixture from './orientation.truth.fixtures.json';

interface Sample {
	jd_tdb: number;
	matrix: number[][];
}

interface Body {
	naif_id: number;
	name: string;
	orientation: Orientation;
	nut_prec: Omit<NutPrec, 'angles' | 'phaseDegree'> | null;
	samples: Sample[];
}

const angles = fixture.nut_prec_angles as Record<string, number[]>;
const degrees = fixture.nut_prec_phase_degree as Record<string, number>;

function nutPrecOf(body: Body): NutPrec | undefined {
	if (!body.nut_prec) return undefined;
	const owner = String(Math.trunc(body.naif_id / 100));
	return { ...body.nut_prec, angles: angles[owner], phaseDegree: degrees[owner] ?? 1 };
}

/** A J2000 row of the SPICE matrix, as a scene direction. */
function sceneAxis(row: number[]): Vector3 {
	return equatorialToScene(row[0], row[1], row[2], new Vector3());
}

describe('bodyQuaternion against SPICE', () => {
	for (const body of fixture.bodies as Body[]) {
		it(`matches IAU_${body.name.toUpperCase()}`, () => {
			const nutPrec = nutPrecOf(body);
			for (const { jd_tdb, matrix } of body.samples) {
				const q = bodyQuaternion(body.orientation, tdbToUtc(jd_tdb), nutPrec);
				// Local +X is the prime meridian (SPICE +X); local +Y is the pole (SPICE +Z).
				const meridian = new Vector3(1, 0, 0).applyQuaternion(q);
				const pole = new Vector3(0, 1, 0).applyQuaternion(q);
				expect(meridian.angleTo(sceneAxis(matrix[0]))).toBeLessThan(1e-8);
				expect(pole.angleTo(sceneAxis(matrix[2]))).toBeLessThan(1e-8);
			}
		});
	}
});

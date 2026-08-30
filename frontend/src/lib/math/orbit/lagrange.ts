/** Sun–Earth Lagrange points (`class-EL1`/`class-EL2`). Zone membership comes
 *  from the export (probe event targets); this module only does the sim-time
 *  geometry that picks the rotating trail frame. */
export type LagrangePoint = 'EL1' | 'EL2';

export const LAGRANGE_CLASS_NAMES: ReadonlySet<LagrangePoint> = new Set(['EL1', 'EL2']);

export function isLagrangeClass(className: string): boolean {
	return (LAGRANGE_CLASS_NAMES as ReadonlySet<string>).has(className);
}

/** Earth/Sun mass ratio. The collinear L-points sit at R·cbrt(ratio/3) ≈ 0.01 R
 *  from Earth along the Sun line (R = Sun–Earth distance). */
const EARTH_SUN_MASS_RATIO = 3.0034e-6;

// "At" an L-point = on the Sun axis within these fractions of r_L. Loose enough
// for the wide SOHO/JWST/DSCOVR halos, tight enough to reject cruising probes.
const ALONG_MIN = 0.45;
const ALONG_MAX = 1.6;
const OFF_AXIS_MAX = 0.85;

type Vec3 = readonly [number, number, number];
const dot = (a: Vec3, b: Vec3) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const mag = (a: Vec3) => Math.hypot(a[0], a[1], a[2]);

/** Classify an Earth-relative position as Sun–Earth L1/L2, else null. `geocentric`
 *  and `earthToSun` must share frame & units (scene units work — the test is
 *  scale-invariant). */
export function classifyLagrange(
	geocentric: Vec3,
	earthToSun: Vec3,
	massRatio = EARTH_SUN_MASS_RATIO
): LagrangePoint | null {
	const r = mag(earthToSun);
	if (!(r > 0)) return null;
	const rL = r * Math.cbrt(massRatio / 3);
	const along = dot(geocentric, earthToSun) / r; // signed; sunward positive
	const d = mag(geocentric);
	const offAxis = Math.sqrt(Math.max(0, d * d - along * along));
	if (offAxis > OFF_AXIS_MAX * rL) return null;
	const frac = along / rL;
	if (frac >= ALONG_MIN && frac <= ALONG_MAX) return 'EL1';
	if (frac <= -ALONG_MIN && frac >= -ALONG_MAX) return 'EL2';
	return null;
}

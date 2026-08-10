/**
 * A drive held under gravity: integrating the arc instead of assuming it away.
 *
 * The straight-line brachistochrone is only honest while the drive dwarfs the
 * primary's pull. It does, for the burns of a torch ship — but not for a coast,
 * where the drive is off and the pull is the only thing shaping the path, and
 * not for a slow drive at all. Measured against a real integration, a crossing
 * that coasted for a month left the line it was drawn on by a tenth of its own
 * length.
 *
 * So the arc is flown rather than assumed. The ship leaves co-moving with the
 * departure body — which is what clearing the well at zero excess speed leaves
 * it doing, so this agrees with how the two ends are priced — and from there the
 * only forces are the primary's gravity and the drive.
 *
 * **Steering.** The drive points along one fixed inertial direction while
 * boosting and exactly against it while braking, so its net Δv over a flip is
 * zero. That keeps the model's original premise — the ship arrives still
 * carrying the departure body's motion and pays an ordinary capture for the
 * difference — but now as a *result* of the integration rather than as
 * bookkeeping laid over a straight line. It is not the optimal steering law;
 * it is the one a ship that flips once actually flies.
 *
 * **The solve is square.** Three unknowns — where the drive points, as two
 * offsets from the chord, and how long each burn lasts — against the three
 * components of "be where the target is when you get there". Newton on a
 * numerical Jacobian, seeded from the straight-line answer, which is close
 * enough to converge from for any drive worth offering this to. Arrival
 * *velocity* is not constrained: it falls out, and paying for it is the arrival
 * model's job.
 *
 * A drive too weak to close the geometry gets no arc. That is the honest answer
 * — a ship that cannot outpush the Sun does not fly a brachistochrone, it
 * spirals — and it is why this returns null rather than a plausible number.
 */

import type { StateVector } from './state';
import { add, cross, norm, normalize, scale, sub, type Vec3 } from './vec3';
import { propagateFull } from './propagate';
import { SEC_PER_DAY } from './constants';

/** Where the destination is at a moment, in the frame the arc is flown in. */
export type Ephemeris = (jd: number) => StateVector | null;

/** The stretches an arc is made of, in flight order. */
export type HeldDrivePhase = 'boost' | 'cruise' | 'brake';

export interface HeldDriveArc {
	/** Seconds under thrust in each burn — both are the same length. */
	burnSeconds: number;
	/** Seconds with the drive off between them. */
	coastSeconds: number;
	totalSeconds: number;
	/** False for a flyby, which never slows down and so never flips. */
	flips: boolean;
	/** Unit vector the drive points along while boosting; braking reverses it. */
	thrustDir: Vec3;
	/** The ship's own velocity where it meets the target, km/s in the frame. */
	arrivalVelocity: Vec3;
	/** Fastest it is going anywhere on the arc, km/s in the frame. Not the Δv the
	 *  drive spent: gravity and the departure body's own motion are in this. */
	peakSpeedKms: number;
}

/**
 * Steps each burn is integrated in while solving.
 *
 * The field a burn crosses is smooth and the thrust is constant, so RK4 is far
 * more accurate here than the ephemerides it is aimed at. Two hundred is chosen
 * against halving the step, not against a tolerance: past this the answer stops
 * moving in metres.
 */
const BURN_STEPS = 200;

/** Newton's own limits. A converged solve takes four or five of these. */
const NEWTON_STEPS = 40;
/** Halvings of a Newton step that made things worse before giving up on it. */
const DAMPING_STEPS = 12;
/**
 * How close counts as arrived, as a fraction of the crossing. The ends are
 * placed by mean elements, so anything past this is answering to a precision
 * the ephemeris never had.
 */
const CLOSE_ENOUGH = 1e-9;

/**
 * Fractions of the primary's pull the solve is walked up through when the full
 * problem will not converge from the straight-line seed.
 *
 * Each step's answer seeds the next, so gravity is introduced gradually to a
 * solution that already exists. This is what rescues the slower drives, where
 * the straight line is too poor a guess to start from.
 */
const CONTINUATION = [0.2, 0.4, 0.6, 0.8, 1];

/** Gravity at `r`, km/s². */
function pull(r: Vec3, mu: number): Vec3 {
	const d = norm(r);
	if (!(d > 0)) return [0, 0, 0];
	return scale(r, -mu / (d * d * d));
}

/** Sees every state the arc passes through, with seconds since departure. */
type Watcher = (kind: HeldDrivePhase, r: Vec3, v: Vec3, elapsed: number) => void;

/**
 * One burn, integrated with RK4. `thrust` is the drive's acceleration vector,
 * km/s², held for the whole stretch.
 */
function flyBurn(
	start: { r: Vec3; v: Vec3 },
	seconds: number,
	mu: number,
	thrust: Vec3,
	steps: number,
	kind: HeldDrivePhase,
	since: number,
	watch: Watcher
): { r: Vec3; v: Vec3 } {
	const h = seconds / steps;
	let r = start.r;
	let v = start.v;
	const accel = (p: Vec3): Vec3 => add(pull(p, mu), thrust);

	for (let i = 0; i < steps; i++) {
		const a1 = accel(r);
		const r2 = add(r, scale(v, h / 2));
		const v2 = add(v, scale(a1, h / 2));
		const a2 = accel(r2);
		const r3 = add(r, scale(v2, h / 2));
		const v3 = add(v, scale(a2, h / 2));
		const a3 = accel(r3);
		const r4 = add(r, scale(v3, h));
		const v4 = add(v, scale(a3, h));
		const a4 = accel(r4);

		r = add(r, scale(add(add(v, scale(v2, 2)), add(scale(v3, 2), v4)), h / 6));
		v = add(v, scale(add(add(a1, scale(a2, 2)), add(scale(a3, 2), a4)), h / 6));
		watch(kind, r, v, since + (i + 1) * h);
	}
	return { r, v };
}

/**
 * The whole crossing under one set of parameters, or null where it cannot be
 * flown. `coastSteps` is how finely the coast is walked: one while solving,
 * where only its far end matters, and many when the curve is being drawn.
 */
function flyArc(
	start: StateVector,
	thrustDir: Vec3,
	burnSeconds: number,
	coastSeconds: number,
	flips: boolean,
	accelKmS2: number,
	mu: number,
	burnSteps: number,
	coastSteps: number,
	watch: Watcher
): { r: Vec3; v: Vec3 } | null {
	const boosted = flyBurn(
		start,
		burnSeconds,
		mu,
		scale(thrustDir, accelKmS2),
		burnSteps,
		'boost',
		0,
		watch
	);
	if (!isFinite(boosted.r[0] + boosted.v[0])) return null;

	let state: { r: Vec3; v: Vec3 } = boosted;
	if (coastSeconds > 0) {
		// Nothing is pushing, so the coast is a conic and closed form walks it
		// exactly — no integration error, however long it runs. Each sample is
		// propagated from the start of the coast rather than from the one before
		// it, so drawing it finely costs no accuracy.
		for (let i = 1; i <= coastSteps; i++) {
			const at = propagateFull(boosted.r, boosted.v, (coastSeconds * i) / coastSteps, mu);
			if (!at) return null;
			watch('cruise', at.r, at.v, burnSeconds + (coastSeconds * i) / coastSteps);
			state = at;
		}
	}

	if (flips) {
		const braked = flyBurn(
			state,
			burnSeconds,
			mu,
			scale(thrustDir, -accelKmS2),
			burnSteps,
			'brake',
			burnSeconds + coastSeconds,
			watch
		);
		if (!isFinite(braked.r[0] + braked.v[0])) return null;
		state = braked;
	}

	return state;
}

/** Solve a 3×3 system by elimination with partial pivoting; null if singular. */
function solve3(a: number[][], b: Vec3): Vec3 | null {
	const m = [
		[a[0][0], a[0][1], a[0][2], b[0]],
		[a[1][0], a[1][1], a[1][2], b[1]],
		[a[2][0], a[2][1], a[2][2], b[2]]
	];
	for (let col = 0; col < 3; col++) {
		let best = col;
		for (let row = col + 1; row < 3; row++) {
			if (Math.abs(m[row][col]) > Math.abs(m[best][col])) best = row;
		}
		if (!(Math.abs(m[best][col]) > 0)) return null;
		[m[col], m[best]] = [m[best], m[col]];
		for (let row = 0; row < 3; row++) {
			if (row === col) continue;
			const factor = m[row][col] / m[col][col];
			for (let k = col; k < 4; k++) m[row][k] -= factor * m[col][k];
		}
	}
	const out: Vec3 = [m[0][3] / m[0][0], m[1][3] / m[1][1], m[2][3] / m[2][2]];
	return isFinite(out[0] + out[1] + out[2]) ? out : null;
}

/** Two directions across the chord, for pointing the drive off it. */
function acrossChord(e1: Vec3): { e2: Vec3; e3: Vec3 } {
	// Anything not parallel to the chord will do; the axis the chord leans on
	// least is the one furthest from being parallel to it.
	const abs = [Math.abs(e1[0]), Math.abs(e1[1]), Math.abs(e1[2])];
	const axis: Vec3 =
		abs[0] <= abs[1] && abs[0] <= abs[2] ? [1, 0, 0] : abs[1] <= abs[2] ? [0, 1, 0] : [0, 0, 1];
	const e2 = normalize(cross(e1, axis));
	return { e2, e3: normalize(cross(e1, e2)) };
}

export interface HeldDriveProblem {
	/** Where the ship starts and how fast — co-moving with the departure body. */
	start: StateVector;
	/** Where the destination is, in the same frame. */
	target: Ephemeris;
	departJd: number;
	/** What the drive holds, km/s². */
	accelKmS2: number;
	/** Seconds the drive is off between the burns. */
	coastSeconds: number;
	/** False for a flyby, which never slows down and so never flips. */
	flips: boolean;
	/** μ of whatever the crossing goes round, km³/s². */
	mu: number;
	/** Straight-line burn length to start from, seconds. */
	seedBurnSeconds: number;
}

const IGNORE: Watcher = () => {};

/**
 * Shoot for the target, or return null if the drive cannot close the geometry.
 *
 * The unknowns are packed as two offsets across the chord and the burn length,
 * because that puts the seed at the origin of the first two and makes the
 * Jacobian well behaved — solving for angles instead would have to care where
 * the chord happens to point.
 */
export function solveHeldDrive(problem: HeldDriveProblem): HeldDriveArc | null {
	const { start, target, departJd, accelKmS2, coastSeconds, flips, mu, seedBurnSeconds } = problem;
	const burns = flips ? 2 : 1;

	const here = target(departJd);
	if (!here) return null;
	const chord = sub(here.r, start.r);
	const chordLen = norm(chord);
	if (!(chordLen > 0) || !(seedBurnSeconds > 0) || !(accelKmS2 > 0)) return null;

	const e1 = normalize(chord);
	const { e2, e3 } = acrossChord(e1);
	const tolerance = chordLen * CLOSE_ENOUGH;

	const direction = (across2: number, across3: number): Vec3 =>
		normalize(add(e1, add(scale(e2, across2), scale(e3, across3))));

	/** How far the ship ends up from the target, under one set of unknowns. */
	const miss = (x: Vec3, gravity: number): Vec3 | null => {
		const burnSeconds = x[2];
		if (!(burnSeconds > 0)) return null;
		const totalSeconds = burns * burnSeconds + coastSeconds;
		const end = target(departJd + totalSeconds / SEC_PER_DAY);
		if (!end) return null;
		const flown = flyArc(
			start,
			direction(x[0], x[1]),
			burnSeconds,
			coastSeconds,
			flips,
			accelKmS2,
			mu * gravity,
			BURN_STEPS,
			1,
			IGNORE
		);
		return flown ? sub(flown.r, end.r) : null;
	};

	/** Newton from `from`, under `gravity` of the primary's pull. Null when it
	 *  cannot get inside the tolerance. */
	const refine = (from: Vec3, gravity: number): Vec3 | null => {
		let x = from;
		let residual = miss(x, gravity);
		if (!residual) return null;

		for (let step = 0; step < NEWTON_STEPS && norm(residual) > tolerance; step++) {
			// Finite differences. The two pointing offsets are dimensionless and the
			// burn is in seconds, so each gets a nudge on its own scale.
			const nudges: Vec3 = [1e-6, 1e-6, Math.max(1, x[2] * 1e-6)];
			const columns: Vec3[] = [];
			for (let i = 0; i < 3; i++) {
				const bumped: Vec3 = [
					x[0] + (i === 0 ? nudges[0] : 0),
					x[1] + (i === 1 ? nudges[1] : 0),
					x[2] + (i === 2 ? nudges[2] : 0)
				];
				const shifted = miss(bumped, gravity);
				if (!shifted) return null;
				columns.push(scale(sub(shifted, residual), 1 / nudges[i]));
			}

			const jacobian = [0, 1, 2].map((row) => columns.map((column) => column[row]));
			const delta = solve3(jacobian, scale(residual, -1));
			if (!delta) return null;

			// Halve the step until it actually helps. Newton on a shooting problem
			// overshoots badly from a poor seed, and the burn length has a floor it
			// must not step through.
			let damping = 1;
			let accepted: { x: Vec3; residual: Vec3 } | null = null;
			for (let i = 0; i < DAMPING_STEPS; i++) {
				const next: Vec3 = [
					x[0] + delta[0] * damping,
					x[1] + delta[1] * damping,
					x[2] + delta[2] * damping
				];
				const nextResidual = next[2] > 0 ? miss(next, gravity) : null;
				if (nextResidual && norm(nextResidual) < norm(residual)) {
					accepted = { x: next, residual: nextResidual };
					break;
				}
				damping /= 2;
			}
			if (!accepted) break;
			x = accepted.x;
			residual = accepted.residual;
		}

		return norm(residual) <= tolerance ? x : null;
	};

	// Straight at the real problem first, which is where a drive worth offering
	// this to lands from the straight-line seed. The ladder is the rescue, not the
	// route: walking it every time would cost five solves to answer one.
	let solved = refine([0, 0, seedBurnSeconds], 1);
	if (!solved) {
		let stepped: Vec3 | null = [0, 0, seedBurnSeconds];
		for (const gravity of CONTINUATION) {
			stepped = refine(stepped, gravity);
			if (!stepped) break;
		}
		solved = stepped;
	}
	if (!solved) return null;

	const thrustDir = direction(solved[0], solved[1]);
	const burnSeconds = solved[2];
	let peakSpeedKms = norm(start.v);
	const flown = flyArc(
		start,
		thrustDir,
		burnSeconds,
		coastSeconds,
		flips,
		accelKmS2,
		mu,
		BURN_STEPS,
		1,
		(_kind, _r, v) => {
			const speed = norm(v);
			if (speed > peakSpeedKms) peakSpeedKms = speed;
		}
	);
	if (!flown) return null;

	return {
		burnSeconds,
		coastSeconds,
		totalSeconds: burns * burnSeconds + coastSeconds,
		flips,
		thrustDir,
		arrivalVelocity: flown.v,
		peakSpeedKms
	};
}

export interface HeldDriveSample {
	kind: HeldDrivePhase;
	r: Vec3;
	/** Seconds since departure. */
	elapsed: number;
}

/** The four things an arc has to be re-flown from — what a route carries, minus
 *  everything the flying works out again for itself. */
export type HeldDriveShape = Pick<
	HeldDriveArc,
	'burnSeconds' | 'coastSeconds' | 'flips' | 'thrustDir'
>;

/**
 * Replay a solved arc as points to draw.
 *
 * Re-flown rather than stored: an arc is fixed by where its drive pointed and
 * how long it held, so a few hundred points never have to ride along with the
 * route that priced it.
 */
export function sampleHeldDrive(
	start: StateVector,
	shape: HeldDriveShape,
	accelKmS2: number,
	mu: number,
	stepsPerPhase: number
): HeldDriveSample[] {
	const out: HeldDriveSample[] = [{ kind: 'boost', r: start.r, elapsed: 0 }];
	flyArc(
		start,
		shape.thrustDir,
		shape.burnSeconds,
		shape.coastSeconds,
		shape.flips,
		accelKmS2,
		mu,
		stepsPerPhase,
		shape.coastSeconds > 0 ? stepsPerPhase : 0,
		(kind, r, _v, elapsed) => out.push({ kind, r, elapsed })
	);
	return out;
}

/** How far off the target a solved arc actually lands, km. The solve drives this
 *  under tolerance; tests assert on it rather than trusting that it did. */
export function heldDriveMissKm(problem: HeldDriveProblem, arc: HeldDriveArc): number | null {
	const end = problem.target(problem.departJd + arc.totalSeconds / SEC_PER_DAY);
	if (!end) return null;
	const flown = flyArc(
		problem.start,
		arc.thrustDir,
		arc.burnSeconds,
		arc.coastSeconds,
		arc.flips,
		problem.accelKmS2,
		problem.mu,
		BURN_STEPS,
		1,
		IGNORE
	);
	return flown ? norm(sub(flown.r, end.r)) : null;
}

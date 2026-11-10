import { describe, it, expect } from 'vitest';
import { Object3D, Quaternion, Vector3 } from 'three';
import {
	applyPointing,
	applySouthTowardParent,
	applyUpVector,
	bodyQuaternion,
	frameMapQuaternion,
	landedHeadingAt,
	markUtSpin,
	turnToHeading,
	type Orientation
} from './orientation';
import { EARTH_ID } from '$lib/constants';
import { J2000_JD, dateToJD, utcToTdb } from '$lib/time/jd';
import { EARTH_OBLIQUITY_DEG, equatorialToScene } from '$lib/math/units';

/** World direction the body's local `axis` ends up aiming after `q`. */
function aimed(q: Quaternion, axis: [number, number, number]): Vector3 {
	return new Vector3(...axis).applyQuaternion(q);
}

function expectDir(got: Vector3, want: [number, number, number]): void {
	expect(got.x).toBeCloseTo(want[0], 5);
	expect(got.y).toBeCloseTo(want[1], 5);
	expect(got.z).toBeCloseTo(want[2], 5);
}

describe('applyPointing', () => {
	it('aims the primary axis exactly at the parent (primary-only)', () => {
		const obj = new Object3D();
		applyPointing(
			obj,
			{ primary: { axis: '-y', target: 'parent' } },
			{ bodyPos: [0, 0, 0], parentPos: [0, 0, -10] }
		);
		expectDir(aimed(obj.quaternion, [0, -1, 0]), [0, 0, -1]);
	});

	it('satisfies both constraints exactly when targets are orthogonal', () => {
		const obj = new Object3D();
		applyPointing(
			obj,
			{ primary: { axis: '+z', target: 'parent' }, secondary: { axis: '+y', target: 'sun' } },
			{ bodyPos: [0, 0, 0], parentPos: [0, 0, -10], sunPos: [0, 10, 0] }
		);
		expectDir(aimed(obj.quaternion, [0, 0, 1]), [0, 0, -1]); // primary exact
		expectDir(aimed(obj.quaternion, [0, 1, 0]), [0, 1, 0]); // secondary exact
	});

	it('keeps primary exact and rolls secondary best-effort when not orthogonal', () => {
		const obj = new Object3D();
		applyPointing(
			obj,
			{ primary: { axis: '+z', target: 'parent' }, secondary: { axis: '+y', target: 'sun' } },
			{ bodyPos: [0, 0, 0], parentPos: [0, 0, -10], sunPos: [0, 10, -10] }
		);
		// Primary still exact; secondary projects onto the plane ⟂ primary → (0,1,0).
		expectDir(aimed(obj.quaternion, [0, 0, 1]), [0, 0, -1]);
		expectDir(aimed(obj.quaternion, [0, 1, 0]), [0, 1, 0]);
	});

	it('uses ctx.velocity for the velocity target', () => {
		const obj = new Object3D();
		applyPointing(
			obj,
			{ primary: { axis: '+x', target: 'velocity' } },
			{ bodyPos: [0, 0, 0], parentPos: [0, 0, 0], velocity: [0, 0, 5] }
		);
		expectDir(aimed(obj.quaternion, [1, 0, 0]), [0, 0, 1]);
	});

	it('is a no-op when the primary target is unavailable', () => {
		const obj = new Object3D();
		applyPointing(
			obj,
			{ primary: { axis: '+x', target: 'velocity' } },
			{ bodyPos: [0, 0, 0], parentPos: [1, 1, 1] } // no velocity
		);
		expect(obj.quaternion.equals(new Quaternion())).toBe(true);
	});

	it('matches applySouthTowardParent for the default {-y → parent} spec', () => {
		const bodyPos: [number, number, number] = [1, 2, 3];
		const parentPos: [number, number, number] = [4, 1, 9];
		const a = new Object3D();
		const b = new Object3D();
		applySouthTowardParent(a, bodyPos, parentPos);
		applyPointing(b, { primary: { axis: '-y', target: 'parent' } }, { bodyPos, parentPos });
		// Same minimal rotation, up to quaternion double-cover sign.
		expect(Math.abs(a.quaternion.dot(b.quaternion))).toBeCloseTo(1, 5);
	});
});

describe('frameMapQuaternion', () => {
	it('maps a single model axis onto its body axis', () => {
		const q = frameMapQuaternion({ '+y': '+z' })!;
		expectDir(aimed(q, [0, 1, 0]), [0, 0, 1]);
	});

	it('pins the full frame from two pairs, right-handed third axis', () => {
		// Voyager: model +Y → body -Z, model +Z → body -Y ⇒ model +X → body -X.
		const q = frameMapQuaternion({ '+y': '-z', '+z': '-y' })!;
		expectDir(aimed(q, [0, 1, 0]), [0, 0, -1]);
		expectDir(aimed(q, [0, 0, 1]), [0, -1, 0]);
		expectDir(aimed(q, [1, 0, 0]), [-1, 0, 0]);
	});

	it('is a proper rotation (det +1), never a reflection', () => {
		const q = frameMapQuaternion({ '+y': '-z', '+z': '-y' })!;
		// A unit quaternion always encodes det +1; verify it round-trips.
		expect(q.length()).toBeCloseTo(1, 6);
	});

	it('rejects malformed maps', () => {
		expect(frameMapQuaternion({})).toBeNull();
		expect(frameMapQuaternion({ '+y': 'up' })).toBeNull();
		expect(frameMapQuaternion({ '+y': '+z', '-y': '+x' })).toBeNull();
		expect(frameMapQuaternion({ '+x': '+z', '+y': '-z' })).toBeNull();
	});
});

describe('turnToHeading', () => {
	// Body frame at 0°N 0°E: up +X, north +Y, east −Z.
	const north = new Vector3(0, 1, 0);

	function stood(up: Vector3, heading: number): Object3D {
		const obj = new Object3D();
		applyUpVector(obj, up);
		turnToHeading(obj, north, heading);
		return obj;
	}

	it('faces the front along the heading and keeps the up axis', () => {
		for (const [heading, want] of [
			[0, [0, 1, 0]],
			[90, [0, 0, -1]],
			[180, [0, -1, 0]],
			[270, [0, 0, 1]]
		] as const) {
			const obj = stood(new Vector3(1, 0, 0), heading);
			expectDir(aimed(obj.quaternion, [0, 0, 1]), [...want]);
			expectDir(aimed(obj.quaternion, [0, 1, 0]), [1, 0, 0]);
		}
	});

	it('keeps a tilted seat and faces the heading within it', () => {
		const up = new Vector3(1, 0.2, 0.1).normalize();
		const obj = stood(up, 45);
		const front = aimed(obj.quaternion, [0, 0, 1]);
		expectDir(aimed(obj.quaternion, [0, 1, 0]), [up.x, up.y, up.z]);
		expect(front.dot(up)).toBeCloseTo(0, 6);
		// Seen from above, the front sits halfway between north and east.
		expect(front.y).toBeGreaterThan(0);
		expect(-front.z).toBeCloseTo(front.y, 1);
	});
});

describe('landedHeadingAt', () => {
	const headings = [
		{ jd: 10, deg: 120 },
		{ jd: 20, deg: 115 }
	];

	it('takes the latest landing at or before the date', () => {
		expect(landedHeadingAt(headings, 5)).toBeUndefined();
		expect(landedHeadingAt(headings, 10)).toBe(120);
		expect(landedHeadingAt(headings, 25)).toBe(115);
		expect(landedHeadingAt(undefined, 25)).toBeUndefined();
	});
});

/**
 * Earth turns with the clock, which keeps UT: at 12:00 UT the Sun stands over
 * the Greenwich meridian however far ΔT has run from the TDB the other bodies
 * spin by. Within 2°: the equation of time, and six centuries of drift of a
 * linear spin model.
 */
describe("Earth's spin", () => {
	const EARTH: Orientation = {
		pole_ra_0: 0,
		pole_ra_1: -0.641,
		pole_dec_0: 90,
		pole_dec_1: -0.557,
		w0: 190.147,
		w1: 360.9856235,
		w2: 0
	};
	const DEG = Math.PI / 180;

	/** East longitude the Sun stands over: a low-precision Sun (Astronomical
	 *  Almanac) on J2000 axes, through Earth's spin. */
	function subsolarLongitude(jd: number, orientation: Orientation): number {
		const n = utcToTdb(jd) - J2000_JD;
		const g = (357.528 + 0.9856003 * n) * DEG;
		const ofDate = 280.46 + 0.9856474 * n + 1.915 * Math.sin(g) + 0.02 * Math.sin(2 * g);
		// Less the precession since J2000, onto the axes the scene uses.
		const lon = (ofDate - 1.396971 * (n / 36525)) * DEG;
		const obl = EARTH_OBLIQUITY_DEG * DEG;
		const sun = equatorialToScene(
			Math.cos(lon),
			Math.cos(obl) * Math.sin(lon),
			Math.sin(obl) * Math.sin(lon),
			new Vector3()
		);
		sun.applyQuaternion(bodyQuaternion(orientation, jd).invert());
		return Math.atan2(-sun.z, sun.x) / DEG;
	}

	const at = (iso: string) => dateToJD(new Date(iso));
	const tagged = (): Orientation => {
		const o = { ...EARTH };
		markUtSpin(EARTH_ID, o);
		return o;
	};

	it.each(['1600-06-01', '2026-06-01', '2600-06-01'])(
		'has the Sun at noon at 12:00 UT on %s',
		(day) => {
			expect(Math.abs(subsolarLongitude(at(`${day}T12:00:00Z`), tagged()))).toBeLessThan(2);
		}
	);

	it('has the Sun over 90° W at 18:00 UT', () => {
		expect(Math.abs(subsolarLongitude(at('2600-06-01T18:00:00Z'), tagged()) + 90)).toBeLessThan(2);
	});

	it('would be half an hour off in 2600 on TDB days', () => {
		expect(Math.abs(subsolarLongitude(at('2600-06-01T12:00:00Z'), EARTH))).toBeGreaterThan(6);
	});

	it('leaves the other bodies on TDB days', () => {
		const mars = { ...EARTH, pole_dec_0: 52.9, w0: 176.63, w1: 350.89198226 };
		markUtSpin('naif-499', mars);
		expect(mars.ut).toBeUndefined();
	});
});

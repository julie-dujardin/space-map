import { describe, it, expect } from 'vitest';
import { PerspectiveCamera, Quaternion, Vector3 } from 'three';
import { ObjectType, type BodyData, type PositionedBody } from '$lib/types/objects';
import { OrbitalSource } from '$lib/fetch/position/format';
import { kmToScene } from '$lib/math/units';
import { barycenterPrimaryId, collisionParentId } from '$lib/scene/state/bodies.svelte';
import {
	clampCameraOutsideBody,
	LANDED_KEEP_AWAY_KM,
	type SurfaceClampContext
} from './camera-limits';

function mkBody(
	data: Partial<BodyData> & Pick<BodyData, 'id'>,
	pos: [number, number, number] = [0, 0, 0]
): PositionedBody {
	return {
		data: {
			name: null,
			objectType: ObjectType.PLANET,
			parentId: 'naif-0',
			a: 0,
			e: 0,
			i: 0,
			om: 0,
			w: 0,
			ma: 0,
			n: 0,
			epoch: 2451545,
			radiusKm: 1000,
			hasLocalized: false,
			validityStart: -Infinity,
			validityEnd: Infinity,
			orbitalSource: OrbitalSource.SPICE,
			...data
		},
		position: pos
	};
}

// Radius-1000 PLANET → fixed 100 km clearance → nominal wall at 1100 km.
const NOMINAL = kmToScene(1100);
const FOCUS: [number, number, number] = [0, 0, 0];

/** Parent centered `km` from the focused object (along +x), as the renderer sees it. */
function parentAt(km: number) {
	return {
		body: mkBody({ id: 'naif-399' }, [kmToScene(km), 0, 0]),
		center: new Vector3(kmToScene(km), 0, 0)
	};
}

describe('clampCameraOutsideBody', () => {
	it('leaves a camera outside the wall untouched', () => {
		// Orbiter 2000 km up: wall stays at the nominal 1100 km surface.
		const { body, center } = parentAt(2000);
		const cam = new PerspectiveCamera();
		cam.position.copy(center).add(new Vector3(kmToScene(1500), 0, 0)); // 1500 km out
		clampCameraOutsideBody(cam, body, FOCUS);
		expect(cam.position.distanceTo(center)).toBeCloseTo(kmToScene(1500), 10);
	});

	it('pushes a penetrating camera out to the surface, preserving direction', () => {
		const { body, center } = parentAt(2000);
		const cam = new PerspectiveCamera();
		cam.position.copy(center).add(new Vector3(0, kmToScene(500), 0)); // 500 km in, on +y
		clampCameraOutsideBody(cam, body, FOCUS);
		expect(cam.position.distanceTo(center)).toBeCloseTo(NOMINAL, 10);
		expect(cam.position.x).toBeCloseTo(center.x, 10); // still on the +y radial
		expect(cam.position.z).toBeCloseTo(0, 10);
	});

	// Wall sits LANDED_KEEP_AWAY_KM above the probe's own ground spot (1000 km).
	const LANDED_SHELL = kmToScene(1000 + LANDED_KEEP_AWAY_KM);

	/** Terrain data still loading (radialKm → null) ⇒ shell at the probe. */
	const landedCtx = (
		radialKm: SurfaceClampContext['radialKm'] = () => null
	): SurfaceClampContext => ({ invQuat: new Quaternion(), radialKm, seated: true });

	/** Near plane shrunk to nothing so only the eye constrains — three's default
	 *  0.1 near is planet-sized against these kmToScene radii. */
	const landedCam = () => {
		const cam = new PerspectiveCamera();
		cam.near = 1e-15;
		return cam;
	};

	it('lifts the camera to the keep-away shell above a landed probe', () => {
		const { body, center } = parentAt(1000);
		const cam = landedCam();
		cam.position.set(0, 0, 0); // at the probe / ground level
		clampCameraOutsideBody(cam, body, FOCUS, landedCtx());
		expect(cam.position.distanceTo(center)).toBeCloseTo(LANDED_SHELL, 12);
	});

	it('leaves a camera already above the keep-away shell untouched', () => {
		const { body, center } = parentAt(1000);
		const cam = landedCam();
		const above = kmToScene(LANDED_KEEP_AWAY_KM) * 2; // comfortably outside the shell
		cam.position.set(-above, 0, 0); // above ground, away from the planet
		clampCameraOutsideBody(cam, body, FOCUS, landedCtx());
		expect(cam.position.distanceTo(center)).toBeCloseTo(kmToScene(1000) + above, 12);
	});

	it('blocks the sub-surface volume under a landed probe', () => {
		const { body, center } = parentAt(1000);
		const cam = landedCam();
		cam.position.set(kmToScene(100), 0, 0); // nudged 100 km toward the planet — underground
		clampCameraOutsideBody(cam, body, FOCUS, landedCtx());
		expect(cam.position.distanceTo(center)).toBeCloseTo(LANDED_SHELL, 12); // back to the keep-away shell
	});

	it('floors the camera on the rendered terrain when it resolves', () => {
		const { body, center } = parentAt(1000);
		// Terrain under the camera 5 km above the probe's radial shell — the wall
		// must follow the terrain, not the probe.
		const dirs: [number, number, number][] = [];
		const cam = landedCam();
		cam.position.set(kmToScene(100), 0, 0); // underground toward the planet
		clampCameraOutsideBody(
			cam,
			body,
			FOCUS,
			landedCtx((dir) => {
				dirs.push(dir);
				return 1005;
			})
		);
		expect(cam.position.distanceTo(center)).toBeCloseTo(kmToScene(1005 + LANDED_KEEP_AWAY_KM), 12);
		// Identity orientation: the body-fixed sample directions are the scene-frame
		// point directions from the body centre — eye + 4 (degenerate) near corners,
		// all −x here.
		expect(dirs).toHaveLength(5);
		for (const dir of dirs) {
			expect(dir[0]).toBeCloseTo(-1, 9);
			expect(dir[1]).toBeCloseTo(0, 9);
			expect(dir[2]).toBeCloseTo(0, 9);
		}
	});

	it('keeps the near-plane corners above the terrain, not just the eye', () => {
		const { body, center } = parentAt(1000);
		const wall = kmToScene(1000 + LANDED_KEEP_AWAY_KM);
		const cam = new PerspectiveCamera();
		cam.fov = 90;
		cam.aspect = 2;
		cam.near = kmToScene(1);
		// Eye exactly on the wall, looking sideways (−z): the −x near corners dip
		// hw = 2 km toward the planet and must drive the lift.
		cam.position.copy(center).add(new Vector3(wall, 0, 0));
		clampCameraOutsideBody(
			cam,
			body,
			FOCUS,
			landedCtx(() => 1000)
		);
		const hh = kmToScene(1); // tan(45°)·near
		const hw = 2 * hh;
		const worstCorner = Math.hypot(wall - hw, hh, cam.near);
		expect(cam.position.distanceTo(center)).toBeCloseTo(wall + (wall - worstCorner), 12);
	});

	/** Shape-model host: mesh reaching 17 km out of a body quoted at 10 km. */
	const modelBody = (pos: [number, number, number] = [0, 0, 0]) =>
		mkBody({ id: 'spkid-2000433', objectType: ObjectType.ASTEROID, radiusKm: 10 }, pos);
	const MODEL_CLEARANCE_KM = 0.1;
	const meshCtx = (radialKm: SurfaceClampContext['radialKm']): SurfaceClampContext => ({
		invQuat: new Quaternion(),
		outerRadiusKm: 20,
		radialKm
	});

	it('walls the camera on the shape model, past the sphere at its radius', () => {
		const body = modelBody();
		const cam = new PerspectiveCamera();
		cam.position.set(kmToScene(15), 0, 0); // inside the mesh, outside the sphere
		clampCameraOutsideBody(
			cam,
			body,
			FOCUS,
			meshCtx(() => 17)
		);
		expect(cam.position.length()).toBeCloseTo(kmToScene(17 + MODEL_CLEARANCE_KM), 12);
	});

	it('holds the mesh wall on the focused body itself (no orbiter cap)', () => {
		// focusTruePos is the body: focusDist 0 would cap the wall to nothing.
		const body = modelBody();
		const cam = new PerspectiveCamera();
		cam.position.set(0, kmToScene(2), 0);
		clampCameraOutsideBody(
			cam,
			body,
			FOCUS,
			meshCtx(() => 6)
		);
		expect(cam.position.length()).toBeCloseTo(kmToScene(6 + MODEL_CLEARANCE_KM), 12);
		expect(cam.position.y).toBeGreaterThan(0); // still on the +y radial
	});

	it('lets the camera into a narrow side the quoted radius would fence off', () => {
		const body = modelBody();
		const cam = new PerspectiveCamera();
		cam.position.set(0, kmToScene(6), 0); // inside the sphere, outside the mesh
		clampCameraOutsideBody(
			cam,
			body,
			FOCUS,
			meshCtx(() => 5)
		);
		expect(cam.position.length()).toBeCloseTo(kmToScene(6), 12);
	});

	it('skips the mesh cast outside the model bounding sphere', () => {
		const body = modelBody();
		const cam = new PerspectiveCamera();
		cam.position.set(kmToScene(25), 0, 0);
		let casts = 0;
		clampCameraOutsideBody(
			cam,
			body,
			FOCUS,
			meshCtx(() => {
				casts++;
				return 17;
			})
		);
		expect(casts).toBe(0);
		expect(cam.position.length()).toBeCloseTo(kmToScene(25), 12);
	});

	it('falls back to the quoted radius where the mesh has a hole', () => {
		// Not to the bounding sphere: that would fling a close-up camera out by
		// most of a radius the moment a sample came back empty.
		const body = modelBody();
		const cam = new PerspectiveCamera();
		cam.position.set(kmToScene(5), 0, 0);
		clampCameraOutsideBody(
			cam,
			body,
			FOCUS,
			meshCtx(() => null)
		);
		expect(cam.position.length()).toBeCloseTo(kmToScene(10 + MODEL_CLEARANCE_KM), 12);
	});

	it('is a no-op for a sizeless parent (barycenter)', () => {
		const cam = new PerspectiveCamera();
		cam.position.set(kmToScene(500), 0, 0);
		clampCameraOutsideBody(
			cam,
			mkBody({ id: 'naif-3', radiusKm: 0 }, [kmToScene(1000), 0, 0]),
			FOCUS
		);
		expect(cam.position.x).toBeCloseTo(kmToScene(500), 10);
	});
});

describe('collisionParentId', () => {
	it('skips Sun/SSB orbiters', () => {
		expect(collisionParentId('naif-10')).toBeUndefined();
		expect(collisionParentId('naif-0')).toBeUndefined();
	});

	it('resolves a planetary barycenter to its dominant planet', () => {
		expect(collisionParentId('naif-5')).toBe('naif-599');
	});

	it('keeps a physical parent (planet or moon) as-is', () => {
		expect(collisionParentId('naif-399')).toBe('naif-399');
		expect(collisionParentId('naif-301')).toBe('naif-301');
	});
});

describe('barycenterPrimaryId', () => {
	it('resolves every planetary barycenter to its dominant planet', () => {
		expect(barycenterPrimaryId('naif-6')).toBe('naif-699');
		expect(barycenterPrimaryId('naif-9')).toBe('naif-999');
	});

	it('resolves the SSB to the Sun', () => {
		expect(barycenterPrimaryId('naif-0')).toBe('naif-10');
	});

	it('is null for a physical body', () => {
		expect(barycenterPrimaryId('naif-699')).toBeNull();
	});
});

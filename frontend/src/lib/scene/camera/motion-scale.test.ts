import { describe, it, expect } from 'vitest';
import { PerspectiveCamera, Vector3 } from 'three';
import { ObjectType, type BodyData, type PositionedBody } from '$lib/types/objects';
import { OrbitalSource } from '$lib/fetch/position/format';
import { kmToScene } from '$lib/math/units';
import { cameraMotionScale } from './motion-scale';

const FOCUS: [number, number, number] = [0, 0, 0];
const VIEWPORT_H = 800;
const FOV = 50;

function mkBody(
	radiusKm: number,
	pos: [number, number, number] = [0, 0, 0],
	id = 'naif-499',
	objectType = ObjectType.PLANET
): PositionedBody {
	const data: BodyData = {
		id,
		name: null,
		objectType,
		parentId: 'naif-0',
		a: 0,
		e: 0,
		i: 0,
		om: 0,
		w: 0,
		ma: 0,
		n: 0,
		epoch: 2451545,
		radiusKm,
		hasLocalized: false,
		validityStart: -Infinity,
		validityEnd: Infinity,
		orbitalSource: OrbitalSource.SPICE
	};
	return { data, position: pos };
}

/** A model-bearing craft: no measured radius, drawn in the overlay. */
function mkCraft(pos: [number, number, number] = [0, 0, 0]): PositionedBody {
	return mkBody(0, pos, 'sat-25544', ObjectType.SPACECRAFT);
}

/** Camera `km` from the focus origin, on the +z radial and looking down it. */
function camAt(km: number): PerspectiveCamera {
	const cam = new PerspectiveCamera(FOV, 1, 0.1, 1e9);
	cam.position.set(0, 0, kmToScene(km));
	cam.lookAt(0, 0, 0);
	cam.updateMatrixWorld();
	return cam;
}

/** Horizontal screen position (px) of a world point, aspect 1 so width = height. */
function screenX(point: Vector3, camera: PerspectiveCamera): number {
	return (point.clone().project(camera).x * VIEWPORT_H) / 2;
}

/**
 * How far (px) the sub-camera ground point travels for a `dragPx` drag, using
 * the rotation OrbitControls derives from `rotateSpeed`: a drag of the full
 * viewport height is one whole turn.
 */
function groundTravelPx(dragPx: number, radiusKm: number, altitudeKm: number): number {
	const camera = camAt(radiusKm + altitudeKm);
	const { rotate } = cameraMotionScale(camera, FOCUS, mkBody(radiusKm), undefined);
	const theta = (2 * Math.PI * dragPx * rotate) / VIEWPORT_H;

	const before = new Vector3(0, 0, kmToScene(radiusKm));
	const after = before.clone().applyAxisAngle(new Vector3(0, 1, 0), -theta);
	return Math.abs(screenX(after, camera) - screenX(before, camera));
}

describe('cameraMotionScale rotate', () => {
	it('drags the ground 1:1 with the pointer just above a surface', () => {
		// 100 km over Mars: 50 px of drag must move the ground 50 px.
		expect(groundTravelPx(50, 3390, 100)).toBeCloseTo(50, 1);
	});

	it('holds 1:1 on a body of a wholly different size', () => {
		// Phobos, 2 km up — same rule, three orders of magnitude down.
		expect(groundTravelPx(50, 11.1, 2)).toBeCloseTo(50, 1);
	});

	it('hands back the default rate once the body is small on screen', () => {
		// Past ~7.7 radii the 1:1 ask exceeds three's own rate and is clamped.
		const far = camAt(3390 * 20);
		expect(cameraMotionScale(far, FOCUS, mkBody(3390), undefined).rotate).toBe(1);
	});

	it('stays positive with the camera on the surface', () => {
		const seated = camAt(3390);
		expect(cameraMotionScale(seated, FOCUS, mkBody(3390), undefined).rotate).toBeGreaterThan(0);
	});
});

describe('cameraMotionScale translate', () => {
	it('is the clearance fraction just above a focused body', () => {
		// 100 km over a 3390 km body: 100 / 3490.
		const mars = mkBody(3390);
		expect(cameraMotionScale(camAt(3490), FOCUS, mars, undefined).translate).toBeCloseTo(
			100 / 3490,
			10
		);
	});

	it('leaves the speeds alone far from everything', () => {
		const mars = mkBody(3390);
		expect(cameraMotionScale(camAt(1e7), FOCUS, mars, undefined).translate).toBeGreaterThan(0.999);
	});

	it('floors instead of freezing on the surface', () => {
		const mars = mkBody(3390);
		expect(cameraMotionScale(camAt(3390), FOCUS, mars, undefined).translate).toBe(0.02);
	});

	it('follows the parent when it is the nearer surface', () => {
		// Focused on a 400 km orbiter, camera 350 km down its Earthward radial:
		// 50 km of real clearance over a 350 km lever arm.
		const earth = mkBody(6371, [0, 0, kmToScene(6771)], 'naif-399');
		expect(cameraMotionScale(camAt(350), FOCUS, mkCraft(), earth).translate).toBeCloseTo(
			50 / 350,
			10
		);
	});
});

describe('cameraMotionScale on a model-bearing focus', () => {
	it('leaves the rotation at the default rate', () => {
		// 5 m nominal would otherwise read as a body filling the view at 20 m out.
		expect(cameraMotionScale(camAt(0.02), FOCUS, mkCraft(), undefined).rotate).toBe(1);
	});

	it('leaves pan and zoom at the default rate', () => {
		expect(cameraMotionScale(camAt(0.02), FOCUS, mkCraft(), undefined).translate).toBe(1);
	});

	// A parent underneath is still a real surface: covered by the parent case above.
});

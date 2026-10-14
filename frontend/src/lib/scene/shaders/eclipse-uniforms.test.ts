import { describe, it, expect } from 'vitest';
import { Mesh, MeshStandardMaterial, SphereGeometry, Vector3 } from 'three';

import { collectOccluders, updateEclipseUniforms } from './eclipse-uniforms';
import { updatePlanetshineUniforms } from './planetshine-uniforms';
import { SUN_ID } from '$lib/constants';
import {
	evaluateEclipseFactor,
	getEclipseSceneUniforms,
	makeEclipseSelfUniforms,
	MAX_OCCLUDERS
} from '$lib/scene/objects/surface/eclipse-shadow';
import { makePlanetshineUniforms } from '$lib/scene/objects/surface/planetshine';
import type { BodyObjects } from '$lib/scene/types';
import { ObjectType } from '$lib/types/objects';
import type { Vec3 } from '$lib/scene/animation/math';

/**
 * A scene with more drawn bodies than one occluder list holds. Saturn is at
 * 9.5 AU, Mimas is on the line from Saturn to the Sun, a second small moon is
 * behind Saturn, and 36 bodies larger than both are far off that line.
 */

/** Scene units per kilometre: 10 per AU. */
const KM = 10 / 1.496e8;
const SATURN: Vec3 = [95, 0, 0];
const SATURN_R = 58232 * KM;
const MIMAS_R = 198 * KM;
const ORBIT = 185_520 * KM;
/** The scene origin. */
const FOCUS = new Vector3();
/** The camera is nearer to Saturn than its moons are. */
const CAMERA = 2 * SATURN_R;

function body(
	id: string,
	position: Vec3,
	radiusScene: number,
	type = ObjectType.MOON
): BodyObjects {
	return {
		body: { data: { id, objectType: type, radiusKm: radiusScene / KM }, position },
		radiusScene,
		carried: false,
		cachedDist: 0,
		atmosphere: null,
		eclipseShadow: type === ObjectType.STAR ? null : makeEclipseSelfUniforms(),
		planetshine: type === ObjectType.STAR ? null : makePlanetshineUniforms(),
		mesh: new Mesh(new SphereGeometry(1), new MeshStandardMaterial())
	} as unknown as BodyObjects;
}

function scene(): Map<string, BodyObjects> {
	const bodies = [body(SUN_ID, [0, 0, 0], 696_000 * KM, ObjectType.STAR)];
	for (let i = 0; i < 36; i++) bodies.push(body(`big-${i}`, [0, 10 + i, 0], 1000 * KM));
	bodies.push(body('mimas', [SATURN[0] - ORBIT, 0, 0], MIMAS_R));
	bodies.push(body('behind', [SATURN[0] + ORBIT, 0, 0], MIMAS_R));
	// Last, so its index in the occluder list is past MAX_OCCLUDERS.
	bodies.push(body('saturn', SATURN, SATURN_R, ObjectType.PLANET));
	return new Map(bodies.map((bo) => [bo.body.data.id, bo]));
}

function frame(bodies: Map<string, BodyObjects>, cameraDistance: number): void {
	expect(bodies.size - 1).toBeGreaterThan(MAX_OCCLUDERS);
	const occluders = collectOccluders(bodies, []);
	updateEclipseUniforms(bodies, occluders, SATURN, cameraDistance, true);
	updatePlanetshineUniforms(bodies, occluders, true, 1);
}

/** Radii of the occluders in the list of one receiver. */
function listOf(bo: BodyObjects): number[] {
	const self = bo.eclipseShadow!;
	return self.uOccluders.value.slice(0, self.uOccluderCount.value).map((v) => v.w);
}

describe('updateEclipseUniforms', () => {
	it('puts a small moon in line with the Sun in the list of its planet', () => {
		const bodies = scene();
		frame(bodies, CAMERA);
		expect(listOf(bodies.get('saturn')!)).toEqual([MIMAS_R]);
	});

	it('puts the planet in the list of a small moon in its shadow', () => {
		const bodies = scene();
		frame(bodies, CAMERA);
		expect(listOf(bodies.get('behind')!)).toContain(SATURN_R);
	});

	it('fills the scene set with the occluders that reach the view, not the largest', () => {
		const bodies = scene();
		frame(bodies, CAMERA);
		const u = getEclipseSceneUniforms();
		expect(u.uOccluderCount.value).toBe(1);
		expect(u.uOccluders.value[0].w).toBe(MIMAS_R);
		// Mimas covers all of the Sun seen from the centre of Saturn.
		expect(evaluateEclipseFactor(FOCUS, FOCUS)).toBe(0);
	});
});

describe('updatePlanetshineUniforms', () => {
	it('lets a planet past the first MAX_OCCLUDERS bodies light its moon', () => {
		const bodies = scene();
		frame(bodies, CAMERA);
		const dir = bodies.get('mimas')!.planetshine!.uShineDir.value[0];
		expect(dir.x).toBeCloseTo(1, 9);
		expect(dir.w).toBeCloseTo(SATURN_R / ORBIT, 9);
	});
});

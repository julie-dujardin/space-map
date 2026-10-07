import { describe, it, expect } from 'vitest';
import { BackSide, FrontSide, Group, type Material, Vector3 } from 'three';

import { updateAtmosphereShaders } from './atmosphere-uniforms';
import { SUN_ID } from '$lib/constants';
import { makeStarSurfaceMaterial, starViewTintUniforms } from '$lib/scene/objects/sun';
import { buildAtmosphereNode, type AtmosphereParams } from '$lib/scene/objects/surface/atmosphere';
import { ATMOSPHERE_QUALITY_PRESETS } from '$lib/scene/objects/surface/atmosphere-quality';
import type { BodyObjects } from '$lib/scene/types';

/**
 * The scene origin is the focus, so a camera close to the focus is close to
 * the origin, not to every planet. A shell that measures from the origin takes
 * that camera as inside it: it stops its depth test and draws through the
 * focused body, and the Sun disc is tinted through air that is not there, down
 * to black.
 */

const PARAMS: AtmosphereParams = {
	topAltitudeKm: 100,
	rayleighScatterPerKm: [5.8e-3, 13.6e-3, 33.1e-3],
	rayleighScaleHeightKm: 8.4,
	mieScatterPerKm: [4e-3, 4e-3, 4e-3],
	mieAbsorptionPerKm: [4e-4, 4e-4, 4e-4],
	mieScaleHeightKm: 1.2,
	miePhase: new Array(3 * 128).fill(1 / (4 * Math.PI)),
	absorptionPerKm: [0, 0, 0],
	absorptionCenterKm: 25,
	absorptionWidthKm: 15,
	bakedCompensation: 1,
	multiScatterGain: 0.3,
	sunIntensity: 5,
	sunColor: [1, 1, 1]
};

const RADIUS_KM = 6371;
const RADIUS_SCENE = 1;
const SHELL_SCENE = RADIUS_SCENE * (1 + PARAMS.topAltitudeKm / RADIUS_KM);
const PLANET_AT: [number, number, number] = [50, 0, 0];

function scene(): {
	bodyObjects: Map<string, BodyObjects>;
	planet: BodyObjects;
	sun: BodyObjects;
} {
	const root = new Group();
	root.position.set(...PLANET_AT);
	const atmosphere = buildAtmosphereNode(PARAMS, RADIUS_SCENE, RADIUS_KM);
	root.add(atmosphere.mesh);
	const planet = {
		body: { position: PLANET_AT, data: { id: 'planet' } },
		root,
		mesh: null,
		atmosphere
	} as unknown as BodyObjects;
	const sun = {
		body: { position: [0, 0, 500], data: { id: SUN_ID } },
		root: new Group(),
		mesh: { material: makeStarSurfaceMaterial() }
	} as unknown as BodyObjects;
	return {
		bodyObjects: new Map([
			[SUN_ID, sun],
			['planet', planet]
		]),
		planet,
		sun
	};
}

function update(bodyObjects: Map<string, BodyObjects>, camera: Vector3) {
	return updateAtmosphereShaders(
		bodyObjects,
		camera,
		true,
		false,
		1,
		ATMOSPHERE_QUALITY_PRESETS.high,
		2461000.5
	);
}

describe('updateAtmosphereShaders', () => {
	it('keeps a far shell outside-view when the camera is near the focus', () => {
		const { bodyObjects, planet } = scene();
		// Closer to the origin than one shell radius, 49.5 from the planet.
		const state = update(bodyObjects, new Vector3(SHELL_SCENE / 2, 0, 0));
		const material = planet.atmosphere!.material;
		expect(state.insideShell).toBe(false);
		expect(state.skyboxIntensity).toBe(1);
		expect(material.side).toBe(FrontSide);
		expect(material.depthTest).toBe(true);
		expect(material.depthWrite).toBe(true);
	});

	it('flips a shell to inside-view once the camera is inside it', () => {
		const { bodyObjects, planet } = scene();
		const camera = new Vector3(...PLANET_AT).add(
			new Vector3(0, (RADIUS_SCENE + SHELL_SCENE) / 2, 0)
		);
		const state = update(bodyObjects, camera);
		const material = planet.atmosphere!.material;
		expect(state.insideShell).toBe(true);
		expect(material.side).toBe(BackSide);
		expect(material.depthTest).toBe(false);
	});

	it('aims the Sun disc tint at the shell when the camera is near the focus', () => {
		const { bodyObjects, sun } = scene();
		update(bodyObjects, new Vector3(SHELL_SCENE / 2, 0, 0));
		const tint = starViewTintUniforms(sun.mesh!.material as Material)!;
		expect(tint.uAtmoTEnable.value).toBe(1);
		expect(tint.uAtmoTCenter.value.toArray()).toEqual(PLANET_AT);
	});
});

import { describe, it, expect } from 'vitest';
import { ObjectType, type BodyData, type PositionedBody } from '$lib/types/objects';
import { OrbitalSource } from '$lib/fetch/position/format';
import { AU_SCALE } from '$lib/math/units';
import { BodyIndex } from '$lib/scene/state/bodies.svelte';
import { MinorBucket } from '$lib/fetch/position/minor-columns';
import { VisibilityController } from './controller.svelte';
import { VISIBILITY } from './thresholds';

/**
 * Asteroid-moon focus gate.
 *
 * The visibility ratio compares camera-to-focus distance with the moon's
 * orbit (~1e-6 AU for asteroid moons), so it says nothing about proximity to
 * the parent — ungated, every asteroid moon pops in whenever the camera zooms
 * close to anything (e.g. Remus while orbiting an Earth satellite). Asteroid
 * moons must require focus on their family: the parent asteroid or one of
 * its moons.
 */

const SYLVIA = 'sbdb-2087';
const REMUS = 'sbdb-remus';
const SAT = 'sat-fengyun';

/** Camera close enough that the ungated ratio would grant Remus FULL. */
const CLOSE_AU = 0.00002;

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
			radiusKm: 0,
			hasLocalized: false,
			validityStart: -Infinity,
			validityEnd: Infinity,
			orbitalSource: OrbitalSource.SPICE,
			...data
		},
		position: pos
	};
}

function buildScene() {
	const bodies = new BodyIndex();
	bodies.addBodies([
		mkBody({ id: 'naif-399', name: 'Earth', parentId: 'naif-3', a: 1 }),
		mkBody({
			id: SAT,
			name: 'FENGYUN 1C DEB',
			objectType: ObjectType.SPACECRAFT,
			parentId: 'naif-399',
			a: 5e-5
		})
	]);
	// Sylvia lives in an asteroid zone bucket, not bodiesById — like the real
	// chunk-load path, so getMoonVisibility's parent lookup takes getBody.
	const sylvia = mkBody({
		id: SYLVIA,
		name: 'Sylvia',
		objectType: ObjectType.ASTEROID_MAIN_BELT,
		parentId: 'naif-0',
		a: 3.49
	});
	const bucket = new MinorBucket(new Map());
	bucket.addPlaceholder(sylvia);
	bodies.asteroidBodiesByZone.set('small_bodies/MBA', bucket);
	const remus = mkBody({
		id: REMUS,
		name: 'Remus',
		objectType: ObjectType.MOON,
		parentId: SYLVIA,
		a: 4.72e-6 // ~706 km
	});
	const vis = new VisibilityController(bodies);
	vis.updateViewport(954);
	return { bodies, vis, sylvia, remus };
}

const vname = (v: VISIBILITY) => VISIBILITY[v];

describe('asteroid-moon focus gate', () => {
	it('hides the moon when zoomed close inside another system', () => {
		const { bodies, vis, remus } = buildScene();
		vis.setFocused(bodies.bodiesById.get(SAT)!);
		vis.updateCamera(CLOSE_AU * AU_SCALE, 2451545);
		expect(vis.focusedSystemId).toBe('naif-3');
		expect(vname(vis.getMoonVisibility(remus))).toBe(vname(VISIBILITY.HIDE));
	});

	it('shows the moon when its parent asteroid is focused', () => {
		const { vis, sylvia, remus } = buildScene();
		vis.setFocused(sylvia);
		vis.updateCamera(CLOSE_AU * AU_SCALE, 2451545);
		// Top-level parent → no system root; the focusedBodyId match must carry.
		expect(vis.focusedSystemId).toBeNull();
		expect(vname(vis.getMoonVisibility(remus))).toBe(vname(VISIBILITY.FULL));
	});

	it('shows the moon when a moon of the same asteroid is focused', () => {
		const { vis, remus } = buildScene();
		vis.setFocused(remus);
		vis.updateCamera(CLOSE_AU * AU_SCALE, 2451545);
		// The asteroid itself becomes the focused-system root.
		expect(vis.focusedSystemId).toBe(SYLVIA);
		expect(vname(vis.getMoonVisibility(remus))).toBe(vname(VISIBILITY.FULL));
	});

	it('still ratio-gates in-family moons by distance', () => {
		const { vis, sylvia, remus } = buildScene();
		vis.setFocused(sylvia);
		vis.updateCamera(1.5 * AU_SCALE, 2451545);
		expect(vname(vis.getMoonVisibility(remus))).toBe(vname(VISIBILITY.HIDE));
	});
});

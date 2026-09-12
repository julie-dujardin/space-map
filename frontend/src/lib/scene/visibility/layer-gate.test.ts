import { describe, it, expect } from 'vitest';
import { ObjectType, type BodyData, type PositionedBody } from '$lib/types/objects';
import { OrbitalSource } from '$lib/fetch/position/format';
import { AU_SCALE } from '$lib/math/units';
import { BodyIndex } from '$lib/scene/state/bodies.svelte';
import { LayerSet } from '$lib/scene/layers';
import { VisibilityController } from './controller.svelte';
import { VISIBILITY } from './thresholds';

/**
 * The layer gate over the per-frame visibility decisions.
 *
 * A hidden layer must read as HIDE for every object of its kind and for the
 * point clouds that stand in for them, whatever the camera is doing, while
 * everything else is decided by distance and focus as before. The Sun answers
 * to no layer: the scene is lit by it, so it can never be switched off.
 */

const SUN = 'naif-10';
const EARTH = 'naif-399';
const MOON = 'naif-301';
const PROBE = 'probe-1';

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

function buildScene(layers: LayerSet) {
	const bodies = new BodyIndex();
	bodies.addBodies([
		mkBody({ id: SUN, name: 'Sun', objectType: ObjectType.STAR }),
		mkBody({ id: EARTH, name: 'Earth', parentId: 'naif-3', a: 1 }),
		mkBody({ id: MOON, name: 'Moon', objectType: ObjectType.MOON, parentId: 'naif-3', a: 0.00257 }),
		mkBody({
			id: PROBE,
			name: 'Voyager 1',
			objectType: ObjectType.SPACECRAFT,
			parentId: 'naif-0',
			a: 20
		})
	]);
	const vis = new VisibilityController(
		bodies,
		() => null,
		() => null,
		() => null,
		() => layers
	);
	vis.updateViewport(954);
	vis.setFocused(bodies.bodiesById.get(EARTH)!);
	vis.updateCamera(0.002 * AU_SCALE, 2451545);
	return { bodies, vis };
}

const vname = (v: VISIBILITY) => VISIBILITY[v];
const dist = 0.002 * AU_SCALE;

describe('objects under a hidden layer', () => {
	it('are drawn when every layer is on', () => {
		const { bodies, vis } = buildScene(new LayerSet());
		expect(vname(vis.getMoonVisibility(bodies.bodiesById.get(MOON)!))).not.toBe(
			vname(VISIBILITY.HIDE)
		);
		expect(vname(vis.getPlanetVisibility(bodies.bodiesById.get(EARTH)!, dist))).not.toBe(
			vname(VISIBILITY.HIDE)
		);
	});

	it('hide their own kind', () => {
		const { bodies, vis } = buildScene(new LayerSet({ moons: false }));
		expect(vname(vis.getMoonVisibility(bodies.bodiesById.get(MOON)!))).toBe(vname(VISIBILITY.HIDE));
		expect(vname(vis.getPlanetVisibility(bodies.bodiesById.get(EARTH)!, dist))).not.toBe(
			vname(VISIBILITY.HIDE)
		);
	});

	it('hide the planets without touching the Sun', () => {
		const { bodies, vis } = buildScene(new LayerSet({ planets: false }));
		expect(vname(vis.getPlanetVisibility(bodies.bodiesById.get(EARTH)!, dist))).toBe(
			vname(VISIBILITY.HIDE)
		);
		expect(vname(vis.getPlanetVisibility(bodies.bodiesById.get(SUN)!, dist))).not.toBe(
			vname(VISIBILITY.HIDE)
		);
	});

	it('hide a probe under the spacecraft layer, not under the satellite one', () => {
		const probe = () => buildScene(new LayerSet({ spacecraft: false }));
		expect(
			vname(probe().vis.getPlanetVisibility(probe().bodies.bodiesById.get(PROBE)!, dist))
		).toBe(vname(VISIBILITY.HIDE));
		const kept = buildScene(new LayerSet({ satellites: false }));
		expect(vname(kept.vis.getPlanetVisibility(kept.bodies.bodiesById.get(PROBE)!, dist))).not.toBe(
			vname(VISIBILITY.HIDE)
		);
	});
});

describe('point clouds under a hidden layer', () => {
	it('follow the zone their objects came from', () => {
		const { bodies, vis } = buildScene(new LayerSet({ comets: false }));
		// The belts only draw from a solar view, with no planetary system
		// decluttering them away.
		vis.setFocused(bodies.bodiesById.get(SUN)!);
		vis.updateCamera(0.5 * AU_SCALE, 2451545);
		expect(vis.isAsteroidGroupVisible('small_bodies/JFC')).toBe(false);
		expect(vis.isAsteroidGroupVisible('small_bodies/MBA')).toBe(true);
	});

	it('go with the moons', () => {
		const on = buildScene(new LayerSet());
		expect(on.vis.isMoonGroupVisible('naif-3')).toBe(true);
		const off = buildScene(new LayerSet({ moons: false }));
		expect(off.vis.isMoonGroupVisible('naif-3')).toBe(false);
	});

	it('go with the spacecraft', () => {
		const off = buildScene(new LayerSet({ spacecraft: false }));
		expect(off.vis.isSpacecraftGroupVisible('naif-0')).toBe(false);
	});
});

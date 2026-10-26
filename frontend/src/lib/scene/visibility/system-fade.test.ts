import { describe, expect, it } from 'vitest';
import { ObjectType, type BodyData, type PositionedBody } from '$lib/types/objects';
import { OrbitalSource } from '$lib/fetch/position/format';
import { AU_SCALE } from '$lib/math/units';
import { BodyIndex } from '$lib/scene/state/bodies.svelte';
import { LayerSet } from '$lib/scene/layers';
import { VisibilityController } from './controller.svelte';
import { VISIBILITY } from './thresholds';
import {
	SYSTEM_IN_PX,
	SYSTEM_OUT_PX,
	systemDiameterPx,
	systemShown,
	systemShownWithin
} from './system-fade';

/**
 * Zoomed far out, only the Sun draws. The switch follows the solar system's
 * size on screen, and a focused or pinned body is hidden with the rest.
 */

const SUN = 'naif-10';
const EARTH = 'naif-399';
const MOON = 'naif-301';

function mkBody(data: Partial<BodyData> & Pick<BodyData, 'id'>): PositionedBody {
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
		position: [0, 0, 0]
	};
}

function buildScene() {
	const bodies = new BodyIndex();
	bodies.addBodies([
		mkBody({ id: SUN, name: 'Sun', objectType: ObjectType.STAR }),
		mkBody({ id: EARTH, name: 'Earth', parentId: 'naif-3', a: 1 }),
		mkBody({ id: MOON, name: 'Moon', objectType: ObjectType.MOON, parentId: 'naif-3', a: 0.00257 })
	]);
	const vis = new VisibilityController(
		bodies,
		() => null,
		() => null,
		() => null,
		() => new LayerSet()
	);
	vis.updateViewport(1080);
	vis.setFocused(bodies.bodiesById.get(EARTH)!);
	vis.updateCamera(0.002 * AU_SCALE, 2451545);
	return { bodies, vis };
}

const vname = (v: VISIBILITY) => VISIBILITY[v];

describe('the solar system on screen', () => {
	it("is 3 px across at Julie's zoom on a 1080 px view, where it is gone", () => {
		expect(systemDiameterPx(1.8455e5, 1080, 60)).toBeCloseTo(3.05, 2);
		expect(systemShown(1.8455e5, 1080, 60, true)).toBe(false);
	});

	it('goes under its switch, and comes back only a little larger', () => {
		expect(systemShown(1e3 * AU_SCALE, 1080, 60, false)).toBe(true);
		expect(systemShown(1e6, 1080, 60, true)).toBe(false);
		// Twice the size on screen is half the distance.
		const at = (px: number) => (1.8455e5 * 3.05) / px;
		const between = at(Math.sqrt(SYSTEM_OUT_PX * SYSTEM_IN_PX));
		expect(systemShown(between, 1080, 60, true)).toBe(true);
		expect(systemShown(between, 1080, 60, false)).toBe(false);
		expect(systemShown(at(SYSTEM_OUT_PX * 0.99), 1080, 60, true)).toBe(false);
		expect(systemShown(at(SYSTEM_IN_PX * 1.01), 1080, 60, false)).toBe(true);
	});

	it('switches at the same look on a taller view', () => {
		expect(systemShown(2 * 1.8455e5, 2160, 60, true)).toBe(false);
		expect(systemShown(1.8455e5 / 2, 2160, 60, false)).toBe(true);
	});
});

describe('only the Sun past the switch', () => {
	it('hides every body but the Sun, the focused one and a pinned one too', () => {
		const { bodies, vis } = buildScene();
		vis.setPinned([MOON]);
		vis.systemShare = 0;
		const d = 2e4 * AU_SCALE;
		expect(vname(vis.getPlanetVisibility(bodies.bodiesById.get(EARTH)!, d))).toBe('HIDE');
		expect(vname(vis.getPlanetVisibility(bodies.bodiesById.get(MOON)!, d))).toBe('HIDE');
		expect(vname(vis.getMoonVisibility(bodies.bodiesById.get(MOON)!))).toBe('HIDE');
		expect(vname(vis.getPlanetVisibility(bodies.bodiesById.get(SUN)!, d))).not.toBe('HIDE');
	});

	it('hides the clouds, and gives everything back below the switch', () => {
		const { bodies, vis } = buildScene();
		// Out of Earth's system, at a zone with no distance range of its own.
		vis.updateCamera(5 * AU_SCALE, 2451545);
		vis.systemShare = 0;
		expect(vis.isAsteroidGroupVisible('small_bodies/TEST')).toBe(false);
		expect(vis.isSpacecraftGroupVisible('naif-0')).toBe(false);
		vis.systemShare = 0.5;
		expect(vis.isAsteroidGroupVisible('small_bodies/TEST')).toBe(true);
		expect(vname(vis.getPlanetVisibility(bodies.bodiesById.get(EARTH)!, 5 * AU_SCALE))).not.toBe(
			'HIDE'
		);
	});
});

describe("another star's planetary system", () => {
	it('switches by its own outer orbit, at the same size on screen', () => {
		// Proxima c's 1.5 AU orbit at 1/20 of Neptune's distance from the switch.
		const neptune = 1.8455e5;
		const scale = 1.5 / 30.07;
		expect(systemDiameterPx(neptune * scale, 1080, 60, 1.5)).toBeCloseTo(3.05, 2);
		const within = systemShownWithin(1.5, 1080, 60);
		expect(systemDiameterPx(within, 1080, 60, 1.5)).toBeCloseTo(SYSTEM_IN_PX, 9);
		expect(systemShown(within * 0.99, 1080, 60, false, 1.5)).toBe(true);
		expect(systemShown(within * 1.01, 1080, 60, false, 1.5)).toBe(false);
	});

	it('takes a planet of another star out of the solar system zones, by its system share', () => {
		const { vis } = buildScene();
		const planet = mkBody({
			id: 'x-27424668-b-1',
			objectType: ObjectType.EXOPLANET,
			parentId: 'x-27424668',
			a: 0.0485
		});
		expect(vis.resolveSystemId(planet)).toBeNull();
		expect(vis.exoplanetShare(planet)).toBe(0);
		vis.systemShares = new Map([['x-27424668', 0.25]]);
		expect(vis.exoplanetShare(planet)).toBe(0.25);
		// It does not go with the Sun's own system.
		vis.systemShare = 0;
		expect(vis.exoplanetShare(planet)).toBe(0.25);
	});
});

import { describe, expect, it } from 'vitest';
import { ObjectType, type BodyData, type PositionedBody } from '$lib/types/objects';
import { OrbitalSource } from '$lib/fetch/position/format';
import { AU_SCALE } from '$lib/math/units';
import { BodyIndex } from '$lib/scene/state/bodies.svelte';
import { LayerSet } from '$lib/scene/layers';
import { VisibilityController } from './controller.svelte';
import { VISIBILITY } from './thresholds';
import { SYSTEM_FADE_PX, SYSTEM_HIDDEN_PX, systemDiameterPx, systemShare } from './system-fade';

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
	it("is 3 px across at Julie's zoom on a 1080 px view", () => {
		expect(systemDiameterPx(1.8455e5, 1080, 60)).toBeCloseTo(SYSTEM_HIDDEN_PX, 2);
		expect(systemShare(1.8455e5, 1080, 60)).toBe(0);
	});

	it('is whole until it shrinks to the fade, and gone past it', () => {
		expect(systemShare(1e3 * AU_SCALE, 1080, 60)).toBe(1);
		// Twice the size on screen is half the distance.
		const fadeStart = (1.8455e5 * SYSTEM_HIDDEN_PX) / SYSTEM_FADE_PX;
		expect(systemShare(fadeStart, 1080, 60)).toBeCloseTo(1, 4);
		expect(systemShare(Math.sqrt(fadeStart * 1.8455e5), 1080, 60)).toBeCloseTo(0.5, 2);
		expect(systemShare(1e6, 1080, 60)).toBe(0);
	});

	it('switches at the same look on a taller view', () => {
		expect(systemShare(2 * 1.8455e5, 2160, 60)).toBe(0);
		expect(systemShare(1.8455e5, 2160, 60)).toBeGreaterThan(0);
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

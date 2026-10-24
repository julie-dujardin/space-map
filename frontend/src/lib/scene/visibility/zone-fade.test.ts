import { describe, expect, it } from 'vitest';
import { ObjectType, type BodyData, type PositionedBody } from '$lib/types/objects';
import { OrbitalSource } from '$lib/fetch/position/format';
import { AU_SCALE } from '$lib/math/units';
import { BodyIndex } from '$lib/scene/state/bodies.svelte';
import { LayerSet } from '$lib/scene/layers';
import { VisibilityController } from './controller.svelte';
import { SYSTEM_SWITCH_FADE_MS } from './switch-fade';
import { ZoneFades } from './zone-fade';

const SUN = 'naif-10';
const EARTH = 'naif-399';
const MOON = 'naif-301';
const MARS = 'naif-499';
const EARTH_SYSTEM = 'naif-3';

describe('the zones of the view', () => {
	it('open on the zone the camera is in, with no fade', () => {
		const zones = new ZoneFades();
		zones.step(EARTH_SYSTEM, 16);
		expect(zones.mainShare).toBe(0);
		expect(zones.systems.map((s) => [s.id, s.fade.share])).toEqual([[EARTH_SYSTEM, 1]]);
		expect(zones.fading).toBe(false);
	});

	it('cross over when the camera enters a satellite system, and back', () => {
		const zones = new ZoneFades();
		zones.step(null, 16);
		zones.step(EARTH_SYSTEM, SYSTEM_SWITCH_FADE_MS / 4);
		const [earth] = zones.systems;
		expect(zones.mainShare).toBeGreaterThan(0.5);
		expect(zones.mainShare + earth.fade.share).toBeCloseTo(1, 12);
		expect(zones.fading).toBe(true);
		zones.step(EARTH_SYSTEM, SYSTEM_SWITCH_FADE_MS);
		expect(zones.mainShare).toBe(0);
		expect(earth.fade.share).toBe(1);
		expect(zones.fading).toBe(false);

		zones.step(null, SYSTEM_SWITCH_FADE_MS / 2);
		expect(zones.mainShare + earth.fade.share).toBeCloseTo(1, 12);
		zones.step(null, SYSTEM_SWITCH_FADE_MS / 2);
		expect(zones.mainShare).toBe(1);
		expect(zones.systems).toEqual([]);
	});
});

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

describe('what the zones draw', () => {
	const bodies = new BodyIndex();
	bodies.addBodies([
		mkBody({ id: SUN, name: 'Sun', objectType: ObjectType.STAR }),
		mkBody({ id: EARTH, name: 'Earth', parentId: EARTH_SYSTEM, a: 1 }),
		mkBody({
			id: MOON,
			name: 'Moon',
			objectType: ObjectType.MOON,
			parentId: EARTH_SYSTEM,
			a: 0.00257
		}),
		mkBody({ id: MARS, name: 'Mars', parentId: 'naif-4', a: 1.52 })
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
	const at = (au: number, dtMs: number) => {
		vis.updateCamera(au * AU_SCALE, 2451545);
		vis.stepZones(dtMs);
	};
	const earth = bodies.bodiesById.get(EARTH)!;
	const mars = bodies.bodiesById.get(MARS)!;

	it('hands the clouds and the other planets over to the system in a fade', () => {
		at(5, 16);
		expect(vis.asteroidGroupShare('small_bodies/TEST')).toBe(1);
		expect(vis.spacecraftGroupShare(EARTH)).toBe(0);

		at(0.002, SYSTEM_SWITCH_FADE_MS / 2);
		expect(vis.activeSystemId).toBe(EARTH_SYSTEM);
		expect(vis.asteroidGroupShare('small_bodies/TEST')).toBeCloseTo(0.5, 12);
		expect(vis.spacecraftGroupShare('naif-0')).toBeCloseTo(0.5, 12);
		expect(vis.spacecraftGroupShare(EARTH)).toBeCloseTo(0.5, 12);
		expect(vis.fullRenderingShare(mars)).toBeCloseTo(0.5, 12);
		expect(vis.hasFullRendering(mars)).toBe(true);
		// Earth stays whole because it belongs to both zones.
		expect(vis.fullRenderingShare(earth)).toBe(1);

		at(0.002, SYSTEM_SWITCH_FADE_MS / 2);
		expect(vis.isAsteroidGroupVisible('small_bodies/TEST')).toBe(false);
		expect(vis.isSpacecraftGroupVisible('naif-0')).toBe(false);
		expect(vis.spacecraftGroupShare(EARTH)).toBe(1);
		expect(vis.hasFullRendering(mars)).toBe(false);
		expect(vis.fullRenderingShare(earth)).toBe(1);
	});

	it('keeps a pinned body whole', () => {
		vis.setPinned([MARS]);
		expect(vis.fullRenderingShare(mars)).toBe(1);
		vis.setPinned([]);
	});
});

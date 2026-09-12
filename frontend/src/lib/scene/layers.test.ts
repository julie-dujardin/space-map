import { describe, it, expect } from 'vitest';
import { ObjectType, type BodyData, type PositionedBody } from '$lib/types/objects';
import { OrbitalSource } from '$lib/fetch/position/format';
import { EARTH_ID } from '$lib/constants';
import { bodyLayer, drawnSpacecraft, LayerSet, MAP_LAYERS, zoneLayer } from './layers';

/**
 * The layer set: which objects and which zones of the export answer to which
 * switch, and the difference between a layer left out before the map opens
 * (never fetched) and one switched off afterwards (hidden only).
 */

function mkBody(
	data: Partial<BodyData> & Pick<BodyData, 'id'>,
	pos: [number, number, number] = [0, 0, 0]
): PositionedBody {
	return {
		data: {
			name: null,
			objectType: ObjectType.SPACECRAFT,
			parentId: EARTH_ID,
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

describe('layer ids', () => {
	it('are unique and recognised', () => {
		expect(new Set(MAP_LAYERS).size).toBe(MAP_LAYERS.length);
		for (const id of MAP_LAYERS) expect(LayerSet.has(id)).toBe(true);
		expect(LayerSet.has('planet')).toBe(false);
	});
});

describe('the layer an object answers to', () => {
	it('sorts the object types', () => {
		expect(bodyLayer(ObjectType.PLANET, 'naif-0')).toBe('planets');
		expect(bodyLayer(ObjectType.DWARF_PLANET, 'naif-0')).toBe('dwarfPlanets');
		expect(bodyLayer(ObjectType.MOON, 'naif-499')).toBe('moons');
		expect(bodyLayer(ObjectType.COMET, 'naif-0')).toBe('comets');
		expect(bodyLayer(ObjectType.DEBRIS, EARTH_ID)).toBe('debris');
	});

	it('folds every asteroid family into one layer', () => {
		for (const type of [
			ObjectType.ASTEROID,
			ObjectType.ASTEROID_INNER,
			ObjectType.ASTEROID_MAIN_BELT,
			ObjectType.ASTEROID_TROJAN,
			ObjectType.ASTEROID_CENTAUR,
			ObjectType.ASTEROID_TNO
		]) {
			expect(bodyLayer(type, 'naif-0')).toBe('asteroids');
		}
	});

	it('splits spacecraft on what they orbit', () => {
		expect(bodyLayer(ObjectType.SPACECRAFT, EARTH_ID)).toBe('satellites');
		expect(bodyLayer(ObjectType.SPACECRAFT, 'naif-499')).toBe('spacecraft');
		expect(bodyLayer(ObjectType.SPACECRAFT, 'naif-0')).toBe('spacecraft');
	});

	it('leaves the Sun and the navigational marks to no layer, so they never hide', () => {
		expect(bodyLayer(ObjectType.STAR, 'naif-0')).toBeNull();
		expect(bodyLayer(ObjectType.BARYCENTER, 'naif-0')).toBeNull();
		expect(bodyLayer(ObjectType.LAGRANGE_POINT, 'naif-0')).toBeNull();
	});
});

describe('the layer a zone belongs to', () => {
	it('sorts the small-body classes the way the export types their records', () => {
		expect(zoneLayer('small_bodies/MBA')).toBe('asteroids');
		expect(zoneLayer('small_bodies/TNO')).toBe('asteroids');
		// Encke-type comets are written as trans-Neptunian records.
		expect(zoneLayer('small_bodies/ETc')).toBe('asteroids');
		expect(zoneLayer('small_bodies/JFC')).toBe('comets');
		// A hyperbolic asteroid is written as a comet record.
		expect(zoneLayer('small_bodies/HYA')).toBe('comets');
	});

	it('sorts the moons, the probes and the shared zones', () => {
		expect(zoneLayer('moons')).toBe('moons');
		expect(zoneLayer('moons/jupiter')).toBe('moons');
		expect(zoneLayer('small_body_moons')).toBe('moons');
		expect(zoneLayer('probes/interplanetary')).toBe('spacecraft');
		// The Sun, the planets and the dwarf planets share one file.
		expect(zoneLayer('major')).toBeNull();
		expect(zoneLayer('major_asteroids')).toBeNull();
		// Satellites and debris share one file; skipsZone weighs both.
		expect(zoneLayer('earth')).toBeNull();
	});
});

describe('a layer switched off before the map opens', () => {
	it('is not fetched', () => {
		const layers = new LayerSet({ asteroids: false });
		expect(layers.skipsZone('small_bodies/MBA')).toBe(true);
		expect(layers.skipsZone('small_bodies/JFC')).toBe(false);
		expect(layers.isVisible('asteroids')).toBe(false);
	});

	it('stays skipped after it is switched back on, having nothing to show', () => {
		const layers = new LayerSet({ moons: false });
		layers.setVisible('moons', true);
		expect(layers.isVisible('moons')).toBe(true);
		expect(layers.skipsZone('moons')).toBe(true);
	});

	it('leaves the Earth zone alone until neither its layers are wanted', () => {
		expect(new LayerSet({ debris: false }).skipsZone('earth')).toBe(false);
		expect(new LayerSet({ satellites: false }).skipsZone('earth')).toBe(false);
		expect(new LayerSet({ satellites: false, debris: false }).skipsZone('earth')).toBe(true);
	});
});

describe('a layer switched off while the map is open', () => {
	it('hides without skipping anything', () => {
		const layers = new LayerSet();
		layers.setVisible('comets', false);
		expect(layers.hidesZone('small_bodies/JFC')).toBe(true);
		expect(layers.skipsZone('small_bodies/JFC')).toBe(false);
	});

	it('reports the change once, and only on a change', () => {
		const layers = new LayerSet();
		let changes = 0;
		layers.onChange = () => changes++;
		layers.setVisible('orbits', false);
		layers.setVisible('orbits', false);
		expect(changes).toBe(1);
		layers.setVisible('orbits', true);
		expect(changes).toBe(2);
	});

	it('hides the bodies of its own kind and no others', () => {
		const layers = new LayerSet({ moons: false });
		expect(layers.hidesBody(ObjectType.MOON, 'naif-499')).toBe(true);
		expect(layers.hidesBody(ObjectType.PLANET, 'naif-0')).toBe(false);
		expect(layers.hidesBody(ObjectType.STAR, 'naif-0')).toBe(false);
	});
});

describe('the spacecraft point clouds', () => {
	const sat = mkBody({ id: 'sat-1' });
	const junk = mkBody({ id: 'debris-1', objectType: ObjectType.DEBRIS });
	const probe = mkBody({ id: 'probe-1', parentId: 'naif-499' });

	it('go whole where the group is of one kind', () => {
		const layers = new LayerSet({ spacecraft: false });
		expect(layers.hidesSpacecraftGroup('naif-499')).toBe(true);
		expect(drawnSpacecraft(layers, 'naif-499', [probe])).toEqual([probe]);
	});

	it('only go round Earth when neither the satellites nor the debris are wanted', () => {
		expect(new LayerSet({ satellites: false }).hidesSpacecraftGroup(EARTH_ID)).toBe(false);
		expect(new LayerSet({ satellites: false, debris: false }).hidesSpacecraftGroup(EARTH_ID)).toBe(
			true
		);
	});

	it('are repacked without the kind that is off', () => {
		const both = new LayerSet();
		expect(drawnSpacecraft(both, EARTH_ID, [sat, junk])).toEqual([sat, junk]);

		const noDebris = new LayerSet({ debris: false });
		expect(drawnSpacecraft(noDebris, EARTH_ID, [sat, junk])).toEqual([sat]);

		const noSats = new LayerSet({ satellites: false });
		expect(drawnSpacecraft(noSats, EARTH_ID, [sat, junk])).toEqual([junk]);
	});
});

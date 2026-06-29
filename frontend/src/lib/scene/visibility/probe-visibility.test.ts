import { describe, it, expect } from 'vitest';
import { ObjectType, type BodyData, type PositionedBody } from '$lib/types/objects';
import { OrbitalSource } from '$lib/fetch/position/format';
import { AU_SCALE } from '$lib/math/units';
import { BodyIndex } from '$lib/scene/state/bodies.svelte';
import { VisibilityController } from './controller.svelte';
import { VISIBILITY } from './thresholds';
import type { ProbeStore } from '$lib/fetch/position/probes/store';

/**
 * Probe visibility splits on whether the probe is captured, not on whether it's
 * inside a planet's Hill sphere. A flyby/cruise probe keeps a heliocentric fit,
 * so it stays a sun-orbiting body — visible in the solar view (and as the
 * focused body) even mid-encounter. A captured orbiter has no heliocentric fit
 * and stays moon-style: hidden in the solar view unless its system is focused.
 */

const SUN = 'naif-10';
const FLYBY = 'probe-1'; // transiting Jupiter's Hill sphere, heliocentric fit present
const CAPTURED = 'probe-2'; // bound around Mars, no heliocentric fit

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

const AU = (x: number): [number, number, number] => [x * AU_SCALE, 0, 0];

function buildScene(): { bodies: BodyIndex; vis: VisibilityController } {
	const bodies = new BodyIndex();
	bodies.addBodies([
		mkBody({ id: SUN, name: 'Sun', objectType: ObjectType.STAR, parentId: 'naif-0' }, AU(0)),
		mkBody(
			{
				id: 'naif-4',
				name: 'Mars barycenter',
				objectType: ObjectType.BARYCENTER,
				parentId: 'naif-0'
			},
			AU(1.5)
		),
		mkBody(
			{ id: 'naif-499', name: 'Mars', objectType: ObjectType.PLANET, parentId: 'naif-4' },
			AU(1.5)
		),
		// Flyby probe: 5 AU from the Sun, parent flipped to Jupiter for the encounter.
		mkBody(
			{
				id: FLYBY,
				name: 'Flyby',
				objectType: ObjectType.SPACECRAFT,
				parentId: 'naif-599',
				orbitalSource: OrbitalSource.SPICE_PROBE
			},
			AU(5)
		),
		// Captured orbiter: bound just above Mars.
		mkBody(
			{
				id: CAPTURED,
				name: 'Orbiter',
				objectType: ObjectType.SPACECRAFT,
				parentId: 'naif-499',
				orbitalSource: OrbitalSource.SPICE_PROBE
			},
			[1.5 * AU_SCALE + 0.0001 * AU_SCALE, 0, 0]
		)
	]);

	// Flyby has a heliocentric fit while inside Jupiter's Hill sphere (sys 5);
	// the captured orbiter is only in the Mars zone (sys 4), no heliocentric fit.
	const probeStore = {
		containingSystemAt: (id: string) => (id === FLYBY ? 5 : id === CAPTURED ? 4 : null),
		hasHeliocentricFit: (id: string) => id === FLYBY
	} as unknown as ProbeStore;

	const vis = new VisibilityController(bodies, () => probeStore);
	vis.updateViewport(954);
	return { bodies, vis };
}

const vname = (v: VISIBILITY) => VISIBILITY[v];

describe('probe visibility — flyby vs captured', () => {
	it('a flyby probe stays visible in the solar view mid-encounter', () => {
		const { bodies, vis } = buildScene();
		vis.setFocused(bodies.bodiesById.get(SUN)!); // solar view, focused system null
		vis.updateCamera(10 * AU_SCALE, 2451545);
		const flyby = bodies.bodiesById.get(FLYBY)!;
		expect(vname(vis.getPlanetVisibility(flyby, 10 * AU_SCALE))).toBe(vname(VISIBILITY.FULL));
	});

	it('a captured orbiter stays hidden in the solar view', () => {
		const { bodies, vis } = buildScene();
		vis.setFocused(bodies.bodiesById.get(SUN)!);
		vis.updateCamera(10 * AU_SCALE, 2451545);
		const captured = bodies.bodiesById.get(CAPTURED)!;
		expect(vname(vis.getPlanetVisibility(captured, 10 * AU_SCALE))).toBe(vname(VISIBILITY.HIDE));
	});

	it('a focused flyby probe is not hidden at its default (wide) framing', () => {
		const { bodies, vis } = buildScene();
		const flyby = bodies.bodiesById.get(FLYBY)!;
		vis.setFocused(flyby); // focuses the probe; framing sits well outside the planet
		vis.updateCamera(1.5 * AU_SCALE, 2451545);
		expect(vname(vis.getPlanetVisibility(flyby, 1.5 * AU_SCALE))).toBe(vname(VISIBILITY.FULL));
	});

	it('a captured orbiter is visible once its own system is focused', () => {
		const { bodies, vis } = buildScene();
		const captured = bodies.bodiesById.get(CAPTURED)!;
		vis.setFocused(captured); // focused system resolves to Mars (naif-4)
		vis.updateCamera(0.0001 * AU_SCALE, 2451545);
		expect(vname(vis.getPlanetVisibility(captured, 0.0001 * AU_SCALE))).toBe(
			vname(VISIBILITY.FULL)
		);
	});
});

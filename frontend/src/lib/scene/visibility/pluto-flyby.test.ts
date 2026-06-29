import { describe, it, expect } from 'vitest';
import { ObjectType, type BodyData, type PositionedBody } from '$lib/types/objects';
import { OrbitalSource } from '$lib/fetch/position/format';
import { AU_SCALE } from '$lib/math/units';
import { BodyIndex } from '$lib/scene/state/bodies.svelte';
import { VisibilityController } from './controller.svelte';
import { VISIBILITY } from './thresholds';
import type { ProbeStore } from '$lib/fetch/position/probes/store';

/**
 * New Horizons / Pluto flyby visibility.
 *
 * Pluto's parent is the Pluto-Charon barycenter, so `getPlanetVisibility` scores
 * it on the sun-orbiting branch against the barycenter's ~39.6 AU `a` (its moons
 * score against their ~1e-4 AU orbits). That ratio reaches CLOSE while Pluto's
 * disc is still sub-pixel, so this gate must stay at FULL and leave the
 * halo→mesh handoff to the pixel cull — otherwise the halo drops with no visible
 * mesh and Pluto disappears mid-approach while its moons render.
 *
 * `a` values, radii, viewport (954px) and `hideThresholdAU` (≈8.716e-4) come
 * from a live `debugBody(...)` capture, so these enums match the running app.
 */

const FLYBY_JD = 2457217.99; // 2015-07-14 ~11:49 UTC, closest approach
const PLUTO_SYS = 'naif-9'; // Pluto-Charon barycenter = system root
const NH = 'probe-104804352';

/** Build a PositionedBody with all required fields defaulted. */
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

/** New Horizons sits 12,495 km from Pluto at closest approach. */
const NH_KM_FROM_PLUTO = 12495;
const NH_SCENE_X = (NH_KM_FROM_PLUTO / 1.495978707e8) * AU_SCALE;

function buildScene(): { bodies: BodyIndex; vis: VisibilityController } {
	const bodies = new BodyIndex();
	bodies.addBodies([
		// Pluto-Charon barycenter — heliocentric orbit (~39.6 AU).
		mkBody({
			id: PLUTO_SYS,
			name: 'Pluto barycenter',
			objectType: ObjectType.BARYCENTER,
			parentId: 'naif-0',
			a: 39.563429654476735,
			e: 0.250037
		}),
		// Pluto itself — tiny barycentric wobble, but a DWARF_PLANET with a mesh.
		mkBody({
			id: 'naif-999',
			name: 'Pluto',
			objectType: ObjectType.DWARF_PLANET,
			parentId: PLUTO_SYS,
			a: 0.000007129760610153935,
			e: 0.998713,
			radiusKm: 1188.3
		}),
		// The five moons — scored on their own ~1e-4 AU orbits (Hydra outermost).
		mkBody({
			id: 'naif-901',
			name: 'Charon',
			objectType: ObjectType.MOON,
			parentId: PLUTO_SYS,
			a: 0.00009035074510242655,
			radiusKm: 606
		}),
		mkBody({
			id: 'naif-902',
			name: 'Nix',
			objectType: ObjectType.MOON,
			parentId: PLUTO_SYS,
			a: 0.0003279449915840263,
			radiusKm: 24.2
		}),
		mkBody({
			id: 'naif-905',
			name: 'Styx',
			objectType: ObjectType.MOON,
			parentId: PLUTO_SYS,
			a: 0.00028932208467258286,
			radiusKm: 100
		}),
		mkBody({
			id: 'naif-904',
			name: 'Kerberos',
			objectType: ObjectType.MOON,
			parentId: PLUTO_SYS,
			a: 0.0003884090171082936,
			radiusKm: 100
		}),
		mkBody({
			id: 'naif-903',
			name: 'Hydra',
			objectType: ObjectType.MOON,
			parentId: PLUTO_SYS,
			a: 0.0004358200561091826,
			radiusKm: 26
		}),
		// New Horizons — flyby probe parented to Pluto, 12,495 km out.
		mkBody(
			{
				id: NH,
				name: 'New Horizons',
				objectType: ObjectType.SPACECRAFT,
				parentId: 'naif-999',
				loadParentId: 'naif-999',
				a: 0,
				radiusKm: 0.00137,
				orbitalSource: OrbitalSource.SPICE_PROBE
			},
			[NH_SCENE_X, 0, 0]
		)
	]);

	// Minimal ProbeStore: New Horizons reads as "inside Pluto's system" (NAIF 9)
	// during the encounter, which is what drives focusedSystem when it's focused.
	const probeStore = {
		containingSystemAt: (id: string) => (id === NH ? 9 : null)
	} as unknown as ProbeStore;

	const vis = new VisibilityController(bodies, () => probeStore);
	vis.updateViewport(954); // repro capture viewport → scaledPlanetary/System
	vis.setFocused(bodies.bodiesById.get(NH)!); // focus the probe, NOT Pluto
	return { bodies, vis };
}

/** Drive the camera to `camDistAU` and recompute per-frame visibility state. */
function atDistance(vis: VisibilityController, camDistAU: number): void {
	vis.updateCamera(camDistAU * AU_SCALE, FLYBY_JD);
}

const vname = (v: VISIBILITY) => VISIBILITY[v];

describe('Pluto flyby visibility', () => {
	it('focusing New Horizons sets the focused system to the Pluto barycenter', () => {
		const { vis } = buildScene();
		atDistance(vis, 0.0004);
		const d = vis.debugBody('naif-999')!;
		expect(d.focusedSystemId).toBe(PLUTO_SYS);
	});

	it('reproduces the live hideThresholdAU (≈8.716e-4 = 2× Hydra a)', () => {
		const { vis } = buildScene();
		atDistance(vis, 0.0004);
		const d = vis.debugBody('naif-999')!;
		expect(d.hideThresholdAU).toBeCloseTo(0.0008716401, 9);
	});

	// camAU → expected tiers for Pluto + inner/outer moon. Pluto stays FULL at
	// every distance (the disc-vs-halo handoff is the pixel cull's job); moon
	// tiers match the live capture.
	const cases: Array<{
		camAU: number;
		pluto: VISIBILITY;
		charon: VISIBILITY;
		hydra: VISIBILITY;
		zoomed: boolean;
	}> = [
		// Far solar view: Pluto halo, moons gone.
		{
			camAU: 1.5,
			pluto: VISIBILITY.FULL,
			charon: VISIBILITY.HIDE,
			hydra: VISIBILITY.HIDE,
			zoomed: false
		},
		// Mid-band: Pluto halo holds, moons still off.
		{
			camAU: 0.05,
			pluto: VISIBILITY.FULL,
			charon: VISIBILITY.HIDE,
			hydra: VISIBILITY.HIDE,
			zoomed: false
		},
		// Closer: Pluto halo, outer moon entering as a point.
		{
			camAU: 0.006,
			pluto: VISIBILITY.FULL,
			charon: VISIBILITY.HIDE,
			hydra: VISIBILITY.FAR,
			zoomed: false
		},
		// Deep zoom: Pluto + all moons drawn; Pluto's halo yields to its mesh in the cull.
		{
			camAU: 0.0004,
			pluto: VISIBILITY.FULL,
			charon: VISIBILITY.FULL,
			hydra: VISIBILITY.FULL,
			zoomed: true
		}
	];

	for (const c of cases) {
		it(`camera ${c.camAU} AU → Pluto ${vname(c.pluto)}, Charon ${vname(c.charon)}, Hydra ${vname(c.hydra)}`, () => {
			const { bodies, vis } = buildScene();
			atDistance(vis, c.camAU);
			const pluto = bodies.bodiesById.get('naif-999')!;
			const charon = bodies.bodiesById.get('naif-901')!;
			const hydra = bodies.bodiesById.get('naif-903')!;
			expect(vname(vis.getPlanetVisibility(pluto, c.camAU * AU_SCALE))).toBe(vname(c.pluto));
			expect(vname(vis.getMoonVisibility(charon))).toBe(vname(c.charon));
			expect(vname(vis.getMoonVisibility(hydra))).toBe(vname(c.hydra));
			expect(vis.debugBody('naif-999')!.isZoomedIn).toBe(c.zoomed);
		});
	}

	// Pluto must never hit CLOSE (which drops its halo while the disc is still
	// sub-pixel) at any distance along the approach — only the rendered disc
	// ever replaces the halo.
	it('Pluto never flips to CLOSE across the whole approach', () => {
		const { bodies, vis } = buildScene();
		const pluto = bodies.bodiesById.get('naif-999')!;
		for (let camAU = 2.0; camAU >= 1e-4; camAU *= 0.8) {
			atDistance(vis, camAU);
			expect(vname(vis.getPlanetVisibility(pluto, camAU * AU_SCALE))).not.toBe(
				vname(VISIBILITY.CLOSE)
			);
		}
	});
});

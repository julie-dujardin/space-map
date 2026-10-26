import { describe, expect, it } from 'vitest';
import { PlanetIndex } from '$lib/fetch/extrasolar/planets';
import { treeToScene } from '$lib/scene/starfield/tree';
import { SYSTEM_SWITCH_FADE_MS } from '$lib/scene/visibility/switch-fade';
import { systemShownWithin } from '$lib/scene/visibility/system-fade';
import type { Vec3 } from '$lib/scene/animation/math';
import { NO_ORBIT_AU } from './bodies';
import { SystemFades, type SystemStep } from './fades';
import { INDEX } from './__fixtures__/system';

/** A system draws while its outer orbit is a few pixels across, and fades. */

const PROXIMA = 27424668;
const TOLIMAN = 564339647;
const PULSAR = 1091633172;
const VIEW = { viewportPx: 1080, fovDeg: 60 };

function placeOf(id: number): Vec3 {
	const [x, y, z] = INDEX.hosts.find((h) => h.id === id)!.position!;
	const at = treeToScene(x, y, z, { x: 0, y: 0, z: 0 });
	return [at.x, at.y, at.z];
}

/** The camera `distance` scene units from `id`, along +x. */
function step(id: number, distance: number, extra: Partial<SystemStep> = {}): SystemStep {
	const at = placeOf(id);
	return {
		camera: [at[0] + distance, at[1], at[2]],
		...VIEW,
		dtMs: SYSTEM_SWITCH_FADE_MS,
		outside: 1,
		hosts: [PROXIMA, TOLIMAN, PULSAR],
		ready: () => true,
		...extra
	};
}

describe('SystemFades', () => {
	const within = systemShownWithin(1.5, VIEW.viewportPx, VIEW.fovDeg);

	it('shows a system closer than its switch, fading in over the switch time', () => {
		const fades = new SystemFades(new PlanetIndex(INDEX));
		const half = fades.step({ ...step(PROXIMA, within / 2), dtMs: SYSTEM_SWITCH_FADE_MS / 2 });
		expect(half.get(PROXIMA)).toBeCloseTo(0.5, 9);
		expect(fades.fading).toBe(true);
		const full = fades.step(step(PROXIMA, within / 2));
		expect(full.get(PROXIMA)).toBe(1);
		expect(fades.fading).toBe(false);
	});

	it('keeps its state between the two switch sizes', () => {
		const fades = new SystemFades(new PlanetIndex(INDEX));
		// 4.5 px: between the switch-off 4.3 and the switch-on 4.75.
		const between = (within * 4.75) / 4.5;
		expect(fades.step(step(PROXIMA, between)).has(PROXIMA)).toBe(false);
		fades.step(step(PROXIMA, within / 2));
		expect(fades.step(step(PROXIMA, between)).get(PROXIMA)).toBe(1);
		expect(fades.step(step(PROXIMA, within * 2)).has(PROXIMA)).toBe(false);
	});

	it('counts a host with no orbits as the stand-in span', () => {
		const fades = new SystemFades(new PlanetIndex(INDEX));
		const stand = systemShownWithin(NO_ORBIT_AU, VIEW.viewportPx, VIEW.fovDeg);
		expect(fades.step(step(TOLIMAN, stand * 0.9)).get(TOLIMAN)).toBe(1);
		expect(fades.step(step(TOLIMAN, stand * 1.2)).has(TOLIMAN)).toBe(false);
	});

	it('draws nothing in the solar system, for a host with no place, or not ready', () => {
		const fades = new SystemFades(new PlanetIndex(INDEX));
		expect(fades.step(step(PROXIMA, within / 2, { outside: 0 })).size).toBe(0);
		expect(fades.step(step(PROXIMA, within / 2, { ready: () => false })).size).toBe(0);
		expect(fades.step(step(PROXIMA, within / 2, { hosts: [PULSAR] })).size).toBe(0);
		// Half out of the solar system: half the share.
		fades.step(step(PROXIMA, within / 2));
		expect(fades.step(step(PROXIMA, within / 2, { outside: 0.5 })).get(PROXIMA)).toBe(0.5);
	});

	it('fades out a host that may no longer draw', () => {
		const fades = new SystemFades(new PlanetIndex(INDEX));
		fades.step(step(PROXIMA, within / 2));
		const fading = fades.step({ ...step(PROXIMA, within / 2, { hosts: [] }), dtMs: 100 });
		expect(fading.get(PROXIMA)).toBeGreaterThan(0);
		expect(fading.get(PROXIMA)).toBeLessThan(1);
		expect(fades.step(step(PROXIMA, within / 2, { hosts: [] })).size).toBe(0);
		expect(fades.fading).toBe(false);
	});
});

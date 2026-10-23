/**
 * The opacity of the point clouds under the system fade and the filter
 * emphasis together.
 */

import { describe, expect, it, vi } from 'vitest';
import { BufferGeometry, Points, PointsMaterial, Scene, type CanvasTexture } from 'three';
import { EARTH_ID } from '$lib/constants';
import type { FocusState } from '$lib/scene/animation/focus';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';

const ZONE = 'small_bodies/tno';

let built: {
	asteroidPoints: Map<string, Points>;
	spacecraftPoints: Map<string, Points>;
	moonPoints: Map<string, Points>;
};

vi.mock('$lib/math/orbit/pool', () => ({
	OrbitWorkerPool: class {
		workerCount = 2;
		setResultHandler(): void {}
		destroy(): void {}
	}
}));
vi.mock('$lib/scene/objects/body/bulk', () => ({ buildPointClouds: () => built }));

const { PointCloudSystem } = await import('./system');

const cloud = () => new Points(new BufferGeometry(), new PointsMaterial());
const opacity = (pts: Points) => (pts.material as PointsMaterial).opacity;

function system(): {
	clouds: InstanceType<typeof PointCloudSystem>;
	sats: Points;
	tnos: Points;
	moons: Points;
} {
	const sats = cloud();
	const tnos = cloud();
	const moons = cloud();
	built = {
		asteroidPoints: new Map([[`${ZONE}#0`, tnos]]),
		spacecraftPoints: new Map([[`${EARTH_ID}#0`, sats]]),
		moonPoints: new Map([['naif-599', moons]])
	};
	const clouds = new PointCloudSystem(
		{} as ContextManager,
		new Scene(),
		new Map(),
		null as unknown as CanvasTexture,
		{} as FocusState,
		1,
		() => {}
	);
	clouds.buildInitial(new Set());
	return { clouds, sats, tnos, moons };
}

describe('point cloud opacity', () => {
	it('fades every cloud and gives the opacity back', () => {
		const { clouds, sats, tnos, moons } = system();
		clouds.setFade(0.25);
		expect([opacity(sats), opacity(tnos), opacity(moons)]).toEqual([0.25, 0.25, 0.25]);
		clouds.setFade(1);
		expect([opacity(sats), opacity(tnos), opacity(moons)]).toEqual([1, 1, 1]);
	});

	it('keeps an emphasis set while faded', () => {
		const { clouds, sats } = system();
		clouds.setFade(0.5);
		clouds.setEarthSatEmphasis(50);
		expect(opacity(sats)).toBeCloseTo(3.5 * 0.5);
		clouds.setFade(1);
		expect(opacity(sats)).toBeCloseTo(3.5);
	});

	it('does not give back an emphasis cleared while faded', () => {
		const { clouds, tnos } = system();
		clouds.setEmphasizedSmallBodyZone(ZONE, 50);
		clouds.setFade(0.5);
		expect(opacity(tnos)).toBeCloseTo(3.5 * 0.5);
		clouds.setEmphasizedSmallBodyZone(null, null);
		expect(opacity(tnos)).toBeCloseTo(0.5);
		clouds.setFade(1);
		expect(opacity(tnos)).toBe(1);
	});
});

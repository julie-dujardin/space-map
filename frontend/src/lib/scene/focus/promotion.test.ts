import { describe, it, expect, vi, beforeEach } from 'vitest';
import { ObjectType, type BodyData, type PositionedBody } from '$lib/types/objects';
import { OrbitalSource } from '$lib/fetch/position/format';
import { EARTH_ID } from '$lib/constants';
import { PromotionRegistry, type PromotionDeps } from './promotion';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
import type { PointCloudSystem } from '$lib/scene/pointclouds/system';

vi.mock('$lib/fetch/position/labels', () => ({ fetchLabels: () => Promise.resolve(new Map()) }));

/**
 * Earth-sat cloud emphasis ramps off the count of members valid at the sim
 * time. That count changes with the clock alone. A scrub across a snapshot's
 * validity window loads no data. The registry must recount on sim-time
 * changes, not only on chunk flushes and rollovers.
 */

/** Snapshot validity window: the whole Earth zone shares the file header's bounds. */
const WINDOW_START = 2461217.6;
const WINDOW_END = 2461273.9;
const MEMBERS = 600;

function mkSat(id: string): PositionedBody {
	const data: BodyData = {
		id,
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
		epoch: WINDOW_START,
		radiusKm: 0,
		hasLocalized: false,
		validityStart: WINDOW_START,
		validityEnd: WINDOW_END,
		orbitalSource: OrbitalSource.CELESTRAK
	};
	return { data, position: [0, 0, 0] };
}

function buildRegistry(jd: number) {
	const bucket = new Map<string, PositionedBody>();
	for (let i = 0; i < MEMBERS; i++) bucket.set(`sat-${i}`, mkSat(`sat-${i}`));
	const clock = { jd };
	const setEarthSatEmphasis = vi.fn();
	const ctx = {
		bodies: {
			spacecraftByParent: new Map([[EARTH_ID, bucket]]),
			asteroidBodiesByZone: new Map(),
			dirtySpacecraftGroups: new Set<string>(),
			onBodiesAdded: () => () => {}
		},
		onEarthSatRollover: () => () => {},
		onGroupFilterChange: () => () => {},
		onSmallBodyFilterChange: () => () => {},
		earthSatFilter: null,
		smallBodyFilter: null,
		getBody: () => undefined
	} as unknown as ContextManager;
	const pointClouds = {
		setEarthSatEmphasis,
		setEmphasizedSmallBodyZone: vi.fn(),
		rebuildMinor: vi.fn()
	} as unknown as PointCloudSystem;
	const deps = {
		bodyObjects: new Map(),
		ctx,
		clock,
		pointClouds,
		getFocusedId: () => undefined
	} as unknown as PromotionDeps;
	return { registry: new PromotionRegistry(deps), clock, setEarthSatEmphasis };
}

describe('earth-sat emphasis across sim time', () => {
	let harness: ReturnType<typeof buildRegistry>;

	beforeEach(() => {
		// Loaded past the snapshot's validity window: nothing is observable.
		harness = buildRegistry(WINDOW_END + 15);
	});

	it('counts nothing outside the validity window', () => {
		harness.registry.onSimTimeChanged();
		expect(harness.setEarthSatEmphasis).toHaveBeenLastCalledWith(0);
	});

	it('recounts when the clock scrubs back into the window', () => {
		harness.registry.onSimTimeChanged();
		harness.clock.jd = WINDOW_START + 1;
		harness.registry.onSimTimeChanged();
		expect(harness.setEarthSatEmphasis).toHaveBeenLastCalledWith(MEMBERS);
	});

	it('skips the walk while the clock stays inside the counted bracket', () => {
		harness.clock.jd = WINDOW_START + 1;
		harness.registry.onSimTimeChanged();
		harness.setEarthSatEmphasis.mockClear();
		harness.clock.jd = WINDOW_START + 2;
		harness.registry.onSimTimeChanged();
		expect(harness.setEarthSatEmphasis).not.toHaveBeenCalled();
	});
});

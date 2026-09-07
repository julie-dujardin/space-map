import { describe, it, expect, vi, beforeEach } from 'vitest';
import { ObjectType, type BodyData, type PositionedBody } from '$lib/types/objects';
import { OrbitalSource } from '$lib/fetch/position/format';
import { EARTH_ID } from '$lib/constants';
import { PromotionRegistry, type PromotionDeps } from './promotion';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
import type { PointCloudSystem } from '$lib/scene/pointclouds/system';
import { MinorBucket } from '$lib/fetch/position/minor-columns';

vi.mock('$lib/fetch/position/labels', () => ({ fetchLabels: () => Promise.resolve(new Map()) }));

vi.mock('$lib/scene/objects/body/lifecycle', () => ({
	buildMajorBodies: (bodies: PositionedBody[], ...rest: unknown[]) => {
		const bodyObjects = rest[3] as Map<string, unknown>;
		for (const b of bodies) bodyObjects.set(b.data.id, { body: { position: [0, 0, 0] } });
	},
	disposeMaterial: () => {}
}));
vi.mock('$lib/scene/objects/body/bulk', () => ({ buildTrails: () => {} }));
vi.mock('$lib/scene/objects/body/textures', () => ({
	loadBodyLabel: () => {},
	unloadBodyTexture: () => {}
}));
vi.mock('$lib/scene/minor-body-position', () => ({ refreshMinorBodyPosition: () => {} }));

// Earth-sat emphasis ramps off members valid at sim time; scrubbing across a
// snapshot's validity window loads no data, so the registry must recount on
// sim-time changes alone, not only on chunk flushes and rollovers.

/** Snapshot validity window: the whole Earth zone shares the file header's bounds. */
const WINDOW_START = 2461217.6;
const WINDOW_END = 2461273.9;
const MEMBERS = 600;

function mkBody(data: Partial<BodyData> & Pick<BodyData, 'id'>): PositionedBody {
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
			epoch: WINDOW_START,
			radiusKm: 0,
			hasLocalized: false,
			validityStart: WINDOW_START,
			validityEnd: WINDOW_END,
			orbitalSource: OrbitalSource.CELESTRAK,
			...data
		},
		position: [0, 0, 0]
	};
}

function buildRegistry(jd: number) {
	const bucket = new Map<string, PositionedBody>();
	for (let i = 0; i < MEMBERS; i++) bucket.set(`sat-${i}`, mkBody({ id: `sat-${i}` }));
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

describe('asteroid-moon auto-promotion', () => {
	/** `31 Euphrosyne` is in MINOR_PROMOTED_IDS; `22 Kalliope` is in neither
	 *  curated set, standing in for the hundreds of belt and TNO binaries. */
	const CURATED_HOST = 'spkid-20000031';
	const PLAIN_HOST = 'spkid-20000022';

	async function promotedIds(): Promise<Set<string>> {
		const hosts = new Map(
			[CURATED_HOST, PLAIN_HOST].map((id) => [
				id,
				mkBody({ id, objectType: ObjectType.ASTEROID_MAIN_BELT, parentId: 'naif-10' })
			])
		);
		const moons = new MinorBucket(new Map());
		moons.addPlaceholder(
			mkBody({ id: 'spkid-120000031', objectType: ObjectType.MOON, parentId: CURATED_HOST })
		);
		moons.addPlaceholder(
			mkBody({ id: 'spkid-120000022', objectType: ObjectType.MOON, parentId: PLAIN_HOST })
		);
		const ctx = {
			bodies: {
				spacecraftByParent: new Map(),
				asteroidBodiesByZone: new Map([['small_body_moons', moons]]),
				dirtySpacecraftGroups: new Set<string>(),
				dirtyAsteroidZones: new Set<string>(),
				findAsteroidZone: () => 'small_body_moons',
				onBodiesAdded: () => () => {}
			},
			onEarthSatRollover: () => () => {},
			onGroupFilterChange: () => () => {},
			onSmallBodyFilterChange: () => () => {},
			earthSatFilter: null,
			smallBodyFilter: null,
			getBody: (id: string) => hosts.get(id)
		} as unknown as ContextManager;
		const bodyObjects = new Map<string, unknown>();
		new PromotionRegistry({
			bodyObjects,
			ctx,
			clock: { jd: WINDOW_START + 1 },
			pointClouds: {
				setEarthSatEmphasis: vi.fn(),
				setEmphasizedSmallBodyZone: vi.fn(),
				rebuildMinor: vi.fn(),
				basis: () => null
			},
			// Read before the mocked buildMajorBodies sees it.
			renderer: { domElement: {} },
			assignMapLayerToTrails: () => {},
			repositionAll: () => {},
			getFocusedId: () => undefined
		} as unknown as PromotionDeps);
		// The only sweep runs once fetchLabels resolves.
		await Promise.resolve();
		return new Set(bodyObjects.keys());
	}

	it('promotes a moon and its host only when the host is curated', async () => {
		expect(await promotedIds()).toEqual(new Set([CURATED_HOST, 'spkid-120000031']));
	});
});

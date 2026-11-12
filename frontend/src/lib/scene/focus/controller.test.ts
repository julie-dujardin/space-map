import { describe, it, expect, vi } from 'vitest';
import { PerspectiveCamera, Quaternion, Vector3 } from 'three';
import { ObjectType, type BodyData, type PositionedBody } from '$lib/types/objects';
import { OrbitalSource } from '$lib/fetch/position/format';
import { sphericalToCartesian } from '$lib/math/spherical';
import { LEVEL_LOOK } from '$lib/scene/camera/look-controls';
import type { Vec3 } from '$lib/scene/animation/math';
import type { BodyObjects } from '$lib/scene/types';
import { FocusController, type FocusDeps } from './controller';
import type { PromotionDeps } from './promotion';

const landed = vi.hoisted(() => ({ now: true }));
/** The spin the IAU angles give the host: a quarter turn about the pole. */
const SPIN = vi.hoisted(() => [0, Math.SQRT1_2, 0, Math.SQRT1_2] as const);

vi.mock('./promotion', () => ({
	PromotionRegistry: class {
		constructor(readonly deps: PromotionDeps) {}
		ensureBodyObjects() {}
		emitUserPromotedCount() {}
	}
}));
vi.mock('$lib/scene/objects/body/lifecycle', () => ({
	downgradeBodyMesh: () => {},
	isMeshUpgradable: () => false,
	upgradeBodyMesh: () => {}
}));
vi.mock('$lib/scene/objects/body/model', async (importOriginal) => ({
	...(await importOriginal<typeof import('$lib/scene/objects/body/model')>()),
	unloadBodyModel: () => {}
}));
vi.mock('$lib/scene/objects/surface/nomenclature', () => ({ disposeNomenclatureLabels: () => {} }));
vi.mock('$lib/scene/objects/body/bulk', () => ({ buildTrails: () => {} }));
vi.mock('$lib/scene/settings.svelte', () => ({
	sceneSettings: () => ({ resolvedReducedMotion: false })
}));
vi.mock('$lib/scene/position/rendered-surface', () => ({ surfaceDataEpoch: () => 0 }));
vi.mock('$lib/scene/visibility/camera-limits', () => ({ minCameraDistance: () => 0.01 }));
vi.mock('$lib/fetch/position/probes/propagate', () => ({ isLandedAt: () => landed.now }));
vi.mock('$lib/math/orientation', () => ({
	bodyQuaternion: () => new Quaternion(...SPIN)
}));

function mkBody(data: Partial<BodyData> & Pick<BodyData, 'id'>, position: Vec3): PositionedBody {
	return {
		data: {
			name: null,
			objectType: ObjectType.PLANET,
			parentId: 'naif-10',
			a: 0,
			e: 0,
			i: 0,
			om: 0,
			w: 0,
			ma: 0,
			n: 0,
			epoch: 0,
			radiusKm: 3390,
			hasLocalized: false,
			validityStart: 0,
			validityEnd: Infinity,
			orbitalSource: OrbitalSource.SPICE,
			...data
		},
		position
	};
}

const MARS_AT: Vec3 = [1000, 0, 0];
/** Where the rover stands, off Mars' centre in its own axes. */
const SITE = { latitude: 10, longitude: 20, radius: 1 };

function harness({ spun }: { spun: boolean }) {
	const mars = mkBody({ id: 'naif-499' }, MARS_AT);
	if (spun) mars.orientation = {} as PositionedBody['orientation'];
	const quat = spun ? [...SPIN] : undefined;
	const seat = sphericalToCartesian(
		MARS_AT,
		SITE.latitude,
		SITE.longitude,
		SITE.radius,
		quat as [number, number, number, number] | undefined
	);
	const rover = mkBody(
		{ id: 'curiosity', objectType: ObjectType.SPACECRAFT, parentId: 'naif-499' },
		seat
	);
	const earth = mkBody({ id: 'naif-399' }, [0, 0, 0]);
	const bodies = new Map([mars, rover, earth].map((b) => [b.data.id, b]));
	/** Where the scene places each body; a probe that lifts off moves. */
	const placed = new Map(bodies.entries().map(([id, b]) => [id, b.position]));
	const bodyObjects = new Map<string, BodyObjects>();
	// A mesh fresh from an upgrade: no spin applied yet.
	for (const b of [mars, earth]) {
		bodyObjects.set(b.data.id, { body: b, mesh: { quaternion: new Quaternion() } } as BodyObjects);
	}
	const onFocusChange = vi.fn();
	const camera = new PerspectiveCamera();
	const deps = {
		ctx: {
			getBody: (id: string) => bodies.get(id),
			place: (b: PositionedBody) => placed.get(b.data.id),
			visibility: { setFocused: () => {} },
			probeStore: {
				probeWithCenter: (id: string) =>
					id === rover.data.id ? { probe: { landed: { bodyNaifId: 499 } } } : undefined
			}
		},
		clock: { jd: 2460000 },
		camera,
		controls: {
			look: LEVEL_LOOK,
			update: () => {},
			setLook: () => {},
			looksOver: () => false,
			groundAlong: () => false
		},
		bodyObjects,
		callbacks: { onFocusChange },
		focus: {
			focusTruePos: [0, 0, 0],
			focusOriginWorld: [0, 0, 0],
			focusTargetWorld: [0, 0, 0],
			camOriginWorld: null,
			camTargetWorld: null,
			camTargetOffset: null,
			camOriginOffset: null,
			flyQ0: null,
			orbitFly: false,
			arcOrbit: false,
			cameraStaysOnBody: false,
			leavesAim: false,
			aim: null,
			aimLooks: false,
			aimPose: null,
			focusStartTime: 0,
			focusDurationMs: 0
		},
		pointClouds: { basis: () => null, rebuildBasis: () => {} },
		systemData: { syncToFocus: () => {} },
		loadTexture: () => {},
		repositionAll: () => {},
		assignMapLayerToTrails: () => {}
	} as unknown as FocusDeps;
	const fc = new FocusController(deps, undefined, new Set(), {} as PromotionDeps['renderer']);
	/** Put the camera on Mars turned onto the rover, half a radius over Mars. */
	const standOnMars = () =>
		fc.snapOntoGround(
			mars,
			{ latitude: SITE.latitude, longitude: SITE.longitude, zoom: 1.5 },
			rover
		);
	return { fc, deps, camera, mars, rover, earth, placed, onFocusChange, standOnMars };
}

describe('FocusController with a landed probe in view', () => {
	it('keeps the probe and the body it stands on out of a clear', () => {
		const { fc, standOnMars } = harness({ spun: false });
		standOnMars();
		const { inFocus } = (fc.promotion as unknown as { deps: PromotionDeps }).deps;
		expect(inFocus('naif-499')).toBe(true);
		expect(inFocus('curiosity')).toBe(true);
		expect(inFocus('naif-399')).toBe(false);
	});

	it('gives the host the focus when the host is framed', () => {
		const { fc, mars, onFocusChange, standOnMars } = harness({ spun: false });
		standOnMars();
		expect(fc.subject?.data.id).toBe('curiosity');
		fc.focusOnBody('naif-499', 4);
		expect(fc.subject).toBeUndefined();
		expect(fc.groundView).toBe(false);
		expect(onFocusChange).toHaveBeenLastCalledWith(mars);
	});

	it('lets go of the probe for a point', () => {
		const { fc, standOnMars } = harness({ spun: false });
		standOnMars();
		fc.focusOnPoint([0, 5, 0]);
		expect(fc.subject).toBeUndefined();
		expect(fc.groundView).toBe(false);
	});

	it('hands the probe the focus on lift-off, the camera keeping its offset', () => {
		const { fc, camera, rover, placed, standOnMars } = harness({ spun: false });
		standOnMars();
		const seatOff = new Vector3(...rover.position!).sub(new Vector3(...MARS_AT));
		const offset = camera.position.clone().sub(seatOff);
		landed.now = false;
		try {
			placed.set(rover.data.id, [0, 400, 0]);
			fc.leaveGround();
		} finally {
			landed.now = true;
		}
		expect(fc.current).toBe(rover);
		expect(fc.subject).toBeUndefined();
		expect(camera.position.distanceTo(offset)).toBeLessThan(1e-9);
	});

	it('flies onto a site in the axes it was read in, before the mesh has the spin', () => {
		const { fc, deps, earth, mars, rover } = harness({ spun: true });
		fc.setFocusTarget(earth);
		deps.focus.focusTruePos = [0, 0, 0];
		fc.panToSurfacePoint(mars, SITE, 0.5, rover);
		const target = new Vector3(...deps.focus.camTargetWorld!);
		const want = new Vector3(...MARS_AT).lerp(new Vector3(...rover.position!), 1.5);
		expect(target.distanceTo(want)).toBeLessThan(1e-9);
	});
});

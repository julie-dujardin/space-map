import { describe, it, expect, vi } from 'vitest';
import { PerspectiveCamera, Quaternion, Vector3 } from 'three';
import { ObjectType, type BodyData, type PositionedBody } from '$lib/types/objects';
import { OrbitalSource } from '$lib/fetch/position/format';
import { sphericalToCartesian } from '$lib/math/spherical';
import { sceneToKm } from '$lib/math/units';
import { LEVEL_LOOK, LookOrbitControls } from '$lib/scene/camera/look-controls';
import type { Vec3 } from '$lib/scene/animation/math';
import type { BodyObjects } from '$lib/scene/types';
import { FocusController, viewOverSite, type FocusDeps } from './controller';
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
	const mars = mkBody({ id: 'naif-499', radiusKm: sceneToKm(SITE.radius) }, MARS_AT);
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
	/** The mesh takes the spin the IAU angles give. */
	const spinMesh = () => bodyObjects.get(mars.data.id)!.mesh!.quaternion.set(...SPIN);
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
			setLook: vi.fn(),
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
	return { fc, deps, camera, mars, rover, earth, placed, onFocusChange, standOnMars, spinMesh };
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

	it('flies where a jump to the same view puts it', () => {
		const cases = [
			{ zoom: 3, lat: 30, lon: 40, want: sphericalToCartesian(MARS_AT, 30, 40, 3, [...SPIN]) },
			// Under half the host's radius: a height over the probe.
			{
				zoom: 0.2,
				lat: 30,
				lon: 40,
				want: new Vector3(...MARS_AT).lerp(new Vector3(...seatOf()), 1.2)
			}
		];
		for (const { zoom, lat, lon, want } of cases) {
			const flight = harness({ spun: true });
			flight.spinMesh();
			flight.fc.setFocusTarget(flight.earth);
			flight.deps.focus.focusTruePos = [0, 0, 0];
			flight.fc.focusOnBody('curiosity', zoom, lat, lon);
			const landed = new Vector3(...flight.deps.focus.camTargetWorld!);
			expect(landed.distanceTo(new Vector3(...want))).toBeLessThan(1e-9);

			const jump = harness({ spun: true });
			jump.spinMesh();
			jump.fc.snapToBody('curiosity', lat, lon, zoom);
			const at = jump.camera.position.clone().add(new Vector3(...jump.deps.focus.focusTruePos));
			expect(at.distanceTo(landed)).toBeLessThan(1e-9);
		}
	});

	it('keeps the look of a jump that frames the probe from above', () => {
		const { fc, deps } = harness({ spun: true });
		const look = { tilt: 0.6, heading: 0.3 };
		fc.snapToBody('curiosity', 0, 0, 0.05, look);
		expect(deps.controls.setLook).toHaveBeenLastCalledWith(look);
		fc.reapplyInitialViewIfPending();
		expect(deps.controls.setLook).toHaveBeenLastCalledWith(look);
	});

	it('puts a snap over its host at the height asked for, not where the camera was', () => {
		const { fc, deps, camera, mars, spinMesh, standOnMars } = harness({ spun: true });
		spinMesh();
		standOnMars();
		const site = { latitude: -20, longitude: 70, radius: 1 };
		const look = { tilt: 0.4, heading: -0.2 };
		fc.arriveAbove(mars, site, 0.01, undefined, true, look);
		const want = sphericalToCartesian([0, 0, 0], -20, 70, 1.01, [...SPIN]);
		expect(camera.position.distanceTo(new Vector3(...want))).toBeLessThan(1e-9);
		expect(deps.focus.aim).toBeNull();
		expect(deps.controls.setLook).toHaveBeenLastCalledWith(look);
	});
});

/** The rover's seat in the spun harness. */
function seatOf(): Vec3 {
	return sphericalToCartesian(MARS_AT, SITE.latitude, SITE.longitude, SITE.radius, [...SPIN]);
}

describe('viewOverSite', () => {
	/** Just enough of a canvas for OrbitControls. */
	const canvas = {
		style: {},
		clientWidth: 1000,
		clientHeight: 1000,
		ownerDocument: { addEventListener() {}, removeEventListener() {} },
		addEventListener() {},
		removeEventListener() {},
		getRootNode: () => ({ addEventListener() {}, removeEventListener() {} }),
		getBoundingClientRect: () => ({ left: 0, top: 0, width: 1000, height: 1000 })
	} as unknown as HTMLElement;

	it('turns a camera held over the site back to where it stood, onto the site', () => {
		const quat: [number, number, number, number] = [0, 0, 0, 1];
		const site = { latitude: -7, longitude: 282, radius: 1 };
		const seat = new Vector3(...sphericalToCartesian([0, 0, 0], -7, 282, 1, quat));
		for (const offset of [
			new Vector3(0.01, 0.02, 0.03),
			new Vector3(-0.03, 0.01, -0.01),
			seat.clone().multiplyScalar(0.02)
		]) {
			if (offset.dot(seat) <= 0) offset.addScaledVector(seat, 0.05);
			const view = viewOverSite(site, offset, quat);
			const camera = new PerspectiveCamera(50, 1, 1e-4, 10);
			camera.position.set(...sphericalToCartesian([0, 0, 0], -7, 282, view.zoom, quat));
			const controls = new LookOrbitControls(camera, canvas, () => site.radius);
			controls.update();
			controls.setLook(view.look!);
			const stood = seat.clone().add(offset);
			expect(camera.position.distanceTo(stood)).toBeLessThan(1e-9);
			const toSeat = seat.clone().sub(camera.position).normalize();
			const forward = camera.getWorldDirection(new Vector3());
			expect(forward.angleTo(toSeat)).toBeLessThan(1e-6);
		}
	});
});

import {
	MathUtils,
	Quaternion,
	Vector3,
	type Mesh,
	type PerspectiveCamera,
	type Scene
} from 'three';
import {
	ObjectType,
	effectiveRadiusKm,
	isExoplanet,
	isExtrasolar,
	type PositionedBody
} from '$lib/types/objects';
import { kmToScene } from '$lib/math/units';
import { OrbitalSource } from '$lib/fetch/position/format';
import { cartesianToSpherical, offsetFacing, sphericalToCartesian } from '$lib/math/spherical';
import type { BodyObjects, Callbacks, CameraView } from '$lib/scene/types';
import {
	LEVEL_LOOK,
	type LookAngles,
	type LookOrbitControls
} from '$lib/scene/camera/look-controls';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
import type { SimClock } from '$lib/scene/state/clock.svelte';
import {
	downgradeBodyMesh,
	isMeshUpgradable,
	upgradeBodyMesh
} from '$lib/scene/objects/body/lifecycle';
import { isModelBearing, unloadBodyModel } from '$lib/scene/objects/body/model';
import { disposeNomenclatureLabels } from '$lib/scene/objects/surface/nomenclature';
import { buildTrails } from '$lib/scene/objects/body/bulk';
import { minCameraDistance } from '$lib/scene/visibility/camera-limits';
import {
	FOCUS_DURATION_MS,
	prepareAim,
	prepareFlyToCamera,
	prepareFocusTarget,
	type FocusState
} from '$lib/scene/animation/focus';
import { f64dist, type Vec3 } from '$lib/scene/animation/math';
import { sceneSettings } from '$lib/scene/settings.svelte';
import type { PointCloudSystem } from '$lib/scene/pointclouds/system';
import type { SystemDataLoader } from '$lib/scene/system-data/loader';
import { PromotionRegistry, type PromotionDeps } from './promotion';
import { angularDuration, FOCUS_ROT_PACING } from '$lib/scene/animation/pacing';
import { surfaceDataEpoch } from '$lib/scene/position/rendered-surface';
import { isLandedAt } from '$lib/fetch/position/probes/propagate';
import { bodyQuaternion } from '$lib/math/orientation';

/** A point of a body's ground in its own axes: degrees, and its distance from
 *  the body's centre in scene units. */
export interface SurfaceSite {
	latitude: number;
	longitude: number;
	radius: number;
}

/** The site of `point`, placed with `host` at `hostPos` turned as at `jd`. Read
 *  off the drawn point, not the angles it was placed from: the ground is drawn
 *  on the body's ellipsoid, which moves a latitude toward the equator. */
export function surfaceSite(
	host: PositionedBody,
	point: Readonly<Vec3>,
	hostPos: Readonly<Vec3>,
	jd: number
): SurfaceSite {
	const s = cartesianToSpherical([...point], [...hostPos], siteQuat(host, jd));
	return { latitude: s.latitude, longitude: s.longitude, radius: s.distance };
}

/** The axes {@link surfaceSite} reads a site in: `host`'s spin at `jd`. Its
 *  mesh may not have that spin yet, or have no mesh at all. */
export function siteQuat(
	host: PositionedBody,
	jd: number
): [number, number, number, number] | undefined {
	const q = host.orientation && bodyQuaternion(host.orientation, jd, host.nutPrec);
	return q ? [q.x, q.y, q.z, q.w] : undefined;
}

/** Whether `distance` from `host`'s centre is under half its radius. No
 *  camera over its ground is that close, so it reads as a height over a point. */
export function underHalfRadius(host: PositionedBody, distance: number): boolean {
	return distance < kmToScene(effectiveRadiusKm(host.data)) / 2;
}

/** The view, held over `site`, that puts the camera at `offset` from it and
 *  turns it onto the site. `quat` gives the axes of `site`. */
export function viewOverSite(
	site: SurfaceSite,
	offset: Vector3,
	quat?: [number, number, number, number]
): CameraView {
	const { latitude, longitude } = site;
	const up = new Vector3(...sphericalToCartesian([0, 0, 0], latitude, longitude, 1, quat));
	const down = new Vector3(
		...sphericalToCartesian([0, 0, 0], latitude + 90, longitude, 1, quat)
	).negate();
	const range = offset.length();
	const level = offset.clone().addScaledVector(up, -offset.dot(up));
	// The angles of LookOrbitControls.lookToward, with north up.
	const tilt = Math.acos(MathUtils.clamp(offset.dot(up) / range, -1, 1));
	const heading = Math.atan2(new Vector3().crossVectors(down, level).dot(up), down.dot(level));
	return { latitude, longitude, zoom: site.radius + range, look: { tilt, heading } };
}

const _from = new Vector3();
const _shift = new Vector3();
const _forward = new Vector3();
const _ground = new Vector3();

export interface FocusDeps {
	ctx: ContextManager;
	clock: SimClock;
	camera: PerspectiveCamera;
	controls: LookOrbitControls;
	scene: Scene;
	bodyObjects: Map<string, BodyObjects>;
	clickables: Mesh[];
	meshToBody: Map<Mesh, PositionedBody>;
	callbacks: Callbacks;
	focus: FocusState;
	pointClouds: PointCloudSystem;
	systemData: SystemDataLoader;
	/** Renderer-owned wrappers needed by setFocusTarget. */
	loadTexture: (body: PositionedBody) => void;
	repositionAll: () => void;
	assignMapLayerToTrails: () => void;
}

/** Owns the focused body, focus/fly animation parameters, and the URL-derived
 *  initial-view replay. Delegates promote/teardown to {@link PromotionRegistry}. */
export class FocusController {
	readonly promotion: PromotionRegistry;
	/** Answers whether a reader click may take the focus. Null until the
	 *  renderer sets it, which is before there is anything to click. */
	readerFocusFilter: ((body: PositionedBody) => boolean) | null = null;
	/** Counts the times the focus was set, so a pick that loads late can tell
	 *  that the focus moved after it. */
	private focusSets = 0;
	private focusedBody: PositionedBody | undefined;
	/** A landed probe the camera is turned onto: the focus reported to the
	 *  page, while the camera orbits the body it stands on. */
	private subjectBody: PositionedBody | undefined;
	/** The camera was turned onto a point of the focused body's ground, so it
	 *  may come down to that ground. */
	private onGround = false;
	/** Where the subject stood when last followed. */
	private subjectSite: SurfaceSite | null = null;
	/** The camera was put where it is from the subject's seat, not from given
	 *  angles: it goes with that seat as the ground under it loads too. */
	private placedOffSubject = false;
	private readonly _tmpV3 = new Vector3();
	/** The opening view of the focused body, put back as its spin, maps and
	 *  relief land. Dropped once the camera moves, and once the focus goes to
	 *  another body. */
	private pendingInitialView: CameraView | null = null;
	/** The ground data the held view was last put back on. */
	private heldEpoch = -1;
	private heldFloor = NaN;
	/** Members of the last {@link syncUpgradeTargets} pass. */
	private upgradeTargetIds = new Set<string>();

	constructor(
		private readonly deps: FocusDeps,
		initialFocus: PositionedBody | undefined,
		hoveredBodyIds: Set<string>,
		renderer: PromotionDeps['renderer']
	) {
		this.focusedBody = initialFocus;
		this.promotion = new PromotionRegistry({
			scene: deps.scene,
			bodyObjects: deps.bodyObjects,
			ctx: deps.ctx,
			clock: deps.clock,
			renderer,
			clickables: deps.clickables,
			meshToBody: deps.meshToBody,
			hoveredBodyIds,
			pointClouds: deps.pointClouds,
			onBodyClick: (b) => this.handleFocus(b),
			assignMapLayerToTrails: deps.assignMapLayerToTrails,
			repositionAll: deps.repositionAll,
			inFocus: (id) => id === this.focusedBody?.data.id || id === this.subjectBody?.data.id,
			onUserPromotedChange: deps.callbacks.onUserPromotedChange,
			onSystemBodies: (bodies) => deps.systemData.loadPlanets(bodies)
		});
	}

	get current(): PositionedBody | undefined {
		return this.focusedBody;
	}

	get subject(): PositionedBody | undefined {
		return this.subjectBody;
	}

	get groundView(): boolean {
		return this.onGround;
	}

	/** Whether `body` is a probe on the ground at `jd`; undefined while its
	 *  record is not in. */
	onGroundAt(body: PositionedBody, jd = this.deps.clock.jd): boolean | undefined {
		if (body.data.objectType !== ObjectType.SPACECRAFT) return false;
		const probe = this.probeRecord(body, jd);
		return probe && isLandedAt(probe, jd);
	}

	/** Where `body` stands at `jd`, if it is a landed probe then. */
	landedSite(
		body: PositionedBody,
		jd = this.deps.clock.jd
	): { host: PositionedBody; site: SurfaceSite } | undefined {
		const probe = this.probeRecord(body, jd);
		if (!probe?.landed || !isLandedAt(probe, jd)) return undefined;
		const { ctx } = this.deps;
		const host = ctx.getBody(`naif-${probe.landed.bodyNaifId}`);
		const pos = ctx.place(body, jd);
		const hostPos = host && ctx.place(host, jd);
		if (!host || !pos || !hostPos) return undefined;
		return { host, site: surfaceSite(host, pos, hostPos, jd) };
	}

	/** `body`'s probe record at `jd`, if it is a probe and the record is in. */
	private probeRecord(body: PositionedBody, jd: number) {
		if (body.data.objectType !== ObjectType.SPACECRAFT) return undefined;
		return this.deps.ctx.probeStore?.probeWithCenter(body.data.id, jd)?.probe;
	}

	/** The landed probe in view moves on its ground, its seat refining as the
	 *  ground loads or a rover driving: the camera goes with it, as it would
	 *  with the probe at the centre of its orbit. */
	followSubject(jd: number): void {
		const subject = this.subjectBody;
		const host = this.focusedBody;
		const now = subject && this.landedSite(subject, jd);
		if (!subject || !host || !now || now.host !== host) return;
		const was = this.subjectSite;
		this.subjectSite = now.site;
		// A view put at given angles is held there until the reader moves: the
		// seat those angles were read from is where the subject ends up.
		if (!was || (!this.placedOffSubject && this.pendingInitialView)) return;
		const q = this.focusedBodyQuat(host);
		const a = sphericalToCartesian([0, 0, 0], was.latitude, was.longitude, was.radius, q);
		const b = sphericalToCartesian(
			[0, 0, 0],
			now.site.latitude,
			now.site.longitude,
			now.site.radius,
			q
		);
		const shift = _shift.set(b[0] - a[0], b[1] - a[1], b[2] - a[2]);
		// Below a millimetre is the rounding of the read itself.
		if (shift.length() < kmToScene(1e-6)) return;
		this.deps.controls.moveOrbit((orbit) => orbit.add(shift));
		const held = this.pendingInitialView;
		if (held) {
			const at = sphericalToCartesian([0, 0, 0], held.latitude, held.longitude, held.zoom, q);
			const moved = cartesianToSpherical(
				[at[0] + shift.x, at[1] + shift.y, at[2] + shift.z],
				[0, 0, 0],
				q
			);
			this.pendingInitialView = {
				...held,
				latitude: moved.latitude,
				longitude: moved.longitude,
				zoom: moved.distance
			};
		}
	}

	/** The landed probe in view is off its ground: it takes the focus, and the
	 *  camera keeps its offset from where the probe last stood. */
	leaveGround(): void {
		const subject = this.subjectBody;
		const host = this.focusedBody;
		const site = this.subjectSite;
		if (!subject || !host) return;
		const pos = this.place(subject);
		if (!pos || !site) {
			this.setFocusTarget(subject);
			return;
		}
		const seat = sphericalToCartesian(
			[0, 0, 0],
			site.latitude,
			site.longitude,
			site.radius,
			siteQuat(host, this.deps.clock.jd)
		);
		const cam = this.deps.camera.position;
		const offset = cartesianToSpherical(
			[cam.x - seat[0], cam.y - seat[1], cam.z - seat[2]],
			[0, 0, 0]
		);
		this.settleOnBodyInstant(subject, pos);
		this.snapToBodyFrame(offset.latitude, offset.longitude, offset.distance);
	}

	/**
	 * Turn the camera onto `site` on `host`'s ground, the host becoming the
	 * body it orbits. Over the host the camera holds its place and turns, or
	 * where a turned view can't reach, swings round the host at its distance
	 * until the site is under it. From elsewhere it flies to `height` above
	 * the site; without one it does as over the host. `subject` is the landed
	 * probe there. Returns the duration in ms.
	 */
	panToSurfacePoint(
		host: PositionedBody,
		site: SurfaceSite,
		height?: number,
		subject?: PositionedBody
	): number {
		const { focus, camera, controls, callbacks, pointClouds } = this.deps;
		const hostPos = this.place(host);
		if (!hostPos) return 0;
		const current = this.focusedBody;
		const overHost =
			current !== undefined &&
			(current.data.id === host.data.id || this.landedSite(current)?.host.data.id === host.data.id);
		if (!overHost && height !== undefined) {
			return this.arriveAbove(host, site, height, subject);
		}

		// The origin goes onto the host with the camera held where it is, so
		// only the view turns.
		const camWorld = this.cameraTruePos();
		if (f64dist(focus.focusTruePos, hostPos) > 0) {
			focus.focusTruePos = [...hostPos];
			camera.position.set(
				camWorld[0] - hostPos[0],
				camWorld[1] - hostPos[1],
				camWorld[2] - hostPos[2]
			);
			this.deps.repositionAll();
			pointClouds.rebuildBasis();
		}
		this.setFocusTarget(host, undefined, subject);
		this.onGround = true;
		this.placedOffSubject = true;
		// The ground the camera looked at before is not where it turns to, and
		// an aim set reads no ground at all.
		focus.aim = null;
		focus.aimLooks = false;
		focus.aimPose = null;
		const quat = siteQuat(host, this.deps.clock.jd);
		const ground = new Vector3(
			...sphericalToCartesian([0, 0, 0], site.latitude, site.longitude, site.radius, quat)
		);
		const from = _from.set(
			camWorld[0] - hostPos[0],
			camWorld[1] - hostPos[1],
			camWorld[2] - hostPos[2]
		);
		if (controls.looksOver(from, ground)) {
			focus.aimPose = controls.lookPose(from, ground, new Quaternion());
			focus.aim = [ground.x, ground.y, ground.z];
			focus.aimLooks = true;
			focus.focusDurationMs = angularDuration(
				camera.quaternion.angleTo(focus.aimPose),
				FOCUS_ROT_PACING
			);
			return focus.focusDurationMs;
		}
		const distance = from.length();
		callbacks.onCameraPosition?.(site.latitude, site.longitude, distance);
		const camPos = sphericalToCartesian(
			[...hostPos],
			site.latitude,
			site.longitude,
			distance,
			quat
		);
		prepareFlyToCamera(focus, camera, camWorld, camPos, sceneSettings().resolvedReducedMotion);
		return focus.focusDurationMs;
	}

	get focusChanges(): number {
		return this.focusSets;
	}

	/** Place of `body` at the scene date. Null when it has none. */
	private place(body: PositionedBody): Vec3 | null {
		return this.deps.ctx.place(body, this.deps.clock.jd);
	}

	setPendingInitialView(view: CameraView): void {
		this.pendingInitialView = view;
	}

	/** Whether the opening view still waits to be placed on its body's axes:
	 *  until then the camera's lat and lon say nothing. */
	get awaitsInitialView(): boolean {
		return this.pendingInitialView !== null;
	}

	clearPendingInitialView(): void {
		this.pendingInitialView = null;
	}

	/** The camera is set from body-fixed angles whose body has no spin yet:
	 *  it turns when the spin lands. */
	get awaitsSpin(): boolean {
		if (!this.pendingInitialView) return false;
		const q = this.focusedBodyQuat();
		return !q || (q[0] === 0 && q[1] === 0 && q[2] === 0 && q[3] === 1);
	}

	/** Quaternion for lat/lon framing around `body`; undefined for scene-frame
	 *  (see {@link framesInBodyAxes}). */
	focusedBodyQuat(body?: PositionedBody): [number, number, number, number] | undefined {
		const b = body ?? this.focusedBody;
		if (!b || !framesInBodyAxes(b)) return undefined;
		const mesh = this.deps.bodyObjects.get(b.data.id)?.mesh;
		if (!mesh) return undefined;
		const q = mesh.quaternion;
		return [q.x, q.y, q.z, q.w];
	}

	/** Reconstruct camera world position in float64 (focus + scene-relative). */
	cameraTruePos(): Vec3 {
		const { focus, camera } = this.deps;
		return [
			focus.focusTruePos[0] + camera.position.x,
			focus.focusTruePos[1] + camera.position.y,
			focus.focusTruePos[2] + camera.position.z
		];
	}

	/** Whether the focus holds `id`'s mesh and model: the focused body, the
	 *  landed probe in view, or another body the focus upgraded. */
	holdsModel(id: string): boolean {
		return (
			id === this.focusedBody?.data.id ||
			id === this.subjectBody?.data.id ||
			this.upgradeTargetIds.has(id)
		);
	}

	/**
	 * Single owner of focus-driven mesh upgrades. Computes the bodies the
	 * current focus needs upgraded ({@link upgradeTargets}: the focus itself, a
	 * moon's parent, a probe's fit center), downgrades `upgradeTargetIds`
	 * members that left the set, upgrades joiners, and loads non-focus
	 * joiners' textures/models. Bodies staying in the set are left untouched,
	 * so their resident texture/DEM/model survive focus switches within it
	 * (Bennu ↔ OSIRIS-REx). Called from initial focus,
	 * {@link setFocusTarget}, and the renderer when a focused probe's fit
	 * center flips mid-focus. Returns the new target ids.
	 */
	syncUpgradeTargets(body: PositionedBody): Set<string> {
		const {
			ctx,
			scene,
			clickables,
			meshToBody,
			bodyObjects,
			pointClouds,
			clock,
			loadTexture,
			assignMapLayerToTrails
		} = this.deps;
		const targets = upgradeTargets(body, ctx);
		// A landed probe in view keeps its model, though the camera orbits its host.
		if (this.subjectBody && !targets.includes(this.subjectBody)) targets.push(this.subjectBody);
		const newIds = new Set(targets.map((t) => t.data.id));
		for (const id of this.upgradeTargetIds) {
			if (newIds.has(id)) continue;
			const bo = bodyObjects.get(id);
			if (!bo) continue;
			// Majors keep their own sphere + texture (system residency owns
			// those); only the overlay model is target-scoped.
			if (isMeshUpgradable(bo.body)) downgradeBodyMesh(bo, scene, clickables, meshToBody);
			else unloadBodyModel(bo);
		}
		let didUpgrade = false;
		for (const t of targets) {
			if (this.upgradeTargetIds.has(t.data.id)) continue;
			this.promotion.ensureBodyObjects(t);
			const tBo = bodyObjects.get(t.data.id);
			if (!tBo) {
				// Not buildable yet (still streaming): stay a non-member so the
				// next sync retries the join.
				newIds.delete(t.data.id);
				continue;
			}
			if (isMeshUpgradable(t)) {
				upgradeBodyMesh(tBo, scene, clickables, meshToBody);
				didUpgrade = true;
			}
			// The focused body's own texture load stays with the focus flow.
			if (t.data.id !== body?.data.id) loadTexture(t);
		}
		if (didUpgrade) {
			// Halo-only bodies had no trail; build now that `bo.mesh` is set.
			buildTrails(bodyObjects, scene, pointClouds.basis(), clock.jd);
			assignMapLayerToTrails();
		}
		this.upgradeTargetIds = newIds;
		return newIds;
	}

	/** Move the camera onto `body` without changing the focused body: onto the
	 *  parent when the focus has no data, or onto the host of an object the map
	 *  cannot place. With `distance`, it arrives that far from the body, from
	 *  the direction it is in now. */
	panCameraToBody(body: PositionedBody, distance?: number): void {
		const pos = this.place(body);
		if (!pos) return;
		const { focus, camera } = this.deps;
		const camWorld = this.cameraTruePos();
		let camPos: Vec3 | undefined;
		if (distance !== undefined) {
			const dir = this._tmpV3
				.set(camWorld[0] - pos[0], camWorld[1] - pos[1], camWorld[2] - pos[2])
				.normalize();
			camPos = [pos[0] + dir.x * distance, pos[1] + dir.y * distance, pos[2] + dir.z * distance];
		}
		prepareFocusTarget(
			focus,
			[...pos],
			camera,
			camWorld,
			camPos,
			sceneSettings().resolvedReducedMotion
		);
	}

	/** Point the camera at a place, not a body (e.g. a spot on a drawn trajectory).
	 *  Clears the focused body — otherwise `updatePositions` re-pins the origin
	 *  to it every frame; a moving point needs the caller to re-drive it. */
	focusOnPoint(position: Vec3, distance?: number): void {
		const { focus, camera, callbacks } = this.deps;
		const camWorld = this.cameraTruePos();
		let camPos: Vec3 | undefined;
		if (distance !== undefined) {
			// Arrive from the camera's current direction, so it reads as a glide not a cut.
			const dir = this._tmpV3
				.set(position[0] - camWorld[0], position[1] - camWorld[1], position[2] - camWorld[2])
				.normalize()
				.negate();
			camPos = [
				position[0] + dir.x * distance,
				position[1] + dir.y * distance,
				position[2] + dir.z * distance
			];
		}
		this.focusedBody = undefined;
		this.subjectBody = undefined;
		this.onGround = false;
		this.promotion.emitUserPromotedCount();
		prepareFocusTarget(
			focus,
			[...position],
			camera,
			camWorld,
			camPos,
			sceneSettings().resolvedReducedMotion
		);
		const spherical = cartesianToSpherical(camPos ?? camWorld, position, undefined);
		callbacks.onCameraPosition?.(spherical.latitude, spherical.longitude, spherical.distance);
	}

	/**
	 * A focus change that leaves the camera where it is: when the view is on
	 * ground of the new focus, at a turn its height allows, the camera looks on
	 * at that ground and settles turned over it. Otherwise it turns to the body.
	 */
	private looksOnOver(bodyPosition: Readonly<Vec3>): void {
		const { focus, camera, controls } = this.deps;
		const camWorld = this.cameraTruePos();
		_from.set(
			camWorld[0] - bodyPosition[0],
			camWorld[1] - bodyPosition[1],
			camWorld[2] - bodyPosition[2]
		);
		camera.getWorldDirection(_forward);
		if (!controls.groundAlong(_from, _forward, _ground)) return;
		if (!controls.looksOver(_from, _ground)) return;
		// Before the aim is set: an aimed camera has no ground to read.
		focus.aimPose = controls.lookPose(_from, _ground, new Quaternion());
		focus.aim = [_ground.x, _ground.y, _ground.z];
		focus.aimLooks = true;
		// The turn is what the view sweeps: little or none, the spot staying put.
		if (focus.focusDurationMs > 0) {
			const angle = camera.quaternion.angleTo(focus.aimPose);
			focus.focusDurationMs = angularDuration(angle, FOCUS_ROT_PACING);
		}
	}

	/** Turn the camera to `direction` from where it stands, keeping the focus.
	 *  The camera orbits a point as far off as the body is, so a drag and a zoom
	 *  keep their feel. */
	aimAt(direction: Vector3, instant: boolean): void {
		const { focus, camera } = this.deps;
		const reach = camera.position.length();
		prepareAim(
			focus,
			[
				camera.position.x + direction.x * reach,
				camera.position.y + direction.y * reach,
				camera.position.z + direction.z * reach
			],
			camera,
			this.cameraTruePos(),
			instant
		);
	}

	/** Turn the camera back to the focused body. */
	endAim(): void {
		const { focus, camera } = this.deps;
		if (!focus.aim) return;
		prepareFocusTarget(
			focus,
			[...focus.focusTargetWorld],
			camera,
			this.cameraTruePos(),
			undefined,
			sceneSettings().resolvedReducedMotion
		);
	}

	/** Click → emit + fly. Re-clicking the focused body re-emits without moving the camera.
	 *  The only way a reader changes focus, so it is where a host's restriction on
	 *  what may be focused is applied; the programmatic moves go round it. */
	handleFocus(body: PositionedBody): void {
		if (this.readerFocusFilter && !this.readerFocusFilter(body)) return;
		// A camera turned away from its body turns back to it.
		const shown = this.subjectBody ?? this.focusedBody;
		if (shown?.data.id === body.data.id && !this.deps.focus.aim) {
			this.deps.callbacks.onFocusChange(body, this.focusedBody);
			return;
		}
		const landed = this.landedSite(body);
		if (landed) {
			this.panToSurfacePoint(landed.host, landed.site, undefined, body);
			return;
		}
		this.setFocusTarget(body);
		const pos = body.position;
		if (!pos) return; // camera never moved — nothing to report
		const camWorld = this.cameraTruePos();
		const { latitude, longitude, distance } = cartesianToSpherical(
			camWorld,
			pos,
			this.focusedBodyQuat(body)
		);
		this.deps.callbacks.onCameraPosition?.(latitude, longitude, distance);
	}

	setFocusTarget(body: PositionedBody, camPos?: Vec3, subject?: PositionedBody): void {
		const { ctx, bodyObjects, callbacks, focus, camera, systemData, loadTexture } = this.deps;
		this.focusSets++;
		this.subjectBody = subject;
		this.subjectSite = (subject && this.landedSite(subject)?.site) ?? null;
		this.placedOffSubject = false;
		this.onGround = false;
		// An extrasolar object takes only its halo and name: the starfield draws
		// it. A planet of another star is a dot, a halo, a name and an orbit line.
		const drawsItself = !isExtrasolar(body) && !isExoplanet(body);
		this.promotion.ensureBodyObjects(body);

		// Unfocused bodies stay halo-only for cost.
		const prev = this.focusedBody;
		const prevId = prev?.data.id;
		const newTargetIds = this.syncUpgradeTargets(body);
		if (prevId && prevId !== body.data.id) {
			const prevBo = bodyObjects.get(prevId);
			// A target that stays upgraded keeps its model too (a probe's fit
			// center focused, then unfocused back to the probe).
			if (prevBo && !newTargetIds.has(prevId)) unloadBodyModel(prevBo);
			if (prevBo) disposeNomenclatureLabels(prevBo);
		}

		if (body.data.id !== prev?.data.id) this.pendingInitialView = null;
		this.focusedBody = body;
		ctx.visibility.setFocused(body, subject);
		callbacks.onFocusChange(subject ?? body, body);
		if (drawsItself) loadTexture(body);
		systemData.syncToFocus();
		// A body with no place takes the focus, and the camera stays where the
		// user left it. The frame loop then follows its nearest placed ancestor.
		const pos = this.place(body);
		if (pos) {
			prepareFocusTarget(
				focus,
				[...pos],
				camera,
				this.cameraTruePos(),
				camPos,
				sceneSettings().resolvedReducedMotion
			);
			if (!camPos) this.looksOnOver(pos);
		}
		// Re-emit: the clear button excludes the focused body, so it must stay in sync.
		this.promotion.emitUserPromotedCount();
	}

	/**
	 * Programmatic focus: fly to body at optional zoom, optionally landing at a
	 * specific body-fixed lat/lon. Returns the animation duration in ms.
	 */
	focusOnBody(id: string, zoom?: number, latitude?: number, longitude?: number): number {
		const { ctx, focus, camera, callbacks, pointClouds } = this.deps;
		const body = ctx.getBody(id);
		if (!body) return 0;
		// Nowhere to fly: take the focus (drawer, trails, system data) and hold the camera.
		const pos = this.place(body);
		if (!pos) {
			this.setFocusTarget(body);
			return 0;
		}
		const landed = this.landedSite(body);
		if (landed) {
			const { host, site } = landed;
			// Read as snapToBody reads it, so that a flight and a jump meet.
			if (zoom === undefined || underHalfRadius(host, zoom)) {
				return this.panToSurfacePoint(host, site, zoom, body);
			}
			const view = { latitude: latitude ?? site.latitude, longitude: longitude ?? site.longitude };
			return this.flyOntoGround(host, { ...view, zoom }, body);
		}
		let camPos: Vec3 | undefined;
		if (zoom !== undefined) {
			if (latitude !== undefined && longitude !== undefined) {
				camPos = sphericalToCartesian(pos, latitude, longitude, zoom, this.focusedBodyQuat(body));
			} else {
				// Place camera at `zoom` distance, arriving from the current direction.
				const camWorld = this.cameraTruePos();
				const dir = this._tmpV3
					.set(pos[0] - camWorld[0], pos[1] - camWorld[1], pos[2] - camWorld[2])
					.normalize()
					.negate();
				camPos = [pos[0] + dir.x * zoom, pos[1] + dir.y * zoom, pos[2] + dir.z * zoom];
			}
		}
		// Emit before dispatch so AppState's camera fields are fresh when
		// onFocusChange fires inside setFocusTarget.
		const emitFrom = camPos ?? this.cameraTruePos();
		const spherical = cartesianToSpherical(emitFrom, pos, this.focusedBodyQuat(body));
		callbacks.onCameraPosition?.(spherical.latitude, spherical.longitude, spherical.distance);
		if (zoom !== undefined && camPos) {
			// The flight sets the camera: the opening view would undo it.
			this.pendingInitialView = null;
			// A camera turned onto its ground does not orbit it. `focusedBody` can lead the origin.
			const orbitingThisBody =
				this.focusedBody?.data.id === id &&
				!this.subjectBody &&
				!this.onGround &&
				f64dist(focus.focusTruePos, pos) < minCameraDistance(body);
			if (orbitingThisBody) {
				// Snap focus in case a prior fly animation hasn't fully settled.
				focus.focusTruePos = [...pos];
				this.deps.repositionAll();
				pointClouds.rebuildBasis();
				prepareFlyToCamera(
					focus,
					camera,
					this.cameraTruePos(),
					camPos,
					sceneSettings().resolvedReducedMotion
				);
			} else {
				this.setFocusTarget(body, camPos);
				if (latitude !== undefined && longitude !== undefined) {
					// Orbit mode so Earth stays centered during approach.
					focus.orbitFly = true;
				}
			}
		} else {
			this.setFocusTarget(body);
		}
		return focus.focusDurationMs;
	}

	/** Instantly focus a now-resident body per the URL, no approach fly — for a
	 *  late-arriving chunk landing after the camera settled on the placeholder parent. */
	snapToBody(
		id: string,
		latitude: number,
		longitude: number,
		zoom: number,
		look: LookAngles = LEVEL_LOOK
	): void {
		const body = this.deps.ctx.getBody(id);
		const pos = body && this.place(body);
		if (!body || !pos) return;
		// A landed probe's view is read off the body it stands on.
		const landed = this.landedSite(body);
		if (landed) {
			const { host, site } = landed;
			if (underHalfRadius(host, zoom)) this.arriveAbove(host, site, zoom, body, true, look);
			else this.snapOntoGround(host, { latitude, longitude, zoom, look }, body);
			return;
		}
		this.settleOnBodyInstant(body, pos);
		this.snapToBodyFrame(latitude, longitude, zoom, look);
	}

	/** Go to `height` above `site` on `host`'s ground, looking straight down
	 *  at it or turned by `look`: a flight, or at once with `instant`. The
	 *  camera then goes with `subject` as its seat moves. */
	arriveAbove(
		host: PositionedBody,
		site: SurfaceSite,
		height: number,
		subject?: PositionedBody,
		instant = false,
		look: LookAngles = LEVEL_LOOK
	): number {
		const view = { latitude: site.latitude, longitude: site.longitude, zoom: site.radius + height };
		if (!instant) return this.flyOntoGround(host, view, subject);
		this.snapOntoGround(host, { ...view, look }, subject);
		this.placedOffSubject = true;
		return 0;
	}

	/** Fly onto `host` at `view`, looking down at its ground. Returns the
	 *  duration in ms. */
	private flyOntoGround(host: PositionedBody, view: CameraView, subject?: PositionedBody): number {
		const { focus, callbacks } = this.deps;
		const hostPos = this.place(host);
		if (!hostPos) return 0;
		const camPos = sphericalToCartesian(
			[...hostPos],
			view.latitude,
			view.longitude,
			view.zoom,
			siteQuat(host, this.deps.clock.jd)
		);
		callbacks.onCameraPosition?.(view.latitude, view.longitude, view.zoom);
		this.pendingInitialView = null;
		this.setFocusTarget(host, camPos, subject);
		focus.orbitFly = true;
		this.onGround = true;
		this.placedOffSubject = true;
		return focus.focusDurationMs;
	}

	/** Settle on `host` at `view` at once, looking down at its ground, with
	 *  `subject` the landed probe in view. */
	snapOntoGround(host: PositionedBody, view: CameraView, subject?: PositionedBody): void {
		const pos = this.place(host);
		if (!pos) return;
		this.settleOnBodyInstant(host, pos, subject);
		this.snapToBodyFrame(view.latitude, view.longitude, view.zoom, view.look);
		this.onGround = true;
	}

	/** Snap focus onto a body, framed toward `towardId` (e.g. the Sun) at
	 *  `elevationDeg` above the ecliptic. Scene-frame, not body-fixed — clears
	 *  the pending replay. Used for the home/bare-Earth landing view. */
	snapToBodyFacing(id: string, towardId: string, elevationDeg: number, distance: number): boolean {
		const { ctx, camera, controls, callbacks } = this.deps;
		const body = ctx.getBody(id);
		const towardBody = ctx.getBody(towardId);
		const pos = body && this.place(body);
		const toward = towardBody && this.place(towardBody);
		if (!body || !pos || !toward) return false;
		this.settleOnBodyInstant(body, pos);
		const offset = offsetFacing(pos, toward, elevationDeg, distance);
		camera.position.set(offset[0], offset[1], offset[2]);
		controls.update();
		const settled = cartesianToSpherical(offset, [0, 0, 0]);
		callbacks.onCameraPosition?.(settled.latitude, settled.longitude, settled.distance);
		this.pendingInitialView = null; // scene-frame placement is final; skip the body-fixed replay
		return true;
	}

	/** Snap focus onto a body with the camera `distance` from it on the line to
	 *  `fromId`, looking away from that body: a star framed from the Sun's side,
	 *  against the sky it is seen in from home. Scene-frame, like the home view. */
	snapToBodyFrom(id: string, fromId: string, distance: number): void {
		const { ctx, camera, controls, callbacks } = this.deps;
		const body = ctx.getBody(id);
		const from = ctx.getBody(fromId);
		const pos = body && this.place(body);
		const at = from && this.place(from);
		if (!body || !pos || !at) return;
		this.settleOnBodyInstant(body, pos);
		const d = f64dist(at, pos);
		const offset: Vec3 = [
			((at[0] - pos[0]) / d) * distance,
			((at[1] - pos[1]) / d) * distance,
			((at[2] - pos[2]) / d) * distance
		];
		camera.position.set(offset[0], offset[1], offset[2]);
		controls.update();
		const settled = cartesianToSpherical(offset, [0, 0, 0]);
		callbacks.onCameraPosition?.(settled.latitude, settled.longitude, settled.distance);
		this.pendingInitialView = null;
	}

	/** Settle focus onto a resident body with no approach fly, nulling the cam-fly
	 *  fields so stepFocusAnimation's settle branch leaves the snapped frame untouched. */
	private settleOnBodyInstant(
		body: PositionedBody,
		pos: Readonly<Vec3>,
		subject?: PositionedBody
	): void {
		const { focus, pointClouds } = this.deps;
		this.setFocusTarget(body, undefined, subject);
		focus.focusTruePos = [...pos];
		focus.focusOriginWorld = [...pos];
		focus.focusTargetWorld = [...pos];
		focus.focusStartTime = -FOCUS_DURATION_MS; // already settled
		focus.camOriginWorld = null;
		focus.camTargetWorld = null;
		focus.flyQ0 = null;
		focus.orbitFly = false;
		focus.arcOrbit = false;
		focus.cameraStaysOnBody = false;
		// The caller places the camera: a turn onto what it looked at before
		// would undo that on the next frame.
		focus.aim = null;
		focus.aimLooks = false;
		focus.aimPose = null;
		focus.leavesAim = false;
		this.deps.repositionAll();
		pointClouds.rebuildBasis();
	}

	/** Snap the camera to a body-fixed lat/lon/zoom for URL deep links, no fly.
	 *  Uses the current quat (identity if not loaded); queues a replay to
	 *  correct the angle once orientation lands. */
	snapToBodyFrame(
		latitude: number,
		longitude: number,
		zoom: number,
		look: LookAngles = LEVEL_LOOK
	): void {
		const body = this.focusedBody;
		if (!body) return;
		const { camera, controls, callbacks } = this.deps;
		// A body-fixed body has identity until its spin or pose lands.
		const bodyFixed = framesInBodyAxes(body);
		const quat = bodyFixed ? (this.focusedBodyQuat(body) ?? [0, 0, 0, 1]) : undefined;
		const camOffset = sphericalToCartesian([0, 0, 0], latitude, longitude, zoom, quat);
		camera.position.set(camOffset[0], camOffset[1], camOffset[2]);
		controls.update();
		controls.setLook(look);
		// Read back via cartesianToSpherical to canonicalize to (-180, 180] — feature
		// lon is stored 0..360 and would otherwise leak straight to the URL.
		const settled = cartesianToSpherical(camOffset, [0, 0, 0], quat);
		callbacks.onCameraPosition?.(
			settled.latitude,
			settled.longitude,
			settled.distance,
			controls.look
		);
		// Held until the reader moves: the body's spin, its maps and its relief
		// land after it, and each would leave the camera somewhere else.
		this.pendingInitialView = bodyFixed ? { latitude, longitude, zoom, look } : null;
	}

	/** Put the camera back on the held view, once the body's spin has landed
	 *  or its ground has moved: the first placement fell back to scene axes and
	 *  to whatever floor the ground's data then allowed. */
	reapplyInitialViewIfPending(): void {
		const pending = this.pendingInitialView;
		if (!pending) return;
		// No spin yet, or none at all: scene axes, as the first placement.
		const quat = this.focusedBodyQuat() ?? [0, 0, 0, 1];
		const camPos = sphericalToCartesian(
			[0, 0, 0],
			pending.latitude,
			pending.longitude,
			pending.zoom,
			quat
		);
		this.deps.camera.position.set(...camPos);
		this.deps.controls.update();
		this.deps.controls.setLook(pending.look ?? LEVEL_LOOK);
	}

	/** Per frame: once the ground's data moves the floor (its relief drawn,
	 *  its maps' clearance known), the held view goes back where it was put,
	 *  out of the push the earlier floor gave it. */
	holdInitialView(): void {
		if (!this.pendingInitialView) return;
		const epoch = surfaceDataEpoch();
		const floor = this.deps.controls.minDistance;
		if (epoch === this.heldEpoch && floor === this.heldFloor) return;
		this.heldEpoch = epoch;
		this.heldFloor = floor;
		this.reapplyInitialViewIfPending();
	}
}

/** The camera's lat/lon is in the axes of the body's mesh. Spacecraft spin too
 *  fast for that, and stars and planets drawn as dots have no axes. A planet of
 *  another star with a map uses the axes of its pose. */
function framesInBodyAxes(b: PositionedBody): boolean {
	if (isModelBearing(b) || isExtrasolar(b)) return false;
	return !isExoplanet(b) || b.data.mapped === true;
}

/** Bodies whose mesh should be upgraded while `focus` is focused: the focus
 *  itself, plus the parent for asteroid moons (so it stays a sphere + trail)
 *  and for probes (the fit center the probe is orbiting — Bennu under
 *  OSIRIS-REx — which needs its mesh/model to read the orbit against). */
function upgradeTargets(focus: PositionedBody | undefined, ctx: ContextManager): PositionedBody[] {
	if (!focus) return [];
	const out: PositionedBody[] = [];
	if (isMeshUpgradable(focus)) out.push(focus);
	const wantsParent =
		focus.data.objectType === ObjectType.MOON ||
		focus.data.orbitalSource === OrbitalSource.SPICE_PROBE;
	if (wantsParent) {
		// Non-upgradable parents (Ceres under Dawn) join too: they keep their
		// own mesh, but membership drives their texture/DEM/model load and
		// protects the resident state across focus switches.
		const parent = ctx.getBody(focus.data.parentId);
		if (parent) out.push(parent);
	}
	return out;
}

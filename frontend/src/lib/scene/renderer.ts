import {
	AmbientLight,
	DirectionalLight,
	Float32BufferAttribute,
	Mesh,
	BasicShadowMap,
	PerspectiveCamera,
	PointLight,
	Points,
	Raycaster,
	Scene,
	TextureLoader,
	Vector2,
	Vector3,
	WebGLRenderer
} from 'three';
import { CSS2DRenderer } from 'three/addons/renderers/CSS2DRenderer.js';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { cartesianToSpherical, sphericalToCartesian, type MapViewState } from '$lib/url-state';
import { ObjectType, isAsteroid, type PositionedBody } from '$lib/types/objects';
import type { ContextManager } from '$lib/scene/context-manager.svelte';
import type { SimClock } from '$lib/scene/clock.svelte';
import { AU_SCALE, kmToScene } from '$lib/math/units';
import { applyOrientation } from '$lib/math/orientation';
import { orbitalElementsToPositionJD, parabolicToPositionJD } from '$lib/math/orbit/position';
import {
	buildMajorBodies,
	buildOrbitLines,
	buildPointClouds,
	rebuildMinorPointClouds,
	loadBodyTexture,
	loadBodyTextureTier,
	loadSystemData,
	makeCircleTexture
} from './objects/construction';
import { refreshOrbitLineGeometry } from './objects/builders';
import { type BodyObjects, type Callbacks } from './types';
import { DEFAULT_PROMOTED_IDS } from './default-bodies';
import type { Vec3 } from './animation/math';
import {
	type FocusState,
	FOCUS_DURATION_MS,
	stepFocusAnimation,
	prepareFocusTarget,
	prepareFlyToCamera
} from './animation/focus';
import { minCameraDistance } from './visibility/camera-limits';
import { updateBodyVisibility } from './visibility/update';
import { pickPointCloudBody } from './interaction/picking';

/**
 * Sim-seconds per real-second above which spacecraft point-cloud phases stop
 * advancing. At this rate per-frame sim advance (~1 min at 60fps) is ~1% of a
 * LEO orbit — below it per-frame motion is smooth; above, the round-robin
 * recompute aliases sats to random new phases every cycle and the cloud
 * visibly scrambles. 2 h/s.
 */
const SPACECRAFT_PHASE_FREEZE_RATE = 7200;

// --- SceneRenderer ---

export class SceneRenderer {
	private renderer: WebGLRenderer;
	private labelRenderer: CSS2DRenderer;
	private scene: Scene;
	private camera: PerspectiveCamera;
	private controls: OrbitControls;
	private raycaster = new Raycaster();
	private pointer = new Vector2();
	private pointerDownPos = new Vector2();

	private ctx: ContextManager;
	private clock: SimClock;
	private callbacks: Callbacks;

	private bodyObjects = new Map<string, BodyObjects>();
	private circleTexture = makeCircleTexture();
	private asteroidPoints = new Map<string, Points>();
	private lastSystemTextureBarycenter: string | null = null;
	private spacecraftPoints = new Map<string, Points>();
	private moonPoints = new Map<string, Points>();
	private clickables: Mesh[] = [];
	private meshToBody = new Map<Mesh, PositionedBody>();
	private pendingSceneAdds: Points[] = [];
	private pendingDefaultPromotions = new Set(DEFAULT_PROMOTED_IDS);
	private hoveredBodyIds = new Set<string>();
	private cullFrameCounter = 0;

	// TODO: expose via UI settings
	hideCappedMoonLabels = false;

	private focusedBody: PositionedBody | undefined;
	private readonly _tmpV3 = new Vector3();

	// Focus/fly animation state (mutated by animation module)
	private readonly focus: FocusState = {
		focusTruePos: [0, 0, 0],
		focusOriginWorld: [0, 0, 0],
		focusTargetWorld: [0, 0, 0],
		camOriginWorld: null,
		camTargetWorld: null,
		flyQ0: null,
		flyQ1: null,
		orbitFly: false,
		focusStartTime: 0,
		focusDurationMs: FOCUS_DURATION_MS
	};
	private pointCloudBasisPos: Vec3 = [0, 0, 0];
	/** Round-robin cursor: which minor point cloud (asteroid zone / spacecraft group) to refresh next. */
	private pointCloudUpdateIdx = 0;
	/** JD at which per-frame body positions were last computed. */
	private lastUpdatedJd = NaN;
	/**
	 * Parent position snapshot per point-cloud group at the moment of the
	 * last Kepler recompute. Frame-to-frame, we translate the Points object
	 * by (current parent pos − snapshot) so bodies stay attached to their
	 * moving parent without paying Kepler cost every frame. Keys:
	 * `asteroid:<zone>`, `spacecraft:<parentId>`.
	 */
	private pointCloudParentAtUpdate = new Map<string, Vec3>();
	/** True while time rate is above {@link SPACECRAFT_PHASE_FREEZE_RATE}. Tracked to trigger a catch-up recompute on transition out. */
	private spacecraftFrozen = false;
	/** Memoized moon → parent grouping; invalidated when majorBodies count changes (new chunk loaded). */
	private moonsByParentCache: { len: number; map: Map<string, PositionedBody[]> } | null = null;

	private rafId = 0;
	private firstFrame = true;
	private pendingUrlWrite = false;
	/**
	 * Initial lat/lon/zoom stashed until the focused body's orientation has
	 * loaded, at which point we re-place the camera in body-fixed coords.
	 * Cleared once applied or once the user moves the camera.
	 */
	private pendingInitialView: {
		latitude: number;
		longitude: number;
		zoom: number;
	} | null = null;
	private readonly textureLoader = new TextureLoader();
	private readonly shadowLight: DirectionalLight;
	private sunPointLight: PointLight | undefined;

	constructor(
		canvas: HTMLCanvasElement,
		labelContainer: HTMLElement,
		ctx: ContextManager,
		clock: SimClock,
		initialView: MapViewState,
		callbacks: Callbacks
	) {
		this.ctx = ctx;
		this.clock = clock;
		this.callbacks = callbacks;

		// Renderer
		this.renderer = new WebGLRenderer({ canvas, logarithmicDepthBuffer: true, antialias: true });
		this.renderer.setPixelRatio(window.devicePixelRatio);
		this.renderer.setSize(canvas.clientWidth, canvas.clientHeight, false);
		this.renderer.shadowMap.enabled = true;
		this.renderer.shadowMap.type = BasicShadowMap;

		// CSS2D label renderer
		this.labelRenderer = new CSS2DRenderer({ element: labelContainer });
		this.labelRenderer.setSize(canvas.clientWidth, canvas.clientHeight);
		ctx.updateViewport(canvas.clientHeight);

		// Scene + lights
		this.scene = new Scene();
		this.scene.add(new AmbientLight(0xffffff, 0.05));

		// Shadow-casting directional light (swapped in when zoomed into a sub-system)
		this.shadowLight = new DirectionalLight(0xffffff, 0);
		this.shadowLight.castShadow = true;
		this.shadowLight.shadow.mapSize.set(4096, 4096);
		this.shadowLight.shadow.bias = -0.00001;
		this.scene.add(this.shadowLight);
		this.scene.add(this.shadowLight.target);

		// Camera
		const aspect = canvas.clientWidth / canvas.clientHeight;
		this.camera = new PerspectiveCamera(60, aspect, kmToScene(0.001), 100000);

		// Set initial camera position from URL state
		const sunBody = ctx.majorBodies.find((b) => b.data.id === 'naif-10');
		const matchedBody = ctx.getBody(initialView.id);
		const focusBody = matchedBody ?? sunBody;
		const focusPos: Vec3 = focusBody?.position ?? [0, 0, 0];

		this.focusedBody = focusBody;
		this.focus.focusTruePos = [...focusPos];
		this.focus.focusOriginWorld = [...focusPos];
		this.focus.focusTargetWorld = [...focusPos];
		this.pointCloudBasisPos = [...focusPos];
		this.focus.focusStartTime = -FOCUS_DURATION_MS; // already settled

		// Camera position: focus-relative (small offset from origin).
		// lat/lon are body-fixed, but the mesh quaternion is still identity here
		// because the focused body's orientation metadata hasn't been fetched
		// yet — so this initial placement falls back to scene-frame. We stash
		// the requested view and re-apply it once orientation loads below.
		const camPos = sphericalToCartesian(
			[0, 0, 0],
			initialView.latitude,
			initialView.longitude,
			initialView.zoom,
			this.focusedBodyQuat()
		);
		this.camera.position.set(...camPos);
		this.pendingInitialView = {
			latitude: initialView.latitude,
			longitude: initialView.longitude,
			zoom: initialView.zoom
		};

		// OrbitControls — target always at origin
		this.controls = new OrbitControls(this.camera, canvas);
		this.controls.enableDamping = true;
		this.controls.minDistance = focusBody ? minCameraDistance(focusBody) : kmToScene(0.01);
		this.controls.maxDistance = 31_620.5 * AU_SCALE; // 0.5 light-year
		this.controls.target.set(0, 0, 0);
		this.controls.update();
		this.controls.addEventListener('end', this.onControlsEnd);

		// Sync context initial state
		if (focusBody) ctx.setFocused(focusBody);
		ctx.updateCamera(initialView.zoom);

		// Notify initial focus
		callbacks.onFocusChange(focusBody);

		// Build all scene objects
		this.buildScene();

		// Grab reference to Sun's PointLight for shadow swap
		const sunBo = this.bodyObjects.get('naif-10');
		this.sunPointLight = sunBo?.extraObjects.find((o): o is PointLight => o instanceof PointLight);

		// If focused body has no visual objects (e.g. placeholder from global file), build them.
		if (focusBody) this.ensureBodyObjects(focusBody);

		// Apply focus-relative positions to all scene objects
		this.repositionAll();

		// Load textures for initial focus (bodyObjects is now populated)
		if (focusBody) this.maybeLoadTexture(focusBody);
		this.maybeLoadSystemData();

		// Click handler
		canvas.addEventListener('pointerdown', this.onPointerDown);
		canvas.addEventListener('pointerup', this.onPointerUp);

		// Start loop
		this.tick();
	}

	// --- Scene construction ---

	private buildScene(): void {
		buildMajorBodies(
			this.ctx.majorBodies,
			this.scene,
			this.clickables,
			this.meshToBody,
			this.bodyObjects,
			this.circleTexture,
			this.renderer.domElement,
			(body) => this.handleFocus(body),
			(id, hovered) => (hovered ? this.hoveredBodyIds.add(id) : this.hoveredBodyIds.delete(id))
		);
		const promotedIds = new Set(this.bodyObjects.keys());
		const pts = buildPointClouds(
			this.ctx,
			this.scene,
			this.circleTexture,
			this.pointCloudBasisPos,
			promotedIds
		);
		this.asteroidPoints = pts.asteroidPoints;
		this.spacecraftPoints = pts.spacecraftPoints;
		this.moonPoints = pts.moonPoints;
		// Defer orbit line geometry (100K+ Kepler solves) to after first paint
		const basis = this.pointCloudBasisPos;
		// requestIdleCallback isn't available in Safari
		const scheduleIdle = globalThis.requestIdleCallback ?? ((cb: () => void) => setTimeout(cb, 0));
		scheduleIdle(() => buildOrbitLines(this.bodyObjects, this.scene, basis));
	}

	rebuildMinorPointClouds(): void {
		const newPoints = rebuildMinorPointClouds(
			this.ctx,
			this.circleTexture,
			this.asteroidPoints,
			this.spacecraftPoints,
			this.pointCloudBasisPos,
			new Set(this.bodyObjects.keys())
		);
		if (newPoints.length > 0) {
			this.pendingSceneAdds.push(...newPoints);
		}
	}

	// --- Focus-relative positioning ---

	private repositionAll(): void {
		this.repositionBodies();
		this.rebuildOrbitLineBasis();
	}

	/** Like {@link repositionAll} but skips the orbit-line rewrite — for callers that already refreshed lines per-body. */
	private repositionBodies(): void {
		const [fx, fy, fz] = this.focus.focusTruePos;
		for (const bo of this.bodyObjects.values()) {
			const [bx, by, bz] = bo.body.position;
			const rx = bx - fx,
				ry = by - fy,
				rz = bz - fz;
			bo.group.position.set(rx, ry, rz);
			for (const obj of bo.extraObjects) obj.position.set(rx, ry, rz);
		}
		this.repositionPointClouds();
	}

	private repositionPointClouds(): void {
		const [fx, fy, fz] = this.focus.focusTruePos;
		const [bx, by, bz] = this.pointCloudBasisPos;
		const dx = bx - fx,
			dy = by - fy,
			dz = bz - fz;
		// Shift each group by (parent_now − parent_at_last_kepler_update) so
		// bodies ride along with their moving parent. Without this, point-cloud
		// satellites visibly lag their planet and snap back each round-robin
		// refresh (once per ~group_count frames).
		for (const [zone, pts] of this.asteroidPoints) {
			const [sx, sy, sz] = this.parentShift(`asteroid:${zone}`, 'naif-10');
			pts.position.set(dx + sx, dy + sy, dz + sz);
		}
		for (const [gid, pts] of this.spacecraftPoints) {
			const [sx, sy, sz] = this.parentShift(`spacecraft:${gid}`, gid);
			pts.position.set(dx + sx, dy + sy, dz + sz);
		}
		// Moon point clouds are re-written every frame (writeMoonPointClouds),
		// so vertex buffers are always current — no shift needed.
		for (const pts of this.moonPoints.values()) pts.position.set(dx, dy, dz);
	}

	private parentShift(snapshotKey: string, parentId: string): Vec3 {
		const snapshot = this.pointCloudParentAtUpdate.get(snapshotKey);
		const current = this.ctx.getBody(parentId)?.position;
		if (!snapshot || !current) return [0, 0, 0];
		return [current[0] - snapshot[0], current[1] - snapshot[1], current[2] - snapshot[2]];
	}

	/**
	 * Rebase point clouds when focus has drifted > 0.01 AU from the basis —
	 * keeps Float32 vertex precision at ~4 km while avoiding thrash.
	 */
	private maybeRebasePointClouds(): void {
		const [fx, fy, fz] = this.focus.focusTruePos;
		const [bx, by, bz] = this.pointCloudBasisPos;
		const dx = fx - bx,
			dy = fy - by,
			dz = fz - bz;
		const drift2 = dx * dx + dy * dy + dz * dz;
		const threshold = 0.01 * AU_SCALE;
		if (drift2 > threshold * threshold) this.rebuildPointCloudBasis();
	}

	private rebuildPointCloudBasis(): void {
		this.pointCloudBasisPos = [...this.focus.focusTruePos];
		for (const zone of this.asteroidPoints.keys()) this.ctx.dirtyAsteroidZones.add(zone);
		for (const gid of this.spacecraftPoints.keys()) this.ctx.dirtySpacecraftGroups.add(gid);
		this.rebuildMinorPointClouds();
		// NOTE: do NOT reset parent snapshots here. Vertex buffers were rewritten
		// from the *stale* body.position left over from the last round-robin
		// writeMinorPointCloud, so the snapshot must stay pinned to that same
		// moment (parent-at-body-was-written), not to "now". Resetting it makes
		// parentShift undercompensate by (parent_now − parent_old) and the
		// cluster jumps on every rebase.
		this.rebuildMoonPointClouds();
		this.rebuildOrbitLineBasis();
		// Basis now matches focus, so (basis − focus) = 0, but parentShift is
		// still non-zero (snapshots are intentionally pinned to their vertex
		// data's age, not reset). Run the normal repositioner so each Points
		// object gets shift-compensated — hardcoding 0 here misplaces clusters
		// by ~parentShift for one frame, which at high time rates (rebases
		// several times per second) reads as a visibility flicker when the
		// offset pushes them out of the camera frustum.
		this.repositionPointClouds();
	}

	/**
	 * Moons copy already-repositioned coords (cheap). Asteroid zones and
	 * spacecraft groups each do thousands of Kepler solves, so they're
	 * round-robined one-per-frame to bound the frame budget.
	 *
	 * Above {@link SPACECRAFT_PHASE_FREEZE_RATE}, we stop advancing spacecraft
	 * phases — sim advance per frame exceeds an appreciable fraction of LEO
	 * orbital period, so per-cycle recomputes just alias each sat to a
	 * random new phase. Freezing gives a visually stable cloud that still
	 * rides along with its parent via parentShift in {@link repositionPointClouds}.
	 *
	 * TODO: move Kepler solves off the main thread (worker pool, transferable
	 * Float32Array buffers). With per-frame updates for all groups in parallel
	 * we could drop the round-robin entirely and lower this freeze threshold.
	 */
	private updatePointClouds(jd: number): void {
		this.writeMoonPointClouds();

		const freezeSpacecraft = Math.abs(this.clock.timeScale) >= SPACECRAFT_PHASE_FREEZE_RATE;
		// On transition out of freeze, catch up every spacecraft group in one
		// pass so the cloud reflects current jd immediately (user typically
		// just paused or slowed down — a one-frame hitch is fine, and the
		// alternative is stale positions until each group cycles round-robin).
		if (this.spacecraftFrozen && !freezeSpacecraft) {
			for (const gid of this.spacecraftPoints.keys()) {
				this.writeMinorPointCloud(gid, 'spacecraft', jd);
			}
		}
		this.spacecraftFrozen = freezeSpacecraft;

		const asteroidKeys = [...this.asteroidPoints.keys()];
		const spacecraftKeys = freezeSpacecraft ? [] : [...this.spacecraftPoints.keys()];
		const total = asteroidKeys.length + spacecraftKeys.length;
		if (total === 0) return;
		this.pointCloudUpdateIdx = (this.pointCloudUpdateIdx + 1) % total;
		const idx = this.pointCloudUpdateIdx;
		if (idx < asteroidKeys.length) {
			const zone = asteroidKeys[idx];
			this.writeMinorPointCloud(zone, 'asteroid', jd);
		} else {
			const gid = spacecraftKeys[idx - asteroidKeys.length];
			this.writeMinorPointCloud(gid, 'spacecraft', jd);
		}
	}

	private getMoonsByParent(): Map<string, PositionedBody[]> {
		const len = this.ctx.majorBodies.length;
		if (this.moonsByParentCache?.len === len) return this.moonsByParentCache.map;
		const map = new Map<string, PositionedBody[]>();
		for (const body of this.ctx.majorBodies) {
			if (body.data.objectType === ObjectType.MOON) {
				const list = map.get(body.data.parentId) ?? [];
				list.push(body);
				map.set(body.data.parentId, list);
			}
		}
		this.moonsByParentCache = { len, map };
		return map;
	}

	private writeMoonPointClouds(): void {
		const [bx, by, bz] = this.pointCloudBasisPos;
		for (const [parentId, moons] of this.getMoonsByParent()) {
			const pts = this.moonPoints.get(parentId);
			if (!pts) continue;
			const posAttr = pts.geometry.getAttribute('position');
			const arr = posAttr.array as Float32Array;
			const n = Math.min(moons.length, arr.length / 3);
			for (let i = 0; i < n; i++) {
				arr[i * 3] = moons[i].position[0] - bx;
				arr[i * 3 + 1] = moons[i].position[1] - by;
				arr[i * 3 + 2] = moons[i].position[2] - bz;
			}
			posAttr.needsUpdate = true;
		}
	}

	/**
	 * Recompute one group's positions at `jd` into its geometry buffer.
	 * Parents that aren't meshed fall back to SSB — fine for asteroids since
	 * the Sun's offset from SSB is sub-km.
	 */
	private writeMinorPointCloud(key: string, kind: 'asteroid' | 'spacecraft', jd: number): void {
		const sourceBodies =
			kind === 'asteroid'
				? this.ctx.asteroidBodiesByZone.get(key)
				: this.ctx.spacecraftByParent.get(key);
		const points =
			kind === 'asteroid' ? this.asteroidPoints.get(key) : this.spacecraftPoints.get(key);
		if (!sourceBodies || !points) return;

		// Snapshot the parent's position so {@link parentShift} can translate
		// the Points object each frame between round-robin recomputes.
		const groupParentId = kind === 'asteroid' ? 'naif-10' : key;
		const groupParentPos = this.ctx.getBody(groupParentId)?.position;
		if (groupParentPos) {
			this.pointCloudParentAtUpdate.set(`${kind}:${key}`, [
				groupParentPos[0],
				groupParentPos[1],
				groupParentPos[2]
			]);
		}

		const promoted = this.bodyObjects;
		const [bx, by, bz] = this.pointCloudBasisPos;
		const posAttr = points.geometry.getAttribute('position');
		const arr = posAttr.array as Float32Array;
		const capacity = arr.length / 3;

		let writeIdx = 0;
		for (const body of sourceBodies) {
			if (writeIdx >= capacity) break;
			if (promoted.has(body.data.id)) continue;

			const parent = promoted.get(body.data.parentId)?.body.position;
			const px = parent?.[0] ?? 0;
			const py = parent?.[1] ?? 0;
			const pz = parent?.[2] ?? 0;
			const offset =
				body.data.q != null
					? parabolicToPositionJD(body.data, jd)
					: orbitalElementsToPositionJD(body.data, jd);
			if (!offset) {
				writeIdx++;
				continue;
			}
			const x = px + offset[0];
			const y = py + offset[1];
			const z = pz + offset[2];
			body.position[0] = x;
			body.position[1] = y;
			body.position[2] = z;
			arr[writeIdx * 3] = x - bx;
			arr[writeIdx * 3 + 1] = y - by;
			arr[writeIdx * 3 + 2] = z - bz;
			writeIdx++;
		}
		posAttr.needsUpdate = true;
	}

	private rebuildMoonPointClouds(): void {
		const basis = this.pointCloudBasisPos;
		for (const [parentId, moons] of this.getMoonsByParent()) {
			const existing = this.moonPoints.get(parentId);
			if (!existing) continue;
			const positions = new Float32Array(moons.length * 3);
			for (let i = 0; i < moons.length; i++) {
				positions[i * 3] = moons[i].position[0] - basis[0];
				positions[i * 3 + 1] = moons[i].position[1] - basis[1];
				positions[i * 3 + 2] = moons[i].position[2] - basis[2];
			}
			existing.geometry.setAttribute('position', new Float32BufferAttribute(positions, 3));
		}
	}

	/**
	 * Rebase the cached orbit-local vertices against the current focus (no
	 * Kepler recompute). Used by focus animation paths; the per-jd path goes
	 * through {@link refreshOrbitLineGeometry} instead.
	 */
	private rebuildOrbitLineBasis(): void {
		const [fx, fy, fz] = this.focus.focusTruePos;
		for (const bo of this.bodyObjects.values()) {
			const line = bo.orbitLine;
			if (!line) continue;
			const localPositions = line.userData.orbitLocalPositions as
				| [number, number, number][]
				| undefined;
			if (!localPositions) continue;
			const oc = line.userData.orbitCenter as Vector3;
			const ox = oc.x - fx,
				oy = oc.y - fy,
				oz = oc.z - fz;
			const posAttr = line.geometry.getAttribute('position');
			const arr = posAttr.array as Float32Array;
			for (let i = 0; i < localPositions.length; i++) {
				arr[i * 3] = localPositions[i][0] + ox;
				arr[i * 3 + 1] = localPositions[i][1] + oy;
				arr[i * 3 + 2] = localPositions[i][2] + oz;
			}
			posAttr.needsUpdate = true;
		}
	}

	/**
	 * Quaternion of the currently focused body's mesh, for body-fixed lat/lon.
	 * Returns undefined if there's no mesh (e.g., focus on a point-cloud body) —
	 * callers then fall back to scene-frame lat/lon.
	 */
	private focusedBodyQuat(body?: PositionedBody): [number, number, number, number] | undefined {
		const id = (body ?? this.focusedBody)?.data.id;
		if (!id) return undefined;
		const mesh = this.bodyObjects.get(id)?.mesh;
		if (!mesh) return undefined;
		const q = mesh.quaternion;
		return [q.x, q.y, q.z, q.w];
	}

	// Reconstruct camera true world position (Float64)
	private cameraTruePos(): Vec3 {
		return [
			this.focus.focusTruePos[0] + this.camera.position.x,
			this.focus.focusTruePos[1] + this.camera.position.y,
			this.focus.focusTruePos[2] + this.camera.position.z
		];
	}

	// --- Per-frame body position & orientation updates ---

	private updatePositions(jd: number): void {
		// Seed positionMap with SSB at origin. Iterate ALL bodies with orbit
		// elements (majors, moons, barycenters, promoted minor bodies). Moons'
		// parentId is the planetary barycenter (SPICE convention: Io → naif-5),
		// not the planet, so barycenters must be in the map for children to
		// find their parent; barycenters are in ctx.bodiesById but not meshed.
		const positionMap = new Map<string, Vec3>();
		positionMap.set('naif-0', [0, 0, 0]);

		// Propagate position from `body.data` (the body's own elements around
		// its parent), NOT `body.orbitElements` — for planets those differ:
		// `orbitElements` stores the barycenter's orbit around SSB so the
		// orbit line is drawn correctly, while `body.data.a === 0` means
		// "planet sits at its own barycenter" for positioning. Adding the
		// barycenter's offset on top of the barycenter's position would
		// double-count it.
		// Pass 1: compute positions and update orbitCenters. Do NOT touch orbit
		// line geometry yet — it depends on focus.focusTruePos, which we can't
		// update until the focused body's own position is known below.
		const computePosition = (body: PositionedBody) => {
			const d = body.data;
			const parentPos = positionMap.get(d.parentId) ?? ([0, 0, 0] as Vec3);
			const isParabolic = d.q != null;
			let x: number, y: number, z: number;
			if (d.a === 0 && !isParabolic) {
				// Body coincides with its parent (e.g. planet at its barycenter).
				[x, y, z] = parentPos;
			} else {
				const offset = isParabolic
					? parabolicToPositionJD(d, jd)
					: orbitalElementsToPositionJD(d, jd);
				if (!offset) return;
				x = parentPos[0] + offset[0];
				y = parentPos[1] + offset[1];
				z = parentPos[2] + offset[2];
			}
			body.position[0] = x;
			body.position[1] = y;
			body.position[2] = z;
			if (body.orbitCenter) {
				body.orbitCenter[0] = parentPos[0];
				body.orbitCenter[1] = parentPos[1];
				body.orbitCenter[2] = parentPos[2];
			}
			positionMap.set(d.id, body.position);

			const bo = this.bodyObjects.get(d.id);
			if (!bo) return;
			if (bo.orbitLine && body.orbitCenter) {
				const oc = bo.orbitLine.userData.orbitCenter as Vector3 | undefined;
				if (oc) oc.set(parentPos[0], parentPos[1], parentPos[2]);
			}
			if (bo.orientation && bo.mesh) {
				applyOrientation(bo.mesh, bo.orientation, jd);
			}
		};

		// First pass: bodies in ctx.bodiesById (barycenters → planets → moons,
		// in dependency order). Second pass: promoted minor bodies that only
		// live in bodyObjects, whose parents are now in positionMap.
		for (const body of this.ctx.bodiesById.values()) computePosition(body);
		for (const bo of this.bodyObjects.values()) {
			if (!this.ctx.bodiesById.has(bo.body.data.id)) computePosition(bo.body);
		}

		// Pass 2a: now that all positions are current, lock focus onto the
		// focused body's *new* position (unless an animation is driving it).
		if (this.focusedBody) {
			const p = this.focusedBody.position;
			const elapsed = performance.now() - this.focus.focusStartTime;
			const animating = elapsed < this.focus.focusDurationMs;
			this.focus.focusTargetWorld[0] = p[0];
			this.focus.focusTargetWorld[1] = p[1];
			this.focus.focusTargetWorld[2] = p[2];
			if (!animating) {
				this.focus.focusTruePos[0] = p[0];
				this.focus.focusTruePos[1] = p[1];
				this.focus.focusTruePos[2] = p[2];
			}
		}

		// Pass 2b: refresh orbit-line geometry against the fresh focus basis.
		// If we did this inside computePosition, vertices would be stored
		// against last frame's focus, and rendering (which uses the new focus)
		// would shift every trail by focus-velocity * dt — visible as trails
		// "preceding" the body along the focus's own orbit direction.
		const basis = this.focus.focusTruePos;
		for (const bo of this.bodyObjects.values()) {
			const line = bo.orbitLine;
			if (line) refreshOrbitLineGeometry(bo.body, line, basis);
		}
	}

	// --- RAF loop ---

	private tick = (): void => {
		this.rafId = requestAnimationFrame(this.tick);

		// Snap controls target on first frame
		if (this.firstFrame) {
			this.firstFrame = false;
			this.controls.target.set(0, 0, 0);
			this.controls.update();
		}

		// Gate body updates on jd actually changing — fires for play, pause→now,
		// and manual setJD alike; skips work while paused.
		this.clock.tick(performance.now());
		// A drop from "phases frozen" to "phases live" (pause, slow-down, `now`)
		// also requires a recompute, even if jd didn't advance.
		const exitingFreeze =
			this.spacecraftFrozen && Math.abs(this.clock.timeScale) < SPACECRAFT_PHASE_FREEZE_RATE;
		if (this.clock.jd !== this.lastUpdatedJd || exitingFreeze) {
			this.lastUpdatedJd = this.clock.jd;
			this.updatePositions(this.clock.jd);
			this.updatePointClouds(this.clock.jd);
			// When animating, stepFocusAnimation below does repositionAll already.
			const elapsed = performance.now() - this.focus.focusStartTime;
			if (elapsed >= this.focus.focusDurationMs) {
				this.repositionBodies();
				this.maybeRebasePointClouds();
			}
		}

		// Animate focus/fly
		const controlsSettled = stepFocusAnimation(
			this.focus,
			this.camera,
			this.controls,
			() => this.repositionAll(),
			() => this.rebuildPointCloudBasis()
		);
		if (this.pendingUrlWrite && controlsSettled) {
			this.pendingUrlWrite = false;
			const { latitude, longitude, distance } = this.getCameraState();
			this.callbacks.onCameraPosition?.(latitude, longitude, distance);
		}

		// Camera state → visibility decisions
		const { distance } = this.getCameraState();
		this.ctx.updateCamera(distance);

		// Per-frame visibility, label, and orbit line updates
		this.cullFrameCounter = updateBodyVisibility(
			this.bodyObjects,
			this.camera,
			this.ctx,
			this.focus.focusTruePos,
			this.focusedBody?.data.id,
			this.hideCappedMoonLabels,
			this.hoveredBodyIds,
			this.asteroidPoints,
			this.spacecraftPoints,
			this.moonPoints,
			this.cullFrameCounter,
			this.renderer,
			this._tmpV3
		);

		this.updateTextureLOD();

		// Shadow light: swap between PointLight (solar system) and DirectionalLight (sub-system)
		const sysId = this.ctx.activeSystemId;
		if (sysId) {
			// Sun direction in focus-relative coordinates
			const sunPos = this.bodyObjects.get('naif-10')?.body.position;
			const [fx, fy, fz] = this.focus.focusTruePos;
			const sunRelX = (sunPos?.[0] ?? 0) - fx;
			const sunRelY = (sunPos?.[1] ?? 0) - fy;
			const sunRelZ = (sunPos?.[2] ?? 0) - fz;
			const sunDir = this._tmpV3.set(sunRelX, sunRelY, sunRelZ).normalize();

			const lightDist = 10;
			this.shadowLight.position.copy(sunDir).multiplyScalar(lightDist);
			this.shadowLight.target.position.set(0, 0, 0);
			this.shadowLight.intensity = 2;
			if (this.sunPointLight) this.sunPointLight.intensity = 0;

			// Lateral extent: tight to camera view for high texel density.
			// Depth extent: clamped to camera vicinity so shadow-map depth
			// precision stays high (full system extent causes banding on mobile).
			const lateral = Math.max(distance * 2, 0.001);
			const depthExtent = Math.min(this.ctx.getSystemExtent(sysId) * AU_SCALE * 1.2, lateral * 4);
			const shadowCam = this.shadowLight.shadow.camera;
			shadowCam.left = shadowCam.bottom = -lateral;
			shadowCam.right = shadowCam.top = lateral;
			shadowCam.near = lightDist - depthExtent;
			shadowCam.far = lightDist + depthExtent;
			shadowCam.updateProjectionMatrix();
		} else {
			this.shadowLight.intensity = 0;
			if (this.sunPointLight) this.sunPointLight.intensity = 2;
		}

		// Auto-promote one default-important minor body per frame
		if (this.pendingDefaultPromotions.size > 0) {
			for (const id of this.pendingDefaultPromotions) {
				if (this.bodyObjects.has(id)) {
					this.pendingDefaultPromotions.delete(id);
					continue;
				}
				const body = this.ctx.getBody(id);
				if (!body) continue; // not in exported data, skip
				this.pendingDefaultPromotions.delete(id);
				this.ensureBodyObjects(body);
				break; // one per frame to spread GPU work
			}
		}

		// Stagger new point cloud additions: one per frame to spread GPU upload cost
		if (this.pendingSceneAdds.length > 0) {
			this.scene.add(this.pendingSceneAdds.shift()!);
		}

		this.renderer.render(this.scene, this.camera);
		this.labelRenderer.render(this.scene, this.camera);
	};

	// --- Interaction ---

	private getCameraState() {
		const cam = this.camera.position;
		return cartesianToSpherical([cam.x, cam.y, cam.z], [0, 0, 0], this.focusedBodyQuat());
	}

	private onControlsEnd = (): void => {
		this.pendingUrlWrite = true;
		// User-initiated motion wins — don't overwrite it when orientation loads.
		this.pendingInitialView = null;
	};

	private onPointerDown = (e: PointerEvent): void => {
		this.pointerDownPos.set(e.clientX, e.clientY);
	};

	private onPointerUp = (e: PointerEvent): void => {
		const dx = e.clientX - this.pointerDownPos.x;
		const dy = e.clientY - this.pointerDownPos.y;
		if (dx * dx + dy * dy > 9) return;

		const canvas = this.renderer.domElement;
		const rect = canvas.getBoundingClientRect();
		this.pointer.set(
			((e.clientX - rect.left) / rect.width) * 2 - 1,
			-((e.clientY - rect.top) / rect.height) * 2 + 1
		);
		this.raycaster.setFromCamera(this.pointer, this.camera);

		// Check mesh hits (planets, stars, etc.)
		const hits = this.raycaster.intersectObjects(this.clickables);
		let bestBody: PositionedBody | undefined;
		let bestDist = Infinity;
		if (hits.length > 0) {
			const body = this.meshToBody.get(hits[0].object as Mesh);
			if (body) {
				bestBody = body;
				bestDist = hits[0].distance;
			}
		}

		// Check point cloud bodies (asteroids, spacecraft, moons shown as dots)
		const pointHit = pickPointCloudBody(
			this.pointer,
			this.camera,
			this.ctx,
			this.focus.focusTruePos,
			canvas.clientWidth,
			canvas.clientHeight,
			this._tmpV3
		);
		if (pointHit && pointHit.distance < bestDist) {
			bestBody = pointHit.body;
		}

		if (bestBody && bestBody.data.id !== this.focusedBody?.data.id) {
			this.handleFocus(bestBody);
		}
	};

	/** Load system metadata (textures + orientation) for the focused system (if changed). */
	private maybeLoadSystemData(): void {
		const sysId = this.ctx.focusedSystemId;
		if (!sysId) return;
		// Resolve to barycenter: if sysId is a planet (e.g. naif-599), its parent is the barycenter
		const body = this.ctx.getBody(sysId);
		const baryId =
			body?.data.objectType === ObjectType.BARYCENTER ? sysId : (body?.data.parentId ?? sysId);
		if (baryId === this.lastSystemTextureBarycenter) return;
		this.lastSystemTextureBarycenter = baryId;
		loadSystemData(baryId, this.bodyObjects, this.textureLoader, this.clock.jd).then(() =>
			this.reapplyInitialViewIfPending()
		);
	}

	/**
	 * Re-place the camera using the URL's body-fixed lat/lon once the focused
	 * body's orientation has been applied. The initial placement in the
	 * constructor runs before orientation fetches, so it falls back to
	 * scene-frame; this corrects for that as soon as the mesh is oriented.
	 */
	private reapplyInitialViewIfPending(): void {
		const pending = this.pendingInitialView;
		if (!pending) return;
		const quat = this.focusedBodyQuat();
		// If the mesh still has identity quaternion, the body has no orientation
		// data (e.g. asteroids) — the initial scene-frame placement stands.
		if (!quat || (quat[0] === 0 && quat[1] === 0 && quat[2] === 0 && quat[3] === 1)) {
			this.pendingInitialView = null;
			return;
		}
		const camPos = sphericalToCartesian(
			[0, 0, 0],
			pending.latitude,
			pending.longitude,
			pending.zoom,
			quat
		);
		this.camera.position.set(...camPos);
		this.controls.update();
		this.pendingInitialView = null;
	}

	private maybeLoadTexture(body: PositionedBody): void {
		const bo = this.bodyObjects.get(body.data.id);
		if (!bo) return;
		loadBodyTexture(bo, this.textureLoader, body.data.objectFileFlag);
	}

	/**
	 * Per-frame texture LOD: upgrade each visible body's texture tier based on
	 * its screen-space radius. One-way upgrade — the prior texture is disposed
	 * when a higher tier loads, so at most one tier per body lives on the GPU.
	 */
	private updateTextureLOD(): void {
		if (!this.ctx.activeSystemId) return;
		const fovRad = (this.camera.fov * Math.PI) / 180;
		const screenH = this.renderer.domElement.clientHeight;
		const projScale = screenH / (2 * Math.tan(fovRad / 2));

		for (const bo of this.bodyObjects.values()) {
			if (!bo.mesh || !bo.radiusScene || !bo.group.visible) continue;
			if (!bo.availableTiers?.length || bo.textureLoading) continue;
			if (bo.cachedDist <= 0) continue;
			if (!this.ctx.isInActiveSystem(bo.body.data.parentId)) continue;

			const screenR = (bo.radiusScene / bo.cachedDist) * projScale;
			let desired: 'low' | 'medium' | 'high';
			if (screenR < 256) desired = 'low';
			else if (screenR < 1024) desired = 'medium';
			else desired = 'high';

			const TIER_RANK = { low: 0, medium: 1, high: 2 } as const;
			const currentRank = bo.textureTier
				? (TIER_RANK[bo.textureTier as keyof typeof TIER_RANK] ?? -1)
				: -1;
			if (TIER_RANK[desired] <= currentRank) continue;

			// Clamp desired down to the highest available tier we haven't loaded.
			let target: string | undefined;
			for (let r = TIER_RANK[desired]; r > currentRank; r--) {
				const name = (['low', 'medium', 'high'] as const)[r];
				if (bo.availableTiers.includes(name)) {
					target = name;
					break;
				}
			}
			if (!target) continue;
			loadBodyTextureTier(bo, target, this.textureLoader);
		}
	}

	private handleFocus(body: PositionedBody): void {
		this.setFocusTarget(body);
		const camWorld = this.cameraTruePos();
		const { latitude, longitude, distance } = cartesianToSpherical(
			camWorld,
			body.position,
			this.focusedBodyQuat(body)
		);
		this.callbacks.onCameraPosition?.(latitude, longitude, distance);
	}

	/** Build mesh, label, halo, and orbit line for a body that only existed as a point-cloud dot. */
	private ensureBodyObjects(body: PositionedBody): void {
		if (this.bodyObjects.has(body.data.id)) return;
		// Minor bodies from chunks lack orbitElements; populate from data so orbit lines can be built
		if (!body.orbitElements) {
			body.orbitElements = body.data;
			const parent = this.bodyObjects.get(body.data.parentId);
			if (parent) body.orbitCenter = [...parent.body.position];
		}
		buildMajorBodies(
			[body],
			this.scene,
			this.clickables,
			this.meshToBody,
			this.bodyObjects,
			this.circleTexture,
			this.renderer.domElement,
			(b) => this.handleFocus(b),
			(id, hovered) => (hovered ? this.hoveredBodyIds.add(id) : this.hoveredBodyIds.delete(id))
		);
		buildOrbitLines(this.bodyObjects, this.scene, this.pointCloudBasisPos);
		this.repositionAll();

		// Rebuild the point cloud for this body's group so the promoted dot is removed
		if (body.data.objectType === ObjectType.SPACECRAFT) {
			this.ctx.dirtySpacecraftGroups.add(body.data.parentId);
		} else if (isAsteroid(body.data.objectType) || body.data.objectType === ObjectType.COMET) {
			for (const [zone, bodies] of this.ctx.asteroidBodiesByZone) {
				if (bodies.some((b) => b.data.id === body.data.id)) {
					this.ctx.dirtyAsteroidZones.add(zone);
					break;
				}
			}
		}
		this.rebuildMinorPointClouds();
	}

	// --- Public API ---

	focusOnBody(id: string, zoom?: number, latitude?: number, longitude?: number): number {
		const body = this.ctx.getBody(id);
		if (!body) return 0;
		let camPos: Vec3 | undefined;
		if (zoom !== undefined) {
			if (latitude !== undefined && longitude !== undefined) {
				camPos = sphericalToCartesian(
					body.position,
					latitude,
					longitude,
					zoom,
					this.focusedBodyQuat(body)
				);
			} else {
				// Place camera at `zoom` distance, arriving from the current camera direction
				const camWorld = this.cameraTruePos();
				const dir = this._tmpV3
					.set(
						body.position[0] - camWorld[0],
						body.position[1] - camWorld[1],
						body.position[2] - camWorld[2]
					)
					.normalize()
					.negate();
				camPos = [
					body.position[0] + dir.x * zoom,
					body.position[1] + dir.y * zoom,
					body.position[2] + dir.z * zoom
				];
			}
		}
		// Emit the target camera position before any focus/fly dispatch so that
		// downstream `lastCameraPos` is fresh when `onFocusChange` fires inside
		// `setFocusTarget` and `pushUrlState` captures the intended destination.
		const emitFrom = camPos ?? this.cameraTruePos();
		const spherical = cartesianToSpherical(emitFrom, body.position, this.focusedBodyQuat(body));
		this.callbacks.onCameraPosition?.(spherical.latitude, spherical.longitude, spherical.distance);
		if (zoom !== undefined && camPos) {
			if (this.focusedBody?.data.id === id) {
				// Snap focus in case a prior fly animation hasn't fully settled
				this.focus.focusTruePos = [...body.position];
				this.repositionAll();
				this.rebuildPointCloudBasis();
				prepareFlyToCamera(this.focus, this.camera, this.cameraTruePos(), camPos);
			} else {
				this.setFocusTarget(body, camPos);
				if (latitude !== undefined && longitude !== undefined) {
					// Use orbit mode so Earth stays centered during approach
					this.focus.orbitFly = true;
				}
			}
		} else {
			this.setFocusTarget(body);
		}
		return this.focus.focusDurationMs;
	}

	setFocusTarget(body: PositionedBody, camPos?: Vec3): void {
		this.ensureBodyObjects(body);
		this.focusedBody = body;
		this.controls.minDistance = minCameraDistance(body);
		this.ctx.setFocused(body);
		this.callbacks.onFocusChange(body);
		this.maybeLoadTexture(body);
		this.maybeLoadSystemData();
		prepareFocusTarget(this.focus, [...body.position], this.camera, this.cameraTruePos(), camPos);
	}

	getFocusedBody(): PositionedBody | undefined {
		return this.focusedBody;
	}

	resize(width: number, height: number): void {
		this.renderer.setSize(width, height, false);
		this.labelRenderer.setSize(width, height);
		this.camera.aspect = width / height;
		this.camera.updateProjectionMatrix();
		this.ctx.updateViewport(height);
	}

	dispose(): void {
		cancelAnimationFrame(this.rafId);
		this.renderer.domElement.removeEventListener('pointerdown', this.onPointerDown);
		this.renderer.domElement.removeEventListener('pointerup', this.onPointerUp);
		this.controls.removeEventListener('end', this.onControlsEnd);
		this.controls.dispose();
		this.renderer.dispose();
	}
}

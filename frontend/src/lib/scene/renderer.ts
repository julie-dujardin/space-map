import {
	AmbientLight,
	BufferAttribute,
	DirectionalLight,
	Float32BufferAttribute,
	Mesh,
	PCFSoftShadowMap,
	PerspectiveCamera,
	PointLight,
	Points,
	Quaternion,
	Raycaster,
	Scene,
	TextureLoader,
	Vector2,
	Vector3,
	WebGLRenderer
} from 'three';
import { CSS2DRenderer } from 'three/addons/renderers/CSS2DRenderer.js';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { cartesianToSpherical, sphericalToCartesian } from '$lib/math/spherical';
import type { MapViewState } from '$lib/state/view';
import { ObjectType, isAsteroid, type PositionedBody } from '$lib/types/objects';
import type { ContextManager } from '$lib/scene/context-manager.svelte';
import type { SimClock } from '$lib/scene/clock.svelte';
import { AU_SCALE, kmToScene } from '$lib/math/units';
import { applyOrientation } from '$lib/math/orientation';
import { bodyNorthVector } from '$lib/scene/north-reference';
import { jdToDate } from '$lib/format/date';
import { orbitalElementsToPositionJD, parabolicToPositionJD } from '$lib/math/orbit/position';
import { sgp4PositionScene } from '$lib/math/orbit/sgp4';
import { refreshMinorBodyPosition } from '$lib/scene/minor-body-position';
import {
	buildMajorBodies,
	loadBodyLabel,
	buildOrbitLines,
	buildPointClouds,
	loadBodyTexture,
	loadBodyTextureTier,
	loadSystemData,
	makeCircleTexture
} from './objects/construction';
import {
	makePointCloudFromBuffer,
	rebaseOrbitLineLocals,
	refreshOrbitLineGeometry,
	setOrbitLineResolution
} from './objects/builders';
import { getEclipseSceneUniforms, MAX_OCCLUDERS } from './objects/eclipse-shadow';
import { resolveBodyColor } from '$lib/utils';
import { OrbitWorkerPool } from '$lib/math/orbit/pool';
import { type BodyObjects, type Callbacks } from './types';
import { fetchLabels } from '$lib/fetch/position/labels';
import { MINOR_PROMOTED_IDS } from '$lib/constants';
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
import { emptyGroup, updateOutOfRangeToast, type OutOfRangeState } from './out-of-range-toast';
import { createUserLocationMarker, removeUserLocationMarker } from './user-location';
import type { CSS2DObject } from 'three/addons/renderers/CSS2DRenderer.js';

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
	private orbitPool = new OrbitWorkerPool();
	private asteroidPoints = new Map<string, Points>();
	private lastSystemTextureBarycenter: string | null = null;
	private spacecraftPoints = new Map<string, Points>();
	private moonPoints = new Map<string, Points>();
	private clickables: Mesh[] = [];
	private meshToBody = new Map<Mesh, PositionedBody>();
	private pendingSceneAdds: Points[] = [];
	/** Bodies to auto-promote from point clouds to individual meshes on initial
	 *  load. Populated asynchronously from the global labels file (whose keys
	 *  *are* the promoted set). The auto-promote loop is a no-op until labels
	 *  resolve a few hundred ms after construction. */
	private pendingDefaultPromotions: Set<string> = new Set();
	/** Stable copy of the curated default-promoted set (labels keys ∪
	 *  MINOR_PROMOTED_IDS). Unlike {@link pendingDefaultPromotions} this is
	 *  never drained — it's the "exempt from clear" set queried at clear time
	 *  and at promotion time to decide whether a body counts as user-promoted. */
	private defaultPromotedIds: Set<string> = new Set();
	/** Bodies the user promoted by clicking or by URL navigation (not part of
	 *  the curated default set, not built at scene construction). These can be
	 *  reverted to point-cloud dots via {@link clearUserPromoted}. */
	private userPromotedIds: Set<string> = new Set();
	private hoveredBodyIds = new Set<string>();
	private cullFrameCounter = 0;

	// TODO: expose via UI settings
	hideCappedMoonLabels = false;

	private focusedBody: PositionedBody | undefined;
	private readonly _tmpV3 = new Vector3();
	private readonly _tmpUserLoc = new Vector3();

	/** Body whose IAU pole drives camera.up. null = ecliptic Y (scene frame). */
	private northRefId: string | null = null;
	private readonly upStartVec = new Vector3(0, 1, 0);
	private readonly upTargetVec = new Vector3(0, 1, 0);
	private readonly upCurrentVec = new Vector3(0, 1, 0);
	private upAnimStartTime = -Infinity;
	private static readonly UP_ANIM_DURATION_MS = 400;
	private readonly _upQuatA = new Quaternion();
	private readonly _upQuatB = new Quaternion();
	private static readonly _upRef = new Vector3(0, 1, 0);

	// Focus/fly animation state (mutated by animation module)
	private readonly focus: FocusState = {
		focusTruePos: [0, 0, 0],
		focusOriginWorld: [0, 0, 0],
		focusTargetWorld: [0, 0, 0],
		camOriginWorld: null,
		camTargetWorld: null,
		camTargetOffset: null,
		flyQ0: null,
		flyQ1: null,
		orbitFly: false,
		focusStartTime: 0,
		focusDurationMs: FOCUS_DURATION_MS
	};
	private pointCloudBasisPos: Vec3 = [0, 0, 0];
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
	/** Pinned user-location dot on Earth's surface (Google-Maps-style). */
	private userLocationMarker: CSS2DObject | null = null;

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

		// Promoted set is exactly the keys of the global per-language labels file.
		// Fire-and-forget: the auto-promote loop reads the set every frame and is
		// a no-op until labels resolve a few hundred ms later.
		fetchLabels().then((labels) => {
			for (const id of labels.keys()) {
				this.pendingDefaultPromotions.add(id);
				this.defaultPromotedIds.add(id);
			}
			// Minor-promoted bodies still need to be built as halos. They may or
			// may not be in the labels file (cheb-covered ones are) — adding here
			// is idempotent and covers those that aren't.
			for (const id of MINOR_PROMOTED_IDS) {
				this.pendingDefaultPromotions.add(id);
				this.defaultPromotedIds.add(id);
			}
			// URL-navigation that landed before labels resolved may have flagged a
			// curated body as user-promoted; reconcile now that the truth is known.
			let pruned = false;
			for (const id of this.userPromotedIds) {
				if (this.defaultPromotedIds.has(id)) {
					this.userPromotedIds.delete(id);
					pruned = true;
				}
			}
			if (pruned) this.emitUserPromotedCount();
		});

		// Renderer
		this.renderer = new WebGLRenderer({ canvas, logarithmicDepthBuffer: true, antialias: true });
		this.renderer.setPixelRatio(window.devicePixelRatio);
		this.renderer.setSize(canvas.clientWidth, canvas.clientHeight, false);
		// Fat orbit lines expand by `width / resolution` in NDC; feed the CSS-pixel
		// size so the requested width reads as pixels regardless of devicePixelRatio.
		setOrbitLineResolution(canvas.clientWidth, canvas.clientHeight);
		this.renderer.shadowMap.enabled = true;
		this.renderer.shadowMap.type = PCFSoftShadowMap;

		// CSS2D label renderer
		this.labelRenderer = new CSS2DRenderer({ element: labelContainer });
		this.labelRenderer.setSize(canvas.clientWidth, canvas.clientHeight);
		ctx.updateViewport(canvas.clientHeight);

		// Scene + lights
		this.scene = new Scene();
		this.scene.add(new AmbientLight(0xffffff, 0.01));

		// Directional sun light for sub-system view (swapped in when zoomed
		// into a planet's moon system; PointLight at the Sun handles
		// solar-system view). Body-on-body shadows are computed analytically
		// per-fragment (see `attachEclipseShadowToBody` and
		// `attachRingShadowToPlanet`), so no shadow map is needed.
		this.shadowLight = new DirectionalLight(0xffffff, 0);
		this.shadowLight.castShadow = false;
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

		this.orbitPool.setResultHandler(this.onPoolResult);

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
		scheduleIdle(() => buildOrbitLines(this.bodyObjects, this.scene, basis, this.clock.jd));
	}

	/**
	 * Refresh the pool's owned group set and the matching Three.js geometries
	 * for zones/groups marked dirty since the last rebuild. New chunks landing,
	 * the promoted set changing, and basis rebuilds all add to the dirty markers
	 * — this method drains them.
	 *
	 * Worker ticks asynchronously refresh the positions; this method just
	 * (re)wires the handoff between the pool and the Three.js geometries for
	 * the affected groups, and ensures brand-new zones get a Points object
	 * seeded from `body.position`. Existing groups keep the pool's worker-
	 * computed front buffer — overwriting would clobber fresh data with stale
	 * load-time positions and flicker the cloud between current and load-time
	 * locations on every rebase.
	 */
	rebuildMinorPointClouds(): void {
		if (this.ctx.dirtyAsteroidZones.size === 0 && this.ctx.dirtySpacecraftGroups.size === 0) {
			return;
		}
		const skip = new Set(this.bodyObjects.keys());
		const seedBasis: Vec3 = [
			this.pointCloudBasisPos[0],
			this.pointCloudBasisPos[1],
			this.pointCloudBasisPos[2]
		];

		for (const zone of this.ctx.dirtyAsteroidZones) {
			const groupId = `asteroid:${zone}`;
			const bodies = this.ctx.asteroidBodiesByZone.get(zone);
			if (!bodies || bodies.length === 0) {
				this.orbitPool.unwireOne(groupId);
				const stale = this.asteroidPoints.get(zone);
				if (stale) {
					this.scene.remove(stale);
					this.asteroidPoints.delete(zone);
				}
				continue;
			}
			this.orbitPool.rewireOne(groupId, bodies, skip);
			const front = this.orbitPool.front(groupId);
			if (!front) continue;
			const existing = this.asteroidPoints.get(zone);
			if (existing) {
				existing.geometry.setAttribute('position', new BufferAttribute(front, 3));
			} else {
				this.seedFrontFromBodies(front, bodies);
				const pts = makePointCloudFromBuffer(
					front,
					bodies.length,
					this.circleTexture,
					resolveBodyColor(bodies[0].data)
				);
				pts.userData.frontBasis = seedBasis;
				this.asteroidPoints.set(zone, pts);
				this.pendingSceneAdds.push(pts);
			}
		}
		this.ctx.dirtyAsteroidZones.clear();

		for (const gid of this.ctx.dirtySpacecraftGroups) {
			const groupId = `spacecraft:${gid}`;
			const bodies = this.ctx.spacecraftByParent.get(gid);
			if (!bodies || bodies.length === 0) {
				this.orbitPool.unwireOne(groupId);
				const stale = this.spacecraftPoints.get(gid);
				if (stale) {
					this.scene.remove(stale);
					this.spacecraftPoints.delete(gid);
				}
				continue;
			}
			this.orbitPool.rewireOne(groupId, bodies, skip);
			const front = this.orbitPool.front(groupId);
			if (!front) continue;
			const existing = this.spacecraftPoints.get(gid);
			if (existing) {
				existing.geometry.setAttribute('position', new BufferAttribute(front, 3));
			} else {
				this.seedFrontFromBodies(front, bodies);
				const pts = makePointCloudFromBuffer(
					front,
					bodies.length,
					this.circleTexture,
					resolveBodyColor(bodies[0].data)
				);
				pts.userData.frontBasis = seedBasis;
				this.spacecraftPoints.set(gid, pts);
				this.pendingSceneAdds.push(pts);
			}
		}
		this.ctx.dirtySpacecraftGroups.clear();
	}

	/** Fill a pool-owned Float32Array with basis-relative body positions (for the 1-2 frames before the first worker tick result arrives). */
	private seedFrontFromBodies(front: Float32Array, bodies: PositionedBody[]): void {
		const [bx, by, bz] = this.pointCloudBasisPos;
		const n = Math.min(bodies.length, front.length / 3);
		for (let i = 0; i < n; i++) {
			const p = bodies[i].position;
			front[i * 3] = p[0] - bx;
			front[i * 3 + 1] = p[1] - by;
			front[i * 3 + 2] = p[2] - bz;
		}
	}

	/** Pool result handler: swap the returned buffer into the geometry. */
	private onPoolResult = (
		groupId: string,
		positions: Float32Array,
		count: number,
		basisUsed: Vec3,
		parentUsed: Vec3
	): void => {
		const [kind, key] = groupId.split(':') as ['asteroid' | 'spacecraft', string];
		const pts = kind === 'asteroid' ? this.asteroidPoints.get(key) : this.spacecraftPoints.get(key);
		if (!pts) return;
		pts.geometry.setAttribute('position', new BufferAttribute(positions, 3));
		pts.geometry.setDrawRange(0, count);
		// Record the basis the worker used; repositionPointClouds applies this
		// per-group so a mid-flight rebase doesn't misplace the cloud for the
		// frame between the basis change and the next worker result.
		pts.userData.frontBasis = [basisUsed[0], basisUsed[1], basisUsed[2]];

		// Snapshot the parent's position *as it was passed to the worker at
		// dispatch* (not the parent's position now): {@link parentShift}
		// compensates for parent motion between the jd the worker solved for
		// and the current frame. Snapshotting the post-result parent would
		// hide the worker-latency motion — that error becomes visible at high
		// time rates and freezes in when the user pauses.
		this.pointCloudParentAtUpdate.set(groupId, [parentUsed[0], parentUsed[1], parentUsed[2]]);

		// Re-position the Points container *now*, against the new frontBasis
		// and parent snapshot. The per-frame repositioner only runs when jd
		// changes, so without this a worker result arriving while paused would
		// leave pts.position pinned to its pre-result value while the geometry
		// it wraps used a different basis — the cloud would render visibly
		// offset from where its bodies actually orbit.
		const [fx, fy, fz] = this.focus.focusTruePos;
		const parentNowId = kind === 'asteroid' ? 'naif-10' : key;
		const parentNow = this.ctx.getBody(parentNowId)?.position;
		const sx = parentNow ? parentNow[0] - parentUsed[0] : 0;
		const sy = parentNow ? parentNow[1] - parentUsed[1] : 0;
		const sz = parentNow ? parentNow[2] - parentUsed[2] : 0;
		pts.position.set(basisUsed[0] - fx + sx, basisUsed[1] - fy + sy, basisUsed[2] - fz + sz);
	};

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
		const currentBasis = this.pointCloudBasisPos;
		// Minor-body clouds use the *per-group* basis the worker computed under,
		// not `pointCloudBasisPos` — a rebase that lands between tick-dispatch
		// and worker result would otherwise misplace the cloud by the rebase
		// distance for 1-2 frames, causing visible flicker when focus drifts.
		for (const [zone, pts] of this.asteroidPoints) {
			const b = (pts.userData.frontBasis as Vec3 | undefined) ?? currentBasis;
			const [sx, sy, sz] = this.parentShift(`asteroid:${zone}`, 'naif-10');
			pts.position.set(b[0] - fx + sx, b[1] - fy + sy, b[2] - fz + sz);
		}
		for (const [gid, pts] of this.spacecraftPoints) {
			const b = (pts.userData.frontBasis as Vec3 | undefined) ?? currentBasis;
			const [sx, sy, sz] = this.parentShift(`spacecraft:${gid}`, gid);
			pts.position.set(b[0] - fx + sx, b[1] - fy + sy, b[2] - fz + sz);
		}
		// Moon point clouds are re-written every frame (writeMoonPointClouds),
		// so vertex buffers are always current — no shift needed.
		const [bx, by, bz] = currentBasis;
		const dx = bx - fx,
			dy = by - fy,
			dz = bz - fz;
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
	 * Dispatch a per-frame Kepler solve to the worker pool for every asteroid
	 * zone and spacecraft group. Moons remain on the main thread — they read
	 * already-computed coords from majorBodies, so they're nearly free.
	 *
	 * Worker roundtrip latency means individual groups refresh at ~½× the tick
	 * rate; {@link parentShift} compensates parent motion between refreshes.
	 */
	private updatePointClouds(jd: number): void {
		this.writeMoonPointClouds();

		const parents = new Map<string, Vec3>();
		const sunPos = this.ctx.getBody('naif-10')?.position ?? ([0, 0, 0] as Vec3);
		for (const [zone] of this.ctx.asteroidBodiesByZone) {
			parents.set(`asteroid:${zone}`, [sunPos[0], sunPos[1], sunPos[2]]);
		}
		for (const [gid] of this.ctx.spacecraftByParent) {
			const pp = this.ctx.getBody(gid)?.position ?? ([0, 0, 0] as Vec3);
			parents.set(`spacecraft:${gid}`, [pp[0], pp[1], pp[2]]);
		}
		this.orbitPool.tick(jd, this.pointCloudBasisPos, parents);
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
			// Skip groups whose point cloud isn't shown — saves a vertex-buffer
			// rewrite + GPU upload per parent in any non-focused system.
			if (!this.ctx.isMoonGroupVisible(parentId)) continue;
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
			// Don't gate on line.visible — newly-built lines are visible=false
			// but will be flipped visible later this frame by updateBodyVisibility;
			// their vertices must be rebased against the new focus before first render.
			if (!line) continue;
			const localPositions = line.userData.orbitLocalPositions as
				| [number, number, number][]
				| undefined;
			if (!localPositions) continue;
			const oc = line.userData.orbitCenter as Vector3;
			rebaseOrbitLineLocals(line, localPositions, oc.x - fx, oc.y - fy, oc.z - fz);
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
		// Keep the chebyshev working set centred on `jd` — chunks for the
		// current time window load in the background on boundary crossings so
		// `positionScene` stays valid under time playback. Fire-and-forget: the
		// frame may miss data for one or two ticks right at a boundary, during
		// which chebyshev-tracked bodies are hidden (outOfRange) exactly like
		// SGP4 out-of-coverage bodies.
		this.ctx.chebStore?.ensure(jd);

		// Aggregate data-unavailability across bodies for a single summary toast —
		// per-body toasts would be spammy at chunk boundaries. Grouping by data
		// source lets us report the relevant cutoff date per group.
		const oorState: OutOfRangeState = {
			jd,
			satellites: emptyGroup(),
			majorBodies: emptyGroup(),
			focusedOutOfRange: false
		};
		const focusedId = this.focusedBody?.data.id;

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
			// Validity gate: hide bodies whose elements would diverge (SGP4) or
			// produce nonsense (parabolic) outside their stated window. Skipped
			// for chebyshev bodies — their validityStart/End is the startup
			// chunk's window (not the full segment range), so this gate would
			// wrongly hide them on any time jump past that chunk. The cheb
			// branch below uses `positionScene` as the authoritative gate.
			const bo = this.bodyObjects.get(d.id);
			const isChebTracked = this.ctx.chebStore?.has(d.id) ?? false;
			if (!isChebTracked && (jd < d.validityStart || jd > d.validityEnd)) {
				if (bo) bo.outOfRange = true;
				// SGP4 is the only source with a finite validity here (TLE epoch
				// ± 14 days); Keplerian/parabolic elements use ±Infinity bounds
				// and never land in this branch.
				if (d.satrec) {
					oorState.satellites.count++;
					if (d.validityStart < oorState.satellites.earliestStart) {
						oorState.satellites.earliestStart = d.validityStart;
					}
					if (d.validityEnd > oorState.satellites.latestEnd) {
						oorState.satellites.latestEnd = d.validityEnd;
					}
					if (d.id === focusedId) oorState.focusedOutOfRange = true;
				}
				return;
			}
			let x: number, y: number, z: number;
			// Chebyshev-tracked bodies (planets, moons) propagate strictly from
			// the polynomials — no Kepler fallback. When a chunk boundary is
			// being loaded or jd is outside the export's coverage, hide the body
			// (matches SGP4 behaviour) rather than drifting into positions that
			// break eclipse geometry.
			if (isChebTracked) {
				const chebOffset = this.ctx.chebStore!.positionScene(d.id, jd);
				if (!chebOffset) {
					if (bo) bo.outOfRange = true;
					// Only count as out-of-range for the toast if jd is outside the
					// zone's exported coverage. Inside coverage + null offset means a
					// chunk is still loading (transient) — toasting that would flicker.
					const coverage = this.ctx.chebStore!.zoneCoverage(d.id);
					if (coverage && (jd < coverage.start || jd > coverage.end)) {
						oorState.majorBodies.count++;
						if (coverage.start < oorState.majorBodies.earliestStart) {
							oorState.majorBodies.earliestStart = coverage.start;
						}
						if (coverage.end > oorState.majorBodies.latestEnd) {
							oorState.majorBodies.latestEnd = coverage.end;
						}
						if (d.id === focusedId) oorState.focusedOutOfRange = true;
					}
					return;
				}
				x = parentPos[0] + chebOffset[0];
				y = parentPos[1] + chebOffset[1];
				z = parentPos[2] + chebOffset[2];
			} else if (d.a === 0 && !isParabolic && !d.satrec) {
				// Body coincides with its parent (e.g. a Kepler-only barycenter
				// placeholder, if one ever appears).
				[x, y, z] = parentPos;
			} else {
				const offset = d.satrec
					? sgp4PositionScene(d.satrec, jd)
					: isParabolic
						? parabolicToPositionJD(d, jd)
						: orbitalElementsToPositionJD(d, jd);
				if (!offset) return;
				x = parentPos[0] + offset[0];
				y = parentPos[1] + offset[1];
				z = parentPos[2] + offset[2];
			}
			if (bo) bo.outOfRange = false;
			body.position[0] = x;
			body.position[1] = y;
			body.position[2] = z;
			if (body.orbitCenter) {
				body.orbitCenter[0] = parentPos[0];
				body.orbitCenter[1] = parentPos[1];
				body.orbitCenter[2] = parentPos[2];
			}
			if (body.trailAnchor) {
				body.trailAnchor[0] = parentPos[0];
				body.trailAnchor[1] = parentPos[1];
				body.trailAnchor[2] = parentPos[2];
			}
			positionMap.set(d.id, body.position);

			if (!bo) return;
			if (bo.orbitLine && body.orbitCenter) {
				const oc = bo.orbitLine.userData.orbitCenter as Vector3 | undefined;
				if (oc) oc.set(parentPos[0], parentPos[1], parentPos[2]);
			}
			if (body.orientation && bo.mesh) {
				applyOrientation(bo.mesh, body.orientation, jd, body.nutPrec);
			}
			// Rings inherit the body's pole orientation (their geometry is
			// pre-rotated so local +Y is the pole). Re-apply each frame so
			// nutation/precession/spin all stay in sync with the planet.
			if (body.orientation && bo.rings) {
				applyOrientation(bo.rings.mesh, body.orientation, jd, body.nutPrec);
			}
		};

		// First pass: bodies in ctx.bodiesById (barycenters → planets → moons,
		// in dependency order). Second pass: promoted minor bodies that only
		// live in bodyObjects, whose parents are now in positionMap.
		//
		// Skip moons outside the focused planetary system. Their meshes,
		// orbit lines, and point-cloud groups are all gated on
		// `isInFocusedSystem` (see context-manager.svelte.ts), so a stale
		// position can't be visible — and switching focus pulls them back
		// into the propagation set the same frame `focusedSystemId` flips.
		// Non-moon bodies stay always-on: planets/barycenters parent the
		// chained position chain, and the focused body itself is read by
		// the focus-tracking pass below.
		const sysId = this.ctx.focusedSystemId;
		for (const body of this.ctx.bodiesById.values()) {
			if (body.data.objectType === ObjectType.MOON) {
				const inSystem = sysId !== null && body.data.parentId === sysId;
				if (!inSystem && body.data.id !== focusedId) {
					// Seed positionMap with the last-computed position so any
					// child body (e.g. a sub-moon spacecraft) resolves to the
					// stale-but-known parent location instead of origin.
					positionMap.set(body.data.id, body.position);
					continue;
				}
			}
			computePosition(body);
		}
		for (const bo of this.bodyObjects.values()) {
			if (!this.ctx.bodiesById.has(bo.body.data.id)) computePosition(bo.body);
		}

		updateOutOfRangeToast(oorState);

		// Pass 2a: now that all positions are current, lock focus onto the
		// focused body's *new* position (unless an animation is driving it).
		if (this.focusedBody) {
			const p = this.focusedBody.position;
			const elapsed = performance.now() - this.focus.focusStartTime;
			const animating = elapsed < this.focus.focusDurationMs;
			this.focus.focusTargetWorld[0] = p[0];
			this.focus.focusTargetWorld[1] = p[1];
			this.focus.focusTargetWorld[2] = p[2];
			// Refresh body-relative camera target so the fly destination tracks
			// the moving body (otherwise we land at the body's start-of-fly
			// position offset).
			const camOff = this.focus.camTargetOffset;
			if (camOff && this.focus.camTargetWorld) {
				this.focus.camTargetWorld[0] = p[0] + camOff[0];
				this.focus.camTargetWorld[1] = p[1] + camOff[1];
				this.focus.camTargetWorld[2] = p[2] + camOff[2];
			}
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
		//
		// Skip invisible lines: GPU buffer uploads dominate this path
		// (~6 KB × needsUpdate=true per line), and most lines are off in any
		// view (~70+ chebyshev bodies, MAX_FULL_MOONS=20). Newly-built lines
		// default to visible=false and would render at construction-time basis
		// for one frame after `updateBodyVisibility` flips them on; mark them
		// `refreshDeferred` here and {@link refreshDeferredOrbitLines} catches
		// the transition right after visibility is updated.
		const basis = this.focus.focusTruePos;
		for (const bo of this.bodyObjects.values()) {
			const line = bo.orbitLine;
			if (!line) continue;
			if (!line.visible) {
				line.userData.refreshDeferred = true;
				continue;
			}
			refreshOrbitLineGeometry(bo.body, line, basis, jd);
			line.userData.refreshDeferred = false;
		}
	}

	/**
	 * Catch orbit lines that were skipped by {@link updatePositions} because
	 * they were invisible last frame but were just flipped visible by
	 * {@link updateBodyVisibility}. Refreshes once against the current basis
	 * + jd so the line doesn't render with a stale (or construction-time)
	 * vertex buffer for one frame.
	 */
	private refreshDeferredOrbitLines(): void {
		const basis = this.focus.focusTruePos;
		const jd = this.lastUpdatedJd;
		for (const bo of this.bodyObjects.values()) {
			const line = bo.orbitLine;
			if (!line || !line.visible || !line.userData.refreshDeferred) continue;
			refreshOrbitLineGeometry(bo.body, line, basis, jd);
			line.userData.refreshDeferred = false;
		}
	}

	// --- RAF loop ---

	private tick = (): void => {
		this.rafId = requestAnimationFrame(this.tick);

		this.updateCameraUp();

		// Snap controls target on first frame
		if (this.firstFrame) {
			this.firstFrame = false;
			this.controls.target.set(0, 0, 0);
			this.controls.update();
		}

		// Gate body updates on jd actually changing — fires for play, pause→now,
		// and manual setJD alike; skips work while paused.
		this.clock.tick(performance.now());
		if (this.clock.jd !== this.lastUpdatedJd) {
			this.lastUpdatedJd = this.clock.jd;
			this.ctx.refreshTick(jdToDate(this.clock.jd));
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

		// Catch lines that updatePositions skipped (visible=false last frame)
		// but updateBodyVisibility just flipped on, so they don't render at a
		// stale basis for one frame.
		this.refreshDeferredOrbitLines();

		this.updateRingShaders();
		this.updateEclipseUniforms();

		// Hide the user-location dot when it rotates around to Earth's far side.
		this.updateUserLocationOcclusion();

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
			// Rings no longer receive into the shadow map (their own shader
			// ray-marches the planet's oblate spheroid analytically), so the
			// frustum can stay sized to the camera view without a ring floor.
			const lateral = Math.max(distance * 2, 0.001);
			const depthExtent = this.ctx.getSystemExtent(sysId) * AU_SCALE * 1.2;
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
				if (!body) continue; // not loaded yet — retry on a later frame
				this.pendingDefaultPromotions.delete(id);
				// Barycenters and Lagrange points share the labels file with
				// promoted bodies (their names are needed when the user navigates
				// to one via URL), but they aren't shown by default — except
				// those listed in MINOR_PROMOTED_IDS, which render as collapsed
				// halos so the user sees the SSB / Pluto-Charon offset.
				if (
					(body.data.objectType === ObjectType.BARYCENTER ||
						body.data.objectType === ObjectType.LAGRANGE_POINT) &&
					!MINOR_PROMOTED_IDS.has(id)
				)
					continue;
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
			this._tmpV3,
			this.clock.jd,
			e.pointerType
		);
		if (pointHit && pointHit.distance < bestDist) {
			bestBody = pointHit.body;
		}

		if (bestBody) {
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
		loadSystemData(
			baryId,
			this.bodyObjects,
			this.scene,
			this.textureLoader,
			this.clock.jd,
			this.ctx
		).then(() => {
			this.reapplyInitialViewIfPending();
			this.ctx.orientationVersion++;
		});
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
		loadBodyTexture(bo, this.textureLoader, body.data.hasLocalized, this.ctx);
	}

	/**
	 * Refresh per-frame ring uniforms — both the ring material's lit/unlit
	 * sun direction, and the planet material's analytical ring-shadow inputs
	 * (sun direction, pole direction, planet center). The shadow ray-march
	 * runs entirely in world space, so all three vectors need updating as the
	 * body orbits, spins, and the focus basis shifts.
	 */
	private updateRingShaders(): void {
		const sunPos = this.bodyObjects.get('naif-10')?.body.position;
		if (!sunPos) return;
		const [fx, fy, fz] = this.focus.focusTruePos;
		for (const bo of this.bodyObjects.values()) {
			if (!bo.rings) continue;
			const [bx, by, bz] = bo.body.position;

			// uSunDir on the ring material — direction body → sun in true
			// world coords. Same in scene/focus-relative coords because the
			// focus offset cancels.
			const ringSunDir = bo.rings.material.uniforms.uSunDir.value as Vector3;
			ringSunDir.set(sunPos[0] - bx, sunPos[1] - by, sunPos[2] - bz).normalize();

			// Planet center and pole are shared across both ray-marches:
			// the ring's planet-shadow path (`planetShadowOnRing`, always
			// present) and the planet's ring-shadow path (`planetShadow`,
			// present once `attachRingShadowToPlanet` has run).
			const psOnRing = bo.rings.planetShadowOnRing;
			psOnRing.uPlanetCenter.value.set(bx - fx, by - fy, bz - fz);
			if (bo.mesh) {
				psOnRing.uPlanetPoleDir.value.set(0, 1, 0).applyQuaternion(bo.mesh.quaternion);
			}

			const ps = bo.rings.planetShadow;
			if (!ps) continue;
			ps.uRingShadowSunDir.value.copy(ringSunDir);
			ps.uRingShadowPoleDir.value.copy(psOnRing.uPlanetPoleDir.value);
			ps.uRingShadowCenter.value.copy(psOnRing.uPlanetCenter.value);
		}
	}

	/**
	 * Refresh per-frame eclipse uniforms — sun position/radius, the
	 * occluder list, and each receiver's self-position. Occluder
	 * eligibility is gated on a measured (real) `radiusKm`: the data layer
	 * fills in a fallback radius for bodies whose physical size is
	 * unknown, and using those for shadow casting would draw wrong-sized
	 * shadows. Stars are excluded since the Sun *is* the light source.
	 *
	 * If the system has more than {@link MAX_OCCLUDERS} eligible bodies we
	 * keep the largest by scene radius — those dominate the shadow budget
	 * and the smaller ones contribute negligible obscuration anyway.
	 */
	private updateEclipseUniforms(): void {
		const eclipse = getEclipseSceneUniforms();
		const sunBo = this.bodyObjects.get('naif-10');
		if (!sunBo) {
			eclipse.uSunRadiusScene.value = 0;
			eclipse.uOccluderCount.value = 0;
			return;
		}
		const [fx, fy, fz] = this.focus.focusTruePos;
		const sunPos = sunBo.body.position;
		eclipse.uSunPos.value.set(sunPos[0] - fx, sunPos[1] - fy, sunPos[2] - fz);
		eclipse.uSunRadiusScene.value = sunBo.radiusScene;

		// Collect eligible occluders (non-star bodies with a measured
		// radius) and sort by scene radius descending so that if there are
		// more than MAX_OCCLUDERS we keep the dominant ones.
		const candidates: BodyObjects[] = [];
		for (const bo of this.bodyObjects.values()) {
			if (bo.body.data.objectType === ObjectType.STAR) continue;
			const km = bo.body.data.radiusKm;
			if (!Number.isFinite(km) || km <= 0) continue;
			if (bo.radiusScene <= 0) continue;
			candidates.push(bo);
		}
		if (candidates.length > MAX_OCCLUDERS) {
			candidates.sort((a, b) => b.radiusScene - a.radiusScene);
			candidates.length = MAX_OCCLUDERS;
		}
		const slots = eclipse.uOccluders.value;
		for (let i = 0; i < candidates.length; i++) {
			const bo = candidates[i];
			const [bx, by, bz] = bo.body.position;
			slots[i].set(bx - fx, by - fy, bz - fz, bo.radiusScene);
		}
		eclipse.uOccluderCount.value = candidates.length;

		// Receivers: every non-star body that got an eclipse handler at
		// construction time. Mirror its focus-relative center so the
		// shader can skip its own slot in the occluder loop.
		for (const bo of this.bodyObjects.values()) {
			if (!bo.eclipseShadow) continue;
			const [bx, by, bz] = bo.body.position;
			bo.eclipseShadow.uEclipseSelfPos.value.set(bx - fx, by - fy, bz - fz);
		}
	}

	/**
	 * Per-frame texture LOD: upgrade each visible body's texture tier based on
	 * its screen-space radius. One-way upgrade — the prior texture is disposed
	 * when a higher tier loads, so at most one tier per body lives on the GPU.
	 */
	private updateTextureLOD(): void {
		const fovRad = (this.camera.fov * Math.PI) / 180;
		const screenH = this.renderer.domElement.clientHeight;
		const projScale = screenH / (2 * Math.tan(fovRad / 2));
		const activeSystem = this.ctx.activeSystemId;
		const focusedId = this.focusedBody?.data.id;

		for (const bo of this.bodyObjects.values()) {
			if (!bo.mesh || !bo.radiusScene || !bo.group.visible) continue;
			if (!bo.availableTiers?.length || bo.textureLoading) continue;
			if (bo.cachedDist <= 0) continue;
			const id = bo.body.data.id;
			if (activeSystem) {
				if (id !== activeSystem && !this.ctx.isInActiveSystem(bo.body.data.parentId)) continue;
			} else if (id !== focusedId) {
				continue;
			}

			const screenR = (bo.radiusScene / bo.cachedDist) * projScale;
			const altitudeRadii = bo.cachedDist / bo.radiusScene;
			let desired: 'low' | 'medium' | 'high';
			if (screenR < 256 && altitudeRadii > 10) desired = 'low';
			else if (screenR < 1024 && altitudeRadii > 2) desired = 'medium';
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
		if (this.focusedBody?.data.id === body.data.id) {
			// Same body re-clicked: skip the camera fly, but re-emit so the
			// drawer can reopen after being dismissed.
			this.callbacks.onFocusChange(body);
			return;
		}
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
		// Point-cloud bodies aren't touched by updatePositions — their CPU
		// position is frozen at load. Refresh before building so the mesh,
		// halo, and orbit line spawn at the current jd instead of jumping on
		// the next tick.
		refreshMinorBodyPosition(body, this.clock.jd, this.ctx);
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
		buildOrbitLines(this.bodyObjects, this.scene, this.pointCloudBasisPos, this.clock.jd);
		this.repositionAll();

		// Click-promoted minor bodies enter with no name (the global labels file
		// only carries the curated promoted set). Fire-and-forget the detail
		// bundle fetch so the label fills in once Wikidata arrives.
		const bo = this.bodyObjects.get(body.data.id);
		if (bo && !body.data.name) loadBodyLabel(bo);

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

		// Track click/URL-promoted bodies (not the auto-promoted curated set) so
		// the user can revert them in one shot via {@link clearUserPromoted}.
		if (!this.defaultPromotedIds.has(body.data.id)) {
			this.userPromotedIds.add(body.data.id);
			this.emitUserPromotedCount();
		}
	}

	/** Emit the count of user-promoted bodies that can currently be cleared.
	 *  Excludes the focused body — clearing it would leave the camera pointing
	 *  at a torn-down mesh, so by design it's spared. */
	private emitUserPromotedCount(): void {
		if (!this.callbacks.onUserPromotedChange) return;
		const focusedId = this.focusedBody?.data.id;
		let count = this.userPromotedIds.size;
		if (focusedId && this.userPromotedIds.has(focusedId)) count--;
		this.callbacks.onUserPromotedChange(count);
	}

	/** Tear down every user-promoted body except the currently focused one,
	 *  reverting them to point-cloud dots. */
	clearUserPromoted(): void {
		const focusedId = this.focusedBody?.data.id;
		const dirtySpacecraftParents = new Set<string>();
		const dirtyAsteroidZones = new Set<string>();

		for (const id of [...this.userPromotedIds]) {
			if (id === focusedId) continue;
			const bo = this.bodyObjects.get(id);
			if (!bo) {
				this.userPromotedIds.delete(id);
				continue;
			}

			// Group is added to scene; label is its Three.js child but its DOM
			// element lives in the CSS2D label container — CSS2DRenderer does not
			// remove the DOM node when its object leaves the scene graph, so it'd
			// stay clickable in place. Detach the element manually.
			if (bo.label) {
				bo.label.element.remove();
				bo.label.removeFromParent();
			}
			this.scene.remove(bo.group);
			// Mesh + (for stars) corona/lensflare/etc. are added to scene directly.
			for (const obj of bo.extraObjects) this.scene.remove(obj);
			if (bo.orbitLine) this.scene.remove(bo.orbitLine);

			if (bo.mesh) {
				bo.mesh.geometry.dispose();
				const mat = bo.mesh.material;
				if (Array.isArray(mat)) for (const m of mat) m.dispose();
				else mat.dispose();
				const idx = this.clickables.indexOf(bo.mesh);
				if (idx >= 0) this.clickables.splice(idx, 1);
				this.meshToBody.delete(bo.mesh);
			}
			if (bo.orbitLine) {
				bo.orbitLine.geometry.dispose();
				const mat = bo.orbitLine.material;
				if (Array.isArray(mat)) for (const m of mat) m.dispose();
				else mat.dispose();
			}

			// Mark the body's point-cloud group dirty so the dot reappears.
			const objectType = bo.body.data.objectType;
			if (objectType === ObjectType.SPACECRAFT) {
				dirtySpacecraftParents.add(bo.body.data.parentId);
			} else if (isAsteroid(objectType) || objectType === ObjectType.COMET) {
				for (const [zone, bodies] of this.ctx.asteroidBodiesByZone) {
					if (bodies.some((b) => b.data.id === id)) {
						dirtyAsteroidZones.add(zone);
						break;
					}
				}
			}

			this.bodyObjects.delete(id);
			this.userPromotedIds.delete(id);
		}

		for (const p of dirtySpacecraftParents) this.ctx.dirtySpacecraftGroups.add(p);
		for (const z of dirtyAsteroidZones) this.ctx.dirtyAsteroidZones.add(z);
		if (dirtySpacecraftParents.size > 0 || dirtyAsteroidZones.size > 0) {
			this.rebuildMinorPointClouds();
		}

		this.emitUserPromotedCount();
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
		// AppState's camera fields are fresh when `onFocusChange` fires inside
		// `setFocusTarget` and `setFocus` captures the intended destination.
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
		// Focus moved on/off a user-promoted body — re-emit so the clear button's
		// visibility (which excludes the focused body) stays in sync.
		this.emitUserPromotedCount();
	}

	getFocusedBody(): PositionedBody | undefined {
		return this.focusedBody;
	}

	/**
	 * Set which body's IAU north pole drives `camera.up`. `null` reverts to
	 * ecliptic Y (scene frame). Triggers a slerp from the currently-applied up
	 * vector to the new target over `UP_ANIM_DURATION_MS`. The target is
	 * recomputed each frame inside {@link updateCameraUp} so it tracks the
	 * (slow) drift of the body's pole over time.
	 */
	setNorthReference(id: string | null): void {
		if (id === this.northRefId) return;
		this.northRefId = id;
		this.upStartVec.copy(this.upCurrentVec);
		this.upAnimStartTime = performance.now();
	}

	private updateCameraUp(): void {
		const refBody = this.northRefId ? this.ctx.getBody(this.northRefId) : undefined;
		if (refBody) bodyNorthVector(refBody, this.clock.jd, this.upTargetVec);
		else this.upTargetVec.copy(SceneRenderer._upRef);

		const elapsed = performance.now() - this.upAnimStartTime;
		if (elapsed >= SceneRenderer.UP_ANIM_DURATION_MS) {
			this.upCurrentVec.copy(this.upTargetVec);
		} else {
			const t = Math.max(0, elapsed / SceneRenderer.UP_ANIM_DURATION_MS);
			const s = t * t * (3 - 2 * t);
			// Slerp via the rotation quaternions that map ecliptic Y → start/target.
			this._upQuatA.setFromUnitVectors(SceneRenderer._upRef, this.upStartVec);
			this._upQuatB.setFromUnitVectors(SceneRenderer._upRef, this.upTargetVec);
			this._upQuatA.slerp(this._upQuatB, s);
			this.upCurrentVec.copy(SceneRenderer._upRef).applyQuaternion(this._upQuatA);
		}
		this.camera.up.copy(this.upCurrentVec);

		// OrbitControls caches its up→Y quat at construction and never refreshes it.
		const ctrls = this.controls as unknown as { _quat: Quaternion; _quatInverse: Quaternion };
		ctrls._quat.setFromUnitVectors(this.upCurrentVec, SceneRenderer._upRef);
		ctrls._quatInverse.copy(ctrls._quat).invert();
	}

	/**
	 * Drop a "you are here" pin at lat/lon on Earth. Re-pins if already set.
	 * Parented to Earth's mesh, so it inherits Earth's rotation and the dot
	 * stays glued to the same ground point as the planet spins.
	 */
	setUserLocation(latitude: number, longitude: number): void {
		const earth = this.bodyObjects.get('naif-399');
		if (!earth?.mesh) return;
		if (this.userLocationMarker) removeUserLocationMarker(this.userLocationMarker);
		this.userLocationMarker = createUserLocationMarker(
			earth.mesh,
			earth.radiusScene,
			latitude,
			longitude
		);
	}

	clearUserLocation(): void {
		if (this.userLocationMarker) {
			removeUserLocationMarker(this.userLocationMarker);
			this.userLocationMarker = null;
		}
	}

	/**
	 * Hide the user-location dot when it's on Earth's far hemisphere from the
	 * camera. The marker sits exactly on the surface (|earthToMarker| = R), so
	 * the tangent-plane visibility check reduces to `earthToMarker · earthToCamera > R²`.
	 * If the camera is inside Earth (e.g., debug zoom-through), keep it visible.
	 */
	private updateUserLocationOcclusion(): void {
		const marker = this.userLocationMarker;
		if (!marker) return;
		const earth = this.bodyObjects.get('naif-399');
		if (!earth?.mesh) return;
		// Earth-center → marker, in scene-frame coords (focus-relative).
		this._tmpUserLoc.copy(marker.position).applyQuaternion(earth.mesh.quaternion);
		const ex = this._tmpUserLoc.x;
		const ey = this._tmpUserLoc.y;
		const ez = this._tmpUserLoc.z;
		// Earth-center → camera. mesh.position holds Earth's focus-relative pos.
		const ep = earth.mesh.position;
		const cx = this.camera.position.x - ep.x;
		const cy = this.camera.position.y - ep.y;
		const cz = this.camera.position.z - ep.z;
		const r = earth.radiusScene;
		const r2 = r * r;
		const camDist2 = cx * cx + cy * cy + cz * cz;
		marker.visible = camDist2 <= r2 || ex * cx + ey * cy + ez * cz > r2;
	}

	resize(width: number, height: number): void {
		this.renderer.setSize(width, height, false);
		this.labelRenderer.setSize(width, height);
		this.camera.aspect = width / height;
		this.camera.updateProjectionMatrix();
		this.ctx.updateViewport(height);
		setOrbitLineResolution(width, height);
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

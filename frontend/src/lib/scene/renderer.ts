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
import { orbitalElementsToPositionJD, parabolicToPositionJD } from '$lib/math/orbit/position';
import { sgp4PositionScene } from '$lib/math/orbit/sgp4';
import { refreshMinorBodyPosition } from '$lib/scene/minor-body-position';
import {
	buildMajorBodies,
	buildOrbitLines,
	buildPointClouds,
	loadBodyTexture,
	loadBodyTextureTier,
	loadSystemData,
	makeCircleTexture
} from './objects/construction';
import {
	makePointCloudFromBuffer,
	refreshChebyshevOrbitLineGeometry,
	refreshOrbitLineGeometry
} from './objects/builders';
import type { TrailBuffer } from '$lib/fetch/chebyshev/trail-buffer';
import { resolveBodyColor } from '$lib/utils';
import { OrbitWorkerPool, type GroupInput } from '$lib/math/orbit/pool';
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
import { emptyGroup, updateOutOfRangeToast, type OutOfRangeState } from './out-of-range-toast';

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
		this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
		this.renderer.setSize(canvas.clientWidth, canvas.clientHeight, false);
		this.renderer.shadowMap.enabled = true;
		this.renderer.shadowMap.type = PCFSoftShadowMap;

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
	 * Rebuild the pool's owned group set to match the current ctx contents, and
	 * ensure every zone/group has a Points object whose position attribute is
	 * backed by the pool's front buffer. Called whenever the minor-body data
	 * changes (new chunks loaded, snapshot swap) or the promoted set changes.
	 *
	 * Driven by `dirtyAsteroidZones`/`dirtySpacecraftGroups` — only groups in
	 * those sets are re-packed and shipped to workers. A snapshot swap that
	 * touches one zone (~10k bodies) used to also re-pack the other ~24 zones
	 * (~250k bodies) and re-init the worker pool, which on top of an already
	 * busy worker pool was reading as constant point-cloud flicker.
	 *
	 * Worker ticks asynchronously refresh the positions; this method just
	 * (re)wires the handoff between the pool and the Three.js geometries.
	 */
	rebuildMinorPointClouds(): void {
		const dirtyAsteroid = this.ctx.dirtyAsteroidZones;
		const dirtySpacecraft = this.ctx.dirtySpacecraftGroups;
		if (dirtyAsteroid.size === 0 && dirtySpacecraft.size === 0) return;

		const skip = new Set(this.bodyObjects.keys());
		const input: GroupInput[] = [];
		for (const zone of dirtyAsteroid) {
			input.push({ id: `asteroid:${zone}`, bodies: this.ctx.asteroidBodiesByZone.get(zone) ?? [] });
		}
		for (const gid of dirtySpacecraft) {
			input.push({ id: `spacecraft:${gid}`, bodies: this.ctx.spacecraftByParent.get(gid) ?? [] });
		}
		this.orbitPool.rewireSubset(input, skip);

		const seedBasis: Vec3 = [
			this.pointCloudBasisPos[0],
			this.pointCloudBasisPos[1],
			this.pointCloudBasisPos[2]
		];
		// For existing groups we keep whatever the pool has (worker-computed
		// positions) — overwriting would clobber fresh data with stale
		// load-time positions and cause the cloud to flicker between current
		// and load-time locations. Only seed brand-new groups. Empty groups
		// (parent's body list became empty) are torn down.
		for (const g of input) {
			const isAsteroid = g.id.startsWith('asteroid:');
			const key = g.id.slice(g.id.indexOf(':') + 1);
			const points = isAsteroid ? this.asteroidPoints : this.spacecraftPoints;
			if (g.bodies.length === 0) {
				const pts = points.get(key);
				if (pts) {
					this.scene.remove(pts);
					pts.geometry.dispose();
					points.delete(key);
				}
				continue;
			}
			const front = this.orbitPool.front(g.id);
			if (!front) continue;
			const existing = points.get(key);
			if (existing) {
				existing.geometry.setAttribute('position', new BufferAttribute(front, 3));
			} else {
				this.seedFrontFromBodies(front, g.bodies);
				const pts = makePointCloudFromBuffer(
					front,
					g.bodies.length,
					this.circleTexture,
					resolveBodyColor(g.bodies[0].data)
				);
				pts.userData.frontBasis = seedBasis;
				points.set(key, pts);
				this.pendingSceneAdds.push(pts);
			}
		}
		dirtyAsteroid.clear();
		dirtySpacecraft.clear();
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
		const basis: Vec3 = [fx, fy, fz];
		for (const bo of this.bodyObjects.values()) {
			const line = bo.orbitLine;
			// Don't gate on line.visible — newly-built lines are visible=false
			// but will be flipped visible later this frame by updateBodyVisibility;
			// their vertices must be rebased against the new focus before first render.
			if (!line) continue;
			// Chebyshev-backed lines have their vertices re-read from the live
			// trail buffer each time instead of from a cached Float64 list.
			const trailBuffer = line.userData.trailBuffer as TrailBuffer | undefined;
			if (trailBuffer) {
				refreshChebyshevOrbitLineGeometry(bo.body, line, trailBuffer, basis);
				continue;
			}
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
		// Keep the chebyshev working set centred on `jd` — chunks for the
		// current time window load in the background on boundary crossings so
		// `positionScene` stays valid under time playback. Fire-and-forget: the
		// frame may miss data for one or two ticks right at a boundary, during
		// which chebyshev-tracked bodies are hidden (outOfRange) exactly like
		// SGP4 out-of-coverage bodies.
		this.ctx.chebStore?.ensure(jd);
		this.ctx.advanceTrailBuffers(jd);

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
			// Respect the chunk-level validity window — propagating outside it
			// either diverges (SGP4) or gives nonsense (parabolic). Leaving the
			// body out of `positionMap` tells children to fall back to origin;
			// `updateBodyVisibility` hides the mesh + orbit line via outOfRange.
			const bo = this.bodyObjects.get(d.id);
			if (jd < d.validityStart || jd > d.validityEnd) {
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
			const isChebTracked = this.ctx.chebStore?.has(d.id) ?? false;
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
			positionMap.set(d.id, body.position);

			if (!bo) return;
			if (bo.orbitLine && body.orbitCenter) {
				const oc = bo.orbitLine.userData.orbitCenter as Vector3 | undefined;
				if (oc) oc.set(parentPos[0], parentPos[1], parentPos[2]);
			}
			if (bo.orientation && bo.mesh) {
				applyOrientation(bo.mesh, bo.orientation, jd, bo.nutPrec);
			}
		};

		// First pass: bodies in ctx.bodiesById (barycenters → planets → moons,
		// in dependency order). Second pass: promoted minor bodies that only
		// live in bodyObjects, whose parents are now in positionMap.
		for (const body of this.ctx.bodiesById.values()) computePosition(body);
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
		// Do NOT gate on `line.visible`: newly-built lines default to
		// visible=false, and updateBodyVisibility (which flips them visible) runs
		// *after* this step. A gate here would leave the line's vertex buffer at
		// construction-time values (relative to the OLD focus basis), producing
		// a ~1-AU-offset glitch for one frame after focus change.
		const basis = this.focus.focusTruePos;
		for (const bo of this.bodyObjects.values()) {
			const line = bo.orbitLine;
			if (line) refreshOrbitLineGeometry(bo.body, line, basis, jd);
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
		if (this.clock.jd !== this.lastUpdatedJd) {
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
			// Depth extent: full system so off-axis casters (e.g. Moon at 60 Earth
			// radii during an eclipse) stay inside the shadow frustum regardless
			// of how close the camera is to the receiver.
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
		loadSystemData(baryId, this.bodyObjects, this.textureLoader, this.clock.jd, this.ctx).then(() =>
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
		loadBodyTexture(bo, this.textureLoader, body.data.objectFileFlag, this.ctx);
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

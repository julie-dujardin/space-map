import {
	BufferAttribute,
	Color,
	Float32BufferAttribute,
	Points,
	type BufferGeometry,
	type CanvasTexture,
	type PointsMaterial,
	type Scene
} from 'three';
import { ObjectType, type PositionedBody } from '$lib/types/objects';
import { AU_SCALE } from '$lib/math/units';
import type { Vec3 } from '$lib/scene/animation/math';
import type { FocusState } from '$lib/scene/animation/focus';
import type { BodyObjects } from '$lib/scene/types';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
import { OrbitWorkerPool } from '$lib/math/orbit/pool';
import { partitionForWorkers, parentIdFromSubkey } from '$lib/math/orbit/partition';
import { buildPointClouds } from '$lib/scene/objects/body/bulk';
import { asteroidPointSize, makePointCloudFromBuffer } from '$lib/scene/objects/pointcloud';
import { resolveBodyColor } from '$lib/utils';
import { EARTH_ID, SUN_ID } from '$lib/constants';

const REBASE_THRESHOLD_AU = 0.01;

function clamp01(x: number): number {
	return x < 0 ? 0 : x > 1 ? 1 : x;
}

/** Earth-sat cloud emphasis bands. Stage 1 brightens (alpha + color); stage 2
 *  enlarges. Below stage 2 the cloud is irrelevant because members are
 *  half/full-promoted (handled in PromotionRegistry). */
const EMPHASIS_ALPHA_HI = 10000;
const EMPHASIS_ALPHA_LO = 500;
const EMPHASIS_SIZE_HI = EMPHASIS_ALPHA_LO;
const EMPHASIS_SIZE_LO = 50;
/** Baseline earth-sat cloud knobs (mirror `makePointCloudFromBuffer` defaults).
 *  Color is 0.5 because the spacecraft cloud uses vertex colors and the
 *  material colour is the 0.5 dim multiplier. */
const EMPHASIS_BASE_SIZE = 4;
const EMPHASIS_BASE_DIM = 0.5;
const EMPHASIS_MAX_SIZE = 10;
const EMPHASIS_MAX_DIM = 1.0;
/** Texture alpha is baked at ~0.3; boost opacity past 1 to wash it out toward
 *  fully opaque when only a few members remain. NormalBlending clamps src.a
 *  during compositing, so >1 here just maps to "fully opaque dot". */
const EMPHASIS_BASE_OPACITY = 1.0;
const EMPHASIS_MAX_OPACITY = 3.5;

/** Asteroid-class emphasis: size + opacity boost applied to the focused
 *  `small_bodies/<class>` zone (e.g. when /g/class-NEA is active). Asteroid
 *  zones span four orders of magnitude in cardinality (CEN ~hundreds vs MBA
 *  >10k), so the earth-sat count-based ramp isn't a fit — a single fixed boost
 *  delivers consistent visual emphasis. Color stays at the material's baseline
 *  `overlayColor(c) = c · 0.5`; only size + opacity move. */
const SMALL_BODY_EMPHASIS_SIZE_MULT = 2.5;
const SMALL_BODY_EMPHASIS_OPACITY = 2.5;

/**
 * Owns every minor-body point cloud (asteroid zones, spacecraft groups, moon
 * dots) plus the worker pool that powers asteroid/spacecraft Kepler solves.
 * Tracks a focus-relative basis and rebases when the focus drifts > 0.01 AU
 * to keep float32 vertex precision around 4 km.
 *
 * Moons render their dots on the main thread (cheap — positions already
 * computed in updatePositions); asteroids and spacecraft dispatch to the
 * pool, then {@link reposition} compensates for parent motion between the
 * worker's stale solve and the live frame.
 */
export class PointCloudSystem {
	readonly orbitPool = new OrbitWorkerPool();
	private asteroidPoints = new Map<string, Points>();
	private spacecraftPoints = new Map<string, Points>();
	private moonPoints = new Map<string, Points>();
	private pendingSceneAdds: Points[] = [];
	private basisPos: Vec3 = [0, 0, 0];
	/** Snapshot of each group's parent position at its last worker dispatch.
	 *  {@link parentShift} subtracts this from the parent's current position
	 *  so the cloud follows its moving parent between worker results. */
	private parentAtUpdate = new Map<string, Vec3>();
	private readonly _parentsScratch = new Map<string, Vec3>();
	/** Memoized moon → parent grouping; invalidated when majorBodies count changes. */
	private moonsByParentCache: { len: number; map: Map<string, PositionedBody[]> } | null = null;
	/** Last earth-sat emphasis values applied. Used to re-apply to newly-built
	 *  earth sub-clouds (rebuildMinor recreates them after a group filter swap). */
	private earthSatEmphasis = {
		size: EMPHASIS_BASE_SIZE,
		dim: EMPHASIS_BASE_DIM,
		opacity: EMPHASIS_BASE_OPACITY
	};
	/** Full zone key of the emphasized small-body class (e.g. `small_bodies/MBA`)
	 *  while a /g/class-* page is focused; null otherwise. New sub-clouds spawned
	 *  in rebuildMinor pick this up automatically. */
	private emphasizedSmallBodyZone: string | null = null;

	constructor(
		private readonly ctx: ContextManager,
		private readonly scene: Scene,
		private readonly bodyObjects: Map<string, BodyObjects>,
		private readonly circleTexture: CanvasTexture,
		private readonly focus: FocusState,
		private readonly mapLayer: number,
		/** Called whenever the basis is rebuilt so the caller can rebase trail vertices. */
		private readonly onBasisRebuilt: () => void
	) {
		this.orbitPool.setResultHandler(this.onPoolResult);
	}

	basis(): Vec3 {
		return this.basisPos;
	}

	/** Ramp earth-sat cloud size + alpha when only a few members remain. `count`
	 *  is the active group's member count; `null` resets to baseline. Stage 1
	 *  (2000 → 500) raises alpha + brightness; stage 2 (500 → 50) raises size. */
	setEarthSatEmphasis(count: number | null): void {
		this.earthSatEmphasis = this.computeEarthSatEmphasis(count);
		for (const [key, pts] of this.spacecraftPoints) {
			if (parentIdFromSubkey(key) !== EARTH_ID) continue;
			this.applyEarthSatEmphasis(pts);
		}
	}

	private computeEarthSatEmphasis(count: number | null): {
		size: number;
		dim: number;
		opacity: number;
	} {
		if (count === null) {
			return {
				size: EMPHASIS_BASE_SIZE,
				dim: EMPHASIS_BASE_DIM,
				opacity: EMPHASIS_BASE_OPACITY
			};
		}
		const tBright = clamp01((EMPHASIS_ALPHA_HI - count) / (EMPHASIS_ALPHA_HI - EMPHASIS_ALPHA_LO));
		const tSize = clamp01((EMPHASIS_SIZE_HI - count) / (EMPHASIS_SIZE_HI - EMPHASIS_SIZE_LO));
		return {
			size: EMPHASIS_BASE_SIZE + (EMPHASIS_MAX_SIZE - EMPHASIS_BASE_SIZE) * tSize,
			dim: EMPHASIS_BASE_DIM + (EMPHASIS_MAX_DIM - EMPHASIS_BASE_DIM) * tBright,
			opacity: EMPHASIS_BASE_OPACITY + (EMPHASIS_MAX_OPACITY - EMPHASIS_BASE_OPACITY) * tBright
		};
	}

	private applyEarthSatEmphasis(pts: Points): void {
		const mat = pts.material as PointsMaterial;
		const { size, dim, opacity } = this.earthSatEmphasis;
		mat.size = size;
		mat.color.setRGB(dim, dim, dim);
		mat.opacity = opacity;
	}

	/** Mark a `small_bodies/<class>` zone as focused — its sub-clouds get a
	 *  fixed size + opacity boost so the active /g/class-* page stands out from
	 *  the otherwise-hidden neighbour zones. Passing `null` clears any prior
	 *  emphasis. Safe to call before the matching sub-clouds exist; rebuildMinor
	 *  re-applies on creation. */
	setEmphasizedSmallBodyZone(zone: string | null): void {
		const prev = this.emphasizedSmallBodyZone;
		if (prev === zone) return;
		this.emphasizedSmallBodyZone = zone;
		if (prev !== null) {
			for (const [key, pts] of this.asteroidPoints) {
				if (parentIdFromSubkey(key) === prev) this.resetSmallBodyEmphasis(pts);
			}
		}
		if (zone !== null) {
			for (const [key, pts] of this.asteroidPoints) {
				if (parentIdFromSubkey(key) === zone) this.applySmallBodyEmphasis(pts);
			}
		}
	}

	private applySmallBodyEmphasis(pts: Points): void {
		if (pts.userData.smallBodyEmphasized) return;
		const mat = pts.material as PointsMaterial;
		pts.userData.smallBodyBaseSize = mat.size;
		mat.size = mat.size * SMALL_BODY_EMPHASIS_SIZE_MULT;
		mat.opacity = SMALL_BODY_EMPHASIS_OPACITY;
		pts.userData.smallBodyEmphasized = true;
	}

	private resetSmallBodyEmphasis(pts: Points): void {
		if (!pts.userData.smallBodyEmphasized) return;
		const mat = pts.material as PointsMaterial;
		mat.size = (pts.userData.smallBodyBaseSize as number | undefined) ?? mat.size;
		mat.opacity = 1.0;
		pts.userData.smallBodyEmphasized = false;
	}

	seedBasis(p: Vec3): void {
		this.basisPos = [...p];
	}

	/** Initial point-cloud build for asteroid zones, spacecraft groups, and moons. */
	buildInitial(promotedIds: Set<string>): void {
		const pts = buildPointClouds(
			this.ctx,
			this.scene,
			this.circleTexture,
			this.basisPos,
			promotedIds,
			this.orbitPool.workerCount
		);
		this.asteroidPoints = pts.asteroidPoints;
		this.spacecraftPoints = pts.spacecraftPoints;
		this.moonPoints = pts.moonPoints;
		// PromotionRegistry stores emphasis before this build runs, so re-apply
		// to the freshly-created earth sub-clouds.
		for (const [key, p] of this.spacecraftPoints) {
			if (parentIdFromSubkey(key) === EARTH_ID) this.applyEarthSatEmphasis(p);
		}
		// Same for small-body class focus: a deep-linked /g/class-* page may have
		// set the emphasis before the initial build ran.
		if (this.emphasizedSmallBodyZone !== null) {
			for (const [key, p] of this.asteroidPoints) {
				if (parentIdFromSubkey(key) === this.emphasizedSmallBodyZone) {
					this.applySmallBodyEmphasis(p);
				}
			}
		}
		this.assignMapLayer();
	}

	/** Re-tag every current cloud with the immersive-mode map layer. */
	assignMapLayer(): void {
		for (const pts of this.asteroidPoints.values()) pts.layers.set(this.mapLayer);
		for (const pts of this.spacecraftPoints.values()) pts.layers.set(this.mapLayer);
		for (const pts of this.moonPoints.values()) pts.layers.set(this.mapLayer);
	}

	/**
	 * Sync pool wiring and Three.js geometries with the ctx's dirty markers.
	 * New chunks landing, the promoted set changing, and basis rebuilds all
	 * add to dirty markers — this drains them.
	 *
	 * Each Points' geometry owns a persistent `Float32Array`: only resized
	 * when the body count changes, otherwise left in place so a worker result
	 * can `.set()` into it under the same `BufferAttribute`. That stable
	 * attribute identity lets Three.js reuse the WebGL VBO instead of
	 * `createBuffer`-ing a fresh one every tick.
	 */
	rebuildMinor(): void {
		if (
			this.ctx.bodies.dirtyAsteroidZones.size === 0 &&
			this.ctx.bodies.dirtySpacecraftGroups.size === 0
		) {
			return;
		}
		const skip = new Set(this.bodyObjects.keys());
		const seedBasis: Vec3 = [this.basisPos[0], this.basisPos[1], this.basisPos[2]];
		const k = this.orbitPool.workerCount;

		for (const zone of this.ctx.bodies.dirtyAsteroidZones) {
			const bucket = this.ctx.bodies.asteroidBodiesByZone.get(zone);
			const allBodies = bucket ? Array.from(bucket.values()) : [];
			const { buckets, baseWorker } = partitionForWorkers(zone, allBodies, k);
			// Iterate full K (not buckets.length) so subgroups #1..#K-1 get
			// unwired when a zone shrinks below the split threshold.
			for (let i = 0; i < k; i++) {
				const key = `${zone}#${i}`;
				const groupId = `asteroid:${key}`;
				const bodies = i < buckets.length ? buckets[i] : [];
				if (bodies.length === 0) {
					this.orbitPool.unwireOne(groupId);
					const stale = this.asteroidPoints.get(key);
					if (stale) {
						this.scene.remove(stale);
						this.asteroidPoints.delete(key);
					}
					continue;
				}
				this.orbitPool.rewireOne(groupId, bodies, skip, (baseWorker + i) % k);
				const existing = this.asteroidPoints.get(key);
				if (existing) {
					this.resizeGeometryIfNeeded(existing.geometry, bodies);
				} else {
					const arr = new Float32Array(bodies.length * 3);
					this.seedGeometryArray(arr, bodies);
					const pts = makePointCloudFromBuffer(
						arr,
						bodies.length,
						this.circleTexture,
						resolveBodyColor(bodies[0].data),
						asteroidPointSize()
					);
					pts.userData.frontBasis = seedBasis;
					pts.userData.groupId = groupId;
					pts.userData.parentVec = [0, 0, 0] as Vec3;
					if (zone === this.emphasizedSmallBodyZone) this.applySmallBodyEmphasis(pts);
					this.asteroidPoints.set(key, pts);
					this.pendingSceneAdds.push(pts);
				}
			}
		}
		this.ctx.bodies.dirtyAsteroidZones.clear();

		for (const gid of this.ctx.bodies.dirtySpacecraftGroups) {
			const bucket = this.ctx.bodies.spacecraftByParent.get(gid);
			const allBodies = bucket ? Array.from(bucket.values()) : [];
			const { buckets, baseWorker } = partitionForWorkers(gid, allBodies, k);
			for (let i = 0; i < k; i++) {
				const key = `${gid}#${i}`;
				const groupId = `spacecraft:${key}`;
				const bodies = i < buckets.length ? buckets[i] : [];
				if (bodies.length === 0) {
					this.orbitPool.unwireOne(groupId);
					const stale = this.spacecraftPoints.get(key);
					if (stale) {
						this.scene.remove(stale);
						this.spacecraftPoints.delete(key);
					}
					continue;
				}
				this.orbitPool.rewireOne(groupId, bodies, skip, (baseWorker + i) % k);
				const existing = this.spacecraftPoints.get(key);
				if (existing) {
					this.resizeGeometryIfNeeded(existing.geometry, bodies);
				} else {
					const arr = new Float32Array(bodies.length * 3);
					const colors = new Float32Array(bodies.length * 3);
					this.seedGeometryArray(arr, bodies, colors);
					// Spacecraft buckets mix SPACECRAFT + DEBRIS under the same
					// parentId — per-vertex colors keep each dot honest instead of
					// painting the whole sub-cloud from bodies[0]'s type.
					const pts = makePointCloudFromBuffer(
						arr,
						bodies.length,
						this.circleTexture,
						'#ffffff',
						undefined,
						colors
					);
					pts.userData.frontBasis = seedBasis;
					pts.userData.groupId = groupId;
					pts.userData.parentBodyId = gid;
					pts.userData.parentVec = [0, 0, 0] as Vec3;
					if (gid === EARTH_ID) this.applyEarthSatEmphasis(pts);
					this.spacecraftPoints.set(key, pts);
					this.pendingSceneAdds.push(pts);
				}
			}
		}
		this.ctx.bodies.dirtySpacecraftGroups.clear();
	}

	/** Write basis-relative positions for `bodies` into the first `bodies.length*3` slots of `arr`.
	 *  When `colorArr` is provided, parallel-writes per-body RGB triplets resolved from each body's type. */
	private seedGeometryArray(
		arr: Float32Array,
		bodies: PositionedBody[],
		colorArr: Float32Array | null = null
	): void {
		const [bx, by, bz] = this.basisPos;
		const n = Math.min(bodies.length, arr.length / 3);
		const tmp = colorArr ? new Color() : null;
		for (let i = 0; i < n; i++) {
			const b = bodies[i];
			const p = b.position;
			arr[i * 3] = p[0] - bx;
			arr[i * 3 + 1] = p[1] - by;
			arr[i * 3 + 2] = p[2] - bz;
			if (colorArr && tmp) {
				tmp.set(resolveBodyColor(b.data));
				colorArr[i * 3] = tmp.r;
				colorArr[i * 3 + 1] = tmp.g;
				colorArr[i * 3 + 2] = tmp.b;
			}
		}
	}

	/** If the geometry's position array no longer matches the body count, swap
	 *  in a freshly-seeded array (size change is rare — only on rewire with
	 *  membership change). Same-capacity rewires leave the attribute alone so
	 *  the next worker result updates it in place. Color attribute (when
	 *  present, spacecraft only) is resized in parallel. */
	private resizeGeometryIfNeeded(geometry: BufferGeometry, bodies: PositionedBody[]): void {
		const need = bodies.length * 3;
		const posAttr = geometry.getAttribute('position') as BufferAttribute;
		const arr = posAttr.array as Float32Array;
		if (arr.length === need) {
			geometry.setDrawRange(0, bodies.length);
			return;
		}
		const hasColors = !!geometry.getAttribute('color');
		const fresh = new Float32Array(need);
		const freshColors = hasColors ? new Float32Array(need) : null;
		this.seedGeometryArray(fresh, bodies, freshColors);
		geometry.setAttribute('position', new BufferAttribute(fresh, 3));
		if (freshColors) geometry.setAttribute('color', new BufferAttribute(freshColors, 3));
		geometry.setDrawRange(0, bodies.length);
	}

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
		const posAttr = pts.geometry.getAttribute('position') as BufferAttribute;
		const arr = posAttr.array as Float32Array;
		// Drop results whose capacity doesn't match the geometry — happens when
		// a worker tick for an old body set lands after a mid-flight rewire
		// resized the group. The next tick under the new set will overwrite
		// this array; in the meantime rebuildMinor's seeded values are correct.
		if (arr.length !== positions.length) return;
		arr.set(positions);
		posAttr.needsUpdate = true;
		pts.geometry.setDrawRange(0, count);
		// Record the basis the worker used so reposition() can use it per-group:
		// a mid-flight rebase would otherwise misplace the cloud for the frame
		// between the basis change and the next worker result.
		pts.userData.frontBasis = [basisUsed[0], basisUsed[1], basisUsed[2]];

		// Snapshot parent-as-dispatched (not parent-now): parentShift() compensates
		// for parent motion between the worker's solve jd and the current frame.
		// Snapshotting post-result would hide the worker-latency motion — visible
		// at high time rates and frozen on pause.
		this.parentAtUpdate.set(groupId, [parentUsed[0], parentUsed[1], parentUsed[2]]);

		// Reposition the Points container now against the new basis + parent.
		// Per-frame reposition only runs on jd-change, so without this a worker
		// result arriving while paused would render the cloud at a stale offset.
		const [fx, fy, fz] = this.focus.focusTruePos;
		const parentNowId = kind === 'asteroid' ? SUN_ID : parentIdFromSubkey(key);
		const parentNow = this.ctx.getBody(parentNowId)?.position;
		const sx = parentNow ? parentNow[0] - parentUsed[0] : 0;
		const sy = parentNow ? parentNow[1] - parentUsed[1] : 0;
		const sz = parentNow ? parentNow[2] - parentUsed[2] : 0;
		pts.position.set(basisUsed[0] - fx + sx, basisUsed[1] - fy + sy, basisUsed[2] - fz + sz);
	};

	/**
	 * Reposition every cloud against the current focus. Minor clouds use their
	 * per-group worker basis (not the live basis) so a rebase landing between
	 * dispatch and result doesn't misplace the cloud for 1-2 frames. Moon
	 * vertex buffers are rewritten each frame in {@link writeMoons} so no
	 * shift is needed for them.
	 */
	reposition(): void {
		const [fx, fy, fz] = this.focus.focusTruePos;
		const currentBasis = this.basisPos;
		for (const [key, pts] of this.asteroidPoints) {
			const b = (pts.userData.frontBasis as Vec3 | undefined) ?? currentBasis;
			const [sx, sy, sz] = this.parentShift(`asteroid:${key}`, SUN_ID);
			pts.position.set(b[0] - fx + sx, b[1] - fy + sy, b[2] - fz + sz);
		}
		for (const [key, pts] of this.spacecraftPoints) {
			const b = (pts.userData.frontBasis as Vec3 | undefined) ?? currentBasis;
			const [sx, sy, sz] = this.parentShift(`spacecraft:${key}`, parentIdFromSubkey(key));
			pts.position.set(b[0] - fx + sx, b[1] - fy + sy, b[2] - fz + sz);
		}
		const [bx, by, bz] = currentBasis;
		const dx = bx - fx;
		const dy = by - fy;
		const dz = bz - fz;
		for (const pts of this.moonPoints.values()) pts.position.set(dx, dy, dz);
	}

	private parentShift(snapshotKey: string, parentId: string): Vec3 {
		const snapshot = this.parentAtUpdate.get(snapshotKey);
		const current = this.ctx.getBody(parentId)?.position;
		if (!snapshot || !current) return [0, 0, 0];
		return [current[0] - snapshot[0], current[1] - snapshot[1], current[2] - snapshot[2]];
	}

	/** Rebase when focus has drifted > 0.01 AU from the current basis. */
	maybeRebase(): void {
		const [fx, fy, fz] = this.focus.focusTruePos;
		const [bx, by, bz] = this.basisPos;
		const dx = fx - bx;
		const dy = fy - by;
		const dz = fz - bz;
		const drift2 = dx * dx + dy * dy + dz * dz;
		const threshold = REBASE_THRESHOLD_AU * AU_SCALE;
		if (drift2 > threshold * threshold) this.rebuildBasis();
	}

	rebuildBasis(): void {
		this.basisPos = [...this.focus.focusTruePos];
		// Asteroid/spacecraft cols are basis-independent — the worker picks up
		// `basisPos` from each `orbitPool.tick`, and each Points renders against
		// its pinned `frontBasis` until the new result lands, so no re-pack here.
		this.rebuildMoons();
		this.onBasisRebuilt();
		// parentShift is non-zero even with (basis − focus) = 0; reposition()
		// applies it to avoid a one-frame cluster jump at high time rates.
		this.reposition();
	}

	/** Per-frame: write moon dots, then dispatch async asteroid/spacecraft solves. */
	updateForJd(jd: number): void {
		this.writeMoons();

		const parents = this._parentsScratch;
		parents.clear();
		const sunPos = this.ctx.getBody(SUN_ID)?.position ?? ([0, 0, 0] as Vec3);
		// groupId string and parentVec tuple are cached on each Points' userData
		// (set at creation) so the per-frame loop doesn't reallocate either —
		// just mutates the existing Vec3 in place and re-binds it in the map.
		for (const pts of this.asteroidPoints.values()) {
			const v = pts.userData.parentVec as Vec3;
			v[0] = sunPos[0];
			v[1] = sunPos[1];
			v[2] = sunPos[2];
			parents.set(pts.userData.groupId as string, v);
		}
		for (const pts of this.spacecraftPoints.values()) {
			const pp = this.ctx.getBody(pts.userData.parentBodyId as string)?.position;
			const v = pts.userData.parentVec as Vec3;
			if (pp) {
				v[0] = pp[0];
				v[1] = pp[1];
				v[2] = pp[2];
			} else {
				v[0] = 0;
				v[1] = 0;
				v[2] = 0;
			}
			parents.set(pts.userData.groupId as string, v);
		}
		this.orbitPool.tick(jd, this.basisPos, parents);
	}

	private moonsByParent(): Map<string, PositionedBody[]> {
		const len = this.ctx.bodies.majorBodies.length;
		if (this.moonsByParentCache?.len === len) return this.moonsByParentCache.map;
		const map = new Map<string, PositionedBody[]>();
		for (const body of this.ctx.bodies.majorBodies) {
			if (body.data.objectType === ObjectType.MOON) {
				const list = map.get(body.data.parentId) ?? [];
				list.push(body);
				map.set(body.data.parentId, list);
			}
		}
		this.moonsByParentCache = { len, map };
		return map;
	}

	private writeMoons(): void {
		const [bx, by, bz] = this.basisPos;
		for (const [parentId, moons] of this.moonsByParent()) {
			const pts = this.moonPoints.get(parentId);
			if (!pts) continue;
			// Skip hidden groups — saves a vertex-buffer rewrite + GPU upload per parent in any non-focused system.
			if (!this.ctx.visibility.isMoonGroupVisible(parentId)) continue;
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

	private rebuildMoons(): void {
		const basis = this.basisPos;
		for (const [parentId, moons] of this.moonsByParent()) {
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

	/** Drain one pending point cloud onto the scene this frame (staggers GPU uploads). */
	drainOnePendingSceneAdd(): void {
		if (this.pendingSceneAdds.length === 0) return;
		const pts = this.pendingSceneAdds.shift()!;
		pts.layers.set(this.mapLayer);
		this.scene.add(pts);
	}

	asteroids(): Map<string, Points> {
		return this.asteroidPoints;
	}
	spacecraft(): Map<string, Points> {
		return this.spacecraftPoints;
	}
	moons(): Map<string, Points> {
		return this.moonPoints;
	}
}

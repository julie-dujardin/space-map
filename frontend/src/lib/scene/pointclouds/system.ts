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
import { AU_SCALE, kmToScene } from '$lib/math/units';
import type { Vec3 } from '$lib/scene/animation/math';
import type { FocusState } from '$lib/scene/animation/focus';
import type { BodyObjects } from '$lib/scene/types';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
import { OrbitWorkerPool } from '$lib/math/orbit/pool';
import { KIND_KEPLER, KIND_SKIP, type OrbitColumns } from '$lib/math/orbit/soa';
import { partitionForWorkersSliced, parentIdFromSubkey } from '$lib/math/orbit/partition';
import { buildPointClouds } from '$lib/scene/objects/body/bulk';
import { asteroidPointSize, makePointCloudFromBuffer } from '$lib/scene/objects/pointcloud';
import { resolveBodyColor } from '$lib/utils';
import { EARTH_ID, SUN_ID } from '$lib/constants';
import { PickRegistry } from '$lib/scene/interaction/pick-registry';

const REBASE_THRESHOLD_AU = 0.01;

/** Sun GM as the Gaussian constant k² (AU³/day²) — heliocentric vis-viva. */
const MU_SUN_AU3_DAY2 = 2.959122082855911e-4;
/** Skip a group's per-frame solve below this predicted on-screen drift (CSS px):
 *  the deferred internal motion is imperceptible, and the container transform
 *  still tracks camera/focus/parent motion. */
const SUBPIXEL_PX = 0.75;
/** Speed cap for spacecraft groups — LEO-class ~8 km/s, above any orbiter's mean
 *  speed. Per-parent element math isn't worth it for these small clouds. */
const SPACECRAFT_MAX_SPEED_SCENE = kmToScene(8 * 86400);

/** Subpixel-gate bounds for one group. `alwaysSolve` covers orbits whose speed
 *  can't be cheaply bounded (unbound/degenerate — no aphelion). */
interface GroupKinematics {
	maxSpeedScene: number;
	alwaysSolve: boolean;
}

/** Per-frame view geometry for the subpixel gate. `camPos` is focus-relative
 *  (controls target is the origin); `pxPerRad` is (viewportHeight / 2) / tan(vFov / 2). */
export interface CloudViewInfo {
	camPos: Vec3;
	pxPerRad: number;
}

/** Fastest perihelion speed across a group's elements; any unbound/degenerate
 *  row flips `alwaysSolve` (vis-viva needs a bound orbit). */
function kinematicsFromColumns(cols: OrbitColumns): GroupKinematics {
	let maxSpeed = 0;
	let alwaysSolve = false;
	for (let idx = 0; idx < cols.count; idx++) {
		if (cols.kind[idx] === KIND_SKIP) continue;
		const a = cols.a[idx];
		const e = cols.e[idx];
		if (cols.kind[idx] !== KIND_KEPLER || !(a > 0) || !(e < 1) || !isFinite(a) || !isFinite(e)) {
			alwaysSolve = true;
			continue;
		}
		const ec = Math.min(e, 1 - 1e-7);
		const v = Math.sqrt((MU_SUN_AU3_DAY2 / a) * ((1 + ec) / (1 - ec)));
		if (v > maxSpeed) maxSpeed = v;
	}
	return { maxSpeedScene: maxSpeed * AU_SCALE, alwaysSolve };
}

function clamp01(x: number): number {
	return x < 0 ? 0 : x > 1 ? 1 : x;
}

function matchesEmphasizedZone(zone: string, target: string): boolean {
	if (target === '*') return zone.startsWith('small_bodies/');
	return zone === target;
}

/** Shared count → ramp intensities for cloud emphasis. `tBright` ramps over
 *  count 10000 → 500 (stage 1), `tSize` over 500 → 50 (stage 2). `null` = no
 *  emphasis (both 0). Earth-sat and small-body class consumers each apply these
 *  to their own size/color/opacity ranges. */
function emphasisIntensity(count: number | null): { tBright: number; tSize: number } {
	if (count === null) return { tBright: 0, tSize: 0 };
	return {
		tBright: clamp01((EMPHASIS_ALPHA_HI - count) / (EMPHASIS_ALPHA_HI - EMPHASIS_ALPHA_LO)),
		tSize: clamp01((EMPHASIS_SIZE_HI - count) / (EMPHASIS_SIZE_HI - EMPHASIS_SIZE_LO))
	};
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

/** Asteroid-class emphasis multipliers at max ramp. Ramp curve is shared with
 *  earth-sat (count thresholds 10000/500/50). Asteroid clouds use a single
 *  material color rather than vertex colors, so brightness applies as a scalar
 *  multiply against the cached baseline `overlayColor(c)` instead of a setRGB. */
const SMALL_BODY_SIZE_MULT_MAX = 2.5;
const SMALL_BODY_BRIGHT_MULT_MAX = 2.0;
const SMALL_BODY_MAX_OPACITY = EMPHASIS_MAX_OPACITY;

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
	/** Maps a GPU pick-pass hit back to a body id. Populated per group at wire
	 *  time; consumed by the pointer's pick pass. */
	readonly pickRegistry = new PickRegistry();
	private asteroidPoints = new Map<string, Points>();
	private spacecraftPoints = new Map<string, Points>();
	private moonPoints = new Map<string, Points>();
	/** Points drawn at once over the visible asteroid and spacecraft clouds. */
	private pointBudget = Infinity;
	/** Prefix of each cloud drawn; rows are hash-ordered, so a prefix is a uniform sample. */
	private drawFraction = 1;
	private pendingSceneAdds: Points[] = [];
	private basisPos: Vec3 = [0, 0, 0];
	/** Snapshot of each group's parent position at its last worker dispatch.
	 *  {@link parentShift} subtracts this from the parent's current position
	 *  so the cloud follows its moving parent between worker results. */
	private parentAtUpdate = new Map<string, Vec3>();
	private readonly _parentsScratch = new Map<string, Vec3>();
	/** Memoized moon → parent grouping; invalidated when majorBodies count changes. */
	private moonsByParentCache: { len: number; map: Map<string, PositionedBody[]> } | null = null;
	/** Bucket size at each group's last full pack (keys `asteroid:<zone>` /
	 *  `spacecraft:<gid>`). While the minor stream is in flight, a dirty group
	 *  is only repacked once it doubles past this — repacking the whole zone on
	 *  every 500ms flush is O(loaded-so-far) and was the dominant flush cost. */
	private lastPackedSize = new Map<string, number>();
	/** Worst-case screen-velocity bounds per groupId, for the subpixel gate.
	 *  Computed once at wire time (elements don't change between repacks). */
	private groupKinematics = new Map<string, GroupKinematics>();
	/** jd each group's front buffer was last solved at, set when a worker result
	 *  lands. The gate measures elapsed jd against this to predict drift. */
	private lastSolvedJd = new Map<string, number>();
	/** Last earth-sat emphasis values applied. Used to re-apply to newly-built
	 *  earth sub-clouds (rebuildMinor recreates them after a group filter swap). */
	private earthSatEmphasis = {
		size: EMPHASIS_BASE_SIZE,
		dim: EMPHASIS_BASE_DIM,
		opacity: EMPHASIS_BASE_OPACITY
	};
	/** Emphasis target: `small_bodies/<class>` for class filters, `'*'` for flag
	 *  filters (every small-body sub-cloud), null otherwise. */
	private emphasizedSmallBodyZone: string | null = null;
	/** Current ramp values for the emphasized zone, recomputed from the bucket's
	 *  body count. Mirrors the earth-sat ramp curve so a sparse class (CEN ~few
	 *  hundred) lands at max embiggen while dense ones (MBA >10k) sit at
	 *  baseline. */
	private smallBodyEmphasis = {
		sizeMult: 1,
		brightMult: 1,
		opacity: EMPHASIS_BASE_OPACITY
	};

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

	setPointBudget(budget: number): void {
		this.pointBudget = budget;
		this.applyPointBudget();
	}

	/** Size the drawn prefix of every cloud so the visible ones fit the budget. */
	applyPointBudget(): void {
		let total = 0;
		for (const pts of this.asteroidPoints.values()) {
			if (pts.visible) total += (pts.userData.solvedCount as number | undefined) ?? 0;
		}
		for (const pts of this.spacecraftPoints.values()) {
			if (pts.visible) total += (pts.userData.solvedCount as number | undefined) ?? 0;
		}
		const fraction = total > this.pointBudget ? this.pointBudget / total : 1;
		if (fraction === this.drawFraction) return;
		this.drawFraction = fraction;
		for (const map of [this.asteroidPoints, this.spacecraftPoints]) {
			for (const pts of map.values()) {
				const n = pts.userData.solvedCount as number | undefined;
				if (n !== undefined) pts.geometry.setDrawRange(0, Math.ceil(n * fraction));
			}
		}
	}

	/** Ramp earth-sat cloud size + alpha when only a few members remain. `count`
	 *  is the currently-visible member count (focused group under a filter, else
	 *  the whole cloud); `null` resets to baseline. Stage 1 (10000 → 500) raises
	 *  alpha + brightness; stage 2 (500 → 50) raises size. */
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
		const { tBright, tSize } = emphasisIntensity(count);
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

	/** Emphasize a `small_bodies/<class>` zone — size/brightness/opacity ramp
	 *  against `count`, same thresholds as earth-sat. Sentinel `'*'` ramps every
	 *  small-body sub-cloud (flag-kind filters cut across zones). Null clears.
	 *  Safe before sub-clouds exist; rebuildMinor re-applies on creation. */
	setEmphasizedSmallBodyZone(zone: string | null, count: number | null): void {
		const prev = this.emphasizedSmallBodyZone;
		this.emphasizedSmallBodyZone = zone;
		this.smallBodyEmphasis = this.computeSmallBodyEmphasis(zone === null ? null : count);
		if (prev !== null && prev !== zone) {
			for (const [key, pts] of this.asteroidPoints) {
				if (matchesEmphasizedZone(parentIdFromSubkey(key), prev)) {
					this.resetSmallBodyEmphasis(pts);
				}
			}
		}
		if (zone !== null) {
			for (const [key, pts] of this.asteroidPoints) {
				if (matchesEmphasizedZone(parentIdFromSubkey(key), zone)) {
					this.applySmallBodyEmphasis(pts);
				}
			}
		}
	}

	private computeSmallBodyEmphasis(count: number | null): {
		sizeMult: number;
		brightMult: number;
		opacity: number;
	} {
		const { tBright, tSize } = emphasisIntensity(count);
		return {
			sizeMult: 1 + (SMALL_BODY_SIZE_MULT_MAX - 1) * tSize,
			brightMult: 1 + (SMALL_BODY_BRIGHT_MULT_MAX - 1) * tBright,
			opacity: EMPHASIS_BASE_OPACITY + (SMALL_BODY_MAX_OPACITY - EMPHASIS_BASE_OPACITY) * tBright
		};
	}

	private applySmallBodyEmphasis(pts: Points): void {
		const mat = pts.material as PointsMaterial;
		if (pts.userData.smallBodyBaseSize === undefined) {
			pts.userData.smallBodyBaseSize = mat.size;
			pts.userData.smallBodyBaseColor = mat.color.clone();
		}
		const baseSize = pts.userData.smallBodyBaseSize as number;
		const baseColor = pts.userData.smallBodyBaseColor as Color;
		const { sizeMult, brightMult, opacity } = this.smallBodyEmphasis;
		mat.size = baseSize * sizeMult;
		mat.color.copy(baseColor).multiplyScalar(brightMult);
		mat.opacity = opacity;
	}

	private resetSmallBodyEmphasis(pts: Points): void {
		if (pts.userData.smallBodyBaseSize === undefined) return;
		const mat = pts.material as PointsMaterial;
		mat.size = pts.userData.smallBodyBaseSize as number;
		mat.color.copy(pts.userData.smallBodyBaseColor as Color);
		mat.opacity = EMPHASIS_BASE_OPACITY;
		pts.userData.smallBodyBaseSize = undefined;
		pts.userData.smallBodyBaseColor = undefined;
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
		// Same for small-body focus: a deep-linked /g/class-* page may have set the
		// emphasis before the initial build ran.
		if (this.emphasizedSmallBodyZone !== null) {
			const target = this.emphasizedSmallBodyZone;
			for (const [key, p] of this.asteroidPoints) {
				if (matchesEmphasizedZone(parentIdFromSubkey(key), target)) {
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

	/** Serialization for {@link rebuildMinor}'s async passes: one pass at a
	 *  time; calls landing mid-pass queue a single follow-up pass. */
	private rebuildRunning = false;
	private rebuildQueued = false;

	/**
	 * Sync pool wiring and Three.js geometries with the ctx's dirty markers.
	 * New chunks landing, the promoted set changing, and basis rebuilds all
	 * add to dirty markers — this drains them. Fire-and-forget: the actual
	 * pass is async (packs yield to keep input responsive) and serialized, so
	 * the wiring lands a few frames later rather than within this call.
	 */
	rebuildMinor(): void {
		if (this.rebuildRunning) {
			this.rebuildQueued = true;
			return;
		}
		this.rebuildRunning = true;
		void (async () => {
			try {
				do {
					this.rebuildQueued = false;
					await this.rebuildMinorPass();
				} while (this.rebuildQueued);
			} finally {
				this.rebuildRunning = false;
			}
		})();
	}

	/** In-flight recovery, shared by concurrent callers. */
	private recovering: Promise<boolean> | null = null;

	/**
	 * Respawn the pool and re-wire every group if a worker died. Returns true on
	 * respawn. Moons solve on the main thread, so they're unaffected.
	 *
	 * Single-flight: a mobile tab returning fires both `visibilitychange` and
	 * `webglcontextrestored`, and two overlapping probes would respawn twice —
	 * the second respawn killing the pool the first was still re-wiring into.
	 */
	recoverWorkersIfDead(timeoutMs?: number): Promise<boolean> {
		this.recovering ??= this.runRecovery(timeoutMs).finally(() => (this.recovering = null));
		return this.recovering;
	}

	private async runRecovery(timeoutMs?: number): Promise<boolean> {
		if (await this.orbitPool.ping(timeoutMs)) return false;
		this.orbitPool.respawn();
		// Respawned pool has no wiring; re-mark all and clear the gate so a full
		// repack runs even mid-stream.
		for (const zone of this.ctx.bodies.asteroidBodiesByZone.keys())
			this.ctx.bodies.dirtyAsteroidZones.add(zone);
		for (const gid of this.ctx.bodies.spacecraftByParent.keys())
			this.ctx.bodies.dirtySpacecraftGroups.add(gid);
		this.lastPackedSize.clear();
		this.rebuildMinor();
		return true;
	}

	/**
	 * One drain of the dirty markers. Each Points' geometry owns a persistent
	 * `Float32Array`: only resized when the body count changes, otherwise left
	 * in place so a worker result can `.set()` into it under the same
	 * `BufferAttribute`. That stable attribute identity lets Three.js reuse
	 * the WebGL VBO instead of `createBuffer`-ing a fresh one every tick.
	 */
	private async rebuildMinorPass(): Promise<void> {
		if (
			this.ctx.bodies.dirtyAsteroidZones.size === 0 &&
			this.ctx.bodies.dirtySpacecraftGroups.size === 0
		) {
			return;
		}
		const seedBasis: Vec3 = [this.basisPos[0], this.basisPos[1], this.basisPos[2]];
		const k = this.orbitPool.workerCount;
		// A respawn landing mid-pass throws away every wire made so far, and the
		// consumed dirty markers would offer no second chance — so remember what
		// this pass drained and re-mark it if the pool turned over underneath.
		const generation = this.orbitPool.poolGeneration;
		const drainedZones: string[] = [];
		const drainedGroups: string[] = [];
		// The skip-set (promoted ids) is captured fresh per group right before its
		// pack, not once here: this pass is async, and a promotion that lands during
		// an earlier group's await would otherwise be missed — leaving its body in
		// the cloud as a live dot *and* a halo, with the consumed dirty marker
		// offering no second chance.

		for (const zone of [...this.ctx.bodies.dirtyAsteroidZones]) {
			const bucket = this.ctx.bodies.asteroidBodiesByZone.get(zone);
			if (this.deferPackWhileStreaming(`asteroid:${zone}`, bucket?.size ?? 0)) continue;
			this.ctx.bodies.dirtyAsteroidZones.delete(zone);
			drainedZones.push(zone);
			// Fill the worker SoA straight from the bucket's columns — no
			// PositionedBody[] round-trip, no throwaway main-thread Kepler solve.
			const skip = new Set(this.bodyObjects.keys());
			const { groups, baseWorker } = bucket
				? await bucket.buildWorkerGroups(zone, k, skip, false)
				: { groups: [], baseWorker: 0 };
			const cloudColor = bucket && groups.length > 0 ? bucket.cloudColor() : '#888888';
			// Iterate full K (not groups.length) so subgroups #1..#K-1 get
			// unwired when a zone shrinks below the split threshold.
			for (let i = 0; i < k; i++) {
				const key = `${zone}#${i}`;
				const groupId = `asteroid:${key}`;
				const group = i < groups.length ? groups[i] : null;
				if (!group || group.cols.count === 0) {
					this.orbitPool.unwireOne(groupId);
					this.forgetGroupGate(groupId);
					this.pickRegistry.release(groupId);
					const stale = this.asteroidPoints.get(key);
					if (stale) {
						this.scene.remove(stale);
						this.asteroidPoints.delete(key);
					}
					continue;
				}
				// Compute the gate's kinematics before rewireOneCols — it transfers the
				// column buffers to the worker, detaching them on this thread.
				this.groupKinematics.set(groupId, kinematicsFromColumns(group.cols));
				// A repack grows the buffer (streaming chunks); force one solve so the
				// new points get positions and drawRange expands instead of being gated.
				this.lastSolvedJd.delete(groupId);
				// Assign this group's GPU pick-id range before wiring — the worker
				// writes `pickBase + row` per survivor for the pick pass to decode.
				group.cols.pickBase = this.pickRegistry.allocate(groupId, group.ids);
				this.orbitPool.rewireOneCols(groupId, group.cols, (baseWorker + i) % k);
				const existing = this.asteroidPoints.get(key);
				if (existing) {
					this.resizeGeometryToCount(existing.geometry, group.cols.count, null);
				} else {
					// Positions start empty (drawRange 0) — the first worker tick
					// fills them and expands the draw range; no origin flash.
					const pts = makePointCloudFromBuffer(
						new Float32Array(group.cols.count * 3),
						0,
						this.circleTexture,
						cloudColor,
						asteroidPointSize()
					);
					pts.userData.frontBasis = seedBasis;
					pts.userData.groupId = groupId;
					pts.userData.parentVec = [0, 0, 0] as Vec3;
					if (
						this.emphasizedSmallBodyZone !== null &&
						matchesEmphasizedZone(zone, this.emphasizedSmallBodyZone)
					) {
						this.applySmallBodyEmphasis(pts);
					}
					this.asteroidPoints.set(key, pts);
					this.pendingSceneAdds.push(pts);
				}
			}
		}

		// Spacecraft stay on the AoS path (Earth sats / debris — small count plus
		// time-segmented hot-reload + group filters that the columnar bulk path
		// doesn't model). Same partition + pack + seed as before.
		for (const gid of [...this.ctx.bodies.dirtySpacecraftGroups]) {
			const bucket = this.ctx.bodies.spacecraftByParent.get(gid);
			if (this.deferPackWhileStreaming(`spacecraft:${gid}`, bucket?.size ?? 0)) continue;
			this.ctx.bodies.dirtySpacecraftGroups.delete(gid);
			drainedGroups.push(gid);
			const allBodies = bucket ? Array.from(bucket.values()) : [];
			const { buckets, baseWorker } = await partitionForWorkersSliced(gid, allBodies, k);
			// Capture after the partition await so group promotion (which runs on a
			// chunk flush, possibly between this pass starting and here) is reflected.
			const skip = new Set(this.bodyObjects.keys());
			for (let i = 0; i < k; i++) {
				const key = `${gid}#${i}`;
				const groupId = `spacecraft:${key}`;
				const bodies = i < buckets.length ? buckets[i] : [];
				if (bodies.length === 0) {
					this.orbitPool.unwireOne(groupId);
					this.forgetGroupGate(groupId);
					this.pickRegistry.release(groupId);
					const stale = this.spacecraftPoints.get(key);
					if (stale) {
						this.scene.remove(stale);
						this.spacecraftPoints.delete(key);
					}
					continue;
				}
				// packBodiesSliced fills rows in `bodies` order, so ids line up with
				// the worker's `pickBase + row` pick-ids.
				const pickBase = this.pickRegistry.allocate(
					groupId,
					bodies.map((b) => b.data.id)
				);
				await this.orbitPool.rewireOne(
					groupId,
					bodies,
					skip,
					(baseWorker + i) % k,
					false,
					pickBase
				);
				this.groupKinematics.set(groupId, {
					maxSpeedScene: SPACECRAFT_MAX_SPEED_SCENE,
					alwaysSolve: false
				});
				// Force one solve after a repack so newly-added members get positions.
				this.lastSolvedJd.delete(groupId);
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

		if (this.orbitPool.poolGeneration !== generation) {
			for (const zone of drainedZones) this.ctx.bodies.dirtyAsteroidZones.add(zone);
			for (const gid of drainedGroups) this.ctx.bodies.dirtySpacecraftGroups.add(gid);
			this.lastPackedSize.clear();
			this.rebuildQueued = true;
		}
	}

	/** Streaming-phase repack throttle. Returns true when `key`'s group should
	 *  stay dirty and skip this rebuild: it grew since the last pack but hasn't
	 *  doubled yet. Unchanged sizes (promotion/teardown skip-set changes) and
	 *  first arrivals always pack; once the stream ends the final flush drains
	 *  whatever is still dirty. */
	private deferPackWhileStreaming(key: string, size: number): boolean {
		if (!this.ctx.bodies.minorStreaming) {
			this.lastPackedSize.set(key, size);
			return false;
		}
		const last = this.lastPackedSize.get(key);
		if (last !== undefined && size > last && size < last * 2) return true;
		this.lastPackedSize.set(key, size);
		return false;
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

	/** AoS (spacecraft) geometry resize: if the position array no longer matches
	 *  the body count, swap in a freshly-seeded array (size change is rare — only
	 *  on rewire with membership change). Same-capacity rewires leave the
	 *  attribute alone so the next worker result updates it in place. */
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

	/**
	 * Columnar (asteroid) geometry resize to a new body `count`. Same-capacity
	 * rebuilds leave the position attribute alone (next worker result updates
	 * it in place). On a size change, swaps in a fresh array, copying the
	 * stable prefix (ids are append-only and hash-stable) so visible dots
	 * survive until the next tick repopulates the buffer.
	 */
	private resizeGeometryToCount(
		geometry: BufferGeometry,
		count: number,
		colors: Float32Array | null
	): void {
		const need = count * 3;
		const posAttr = geometry.getAttribute('position') as BufferAttribute;
		const arr = posAttr.array as Float32Array;
		if (colors) geometry.setAttribute('color', new BufferAttribute(colors, 3));
		if (arr.length === need) return; // worker keeps filling the same buffer
		const fresh = new Float32Array(need);
		fresh.set(arr.subarray(0, Math.min(arr.length, need)));
		geometry.setAttribute('position', new BufferAttribute(fresh, 3));
		// Keep the prior draw range (clamped) so the existing prefix stays
		// visible; the next worker tick expands it to the new count.
		const prev = Math.min(geometry.drawRange.count, count);
		geometry.setDrawRange(0, Number.isFinite(prev) ? prev : 0);
	}

	private onPoolResult = (
		groupId: string,
		positions: Float32Array,
		count: number,
		basisUsed: Vec3,
		parentUsed: Vec3,
		jd: number,
		pickIds: Uint8Array
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
		// Leave lastSolvedJd untouched so the gate still forces that re-solve.
		if (arr.length !== positions.length) return;
		arr.set(positions);
		posAttr.needsUpdate = true;
		this.bindPickIds(pts, pickIds);
		pts.userData.solvedCount = count;
		pts.geometry.setDrawRange(0, Math.ceil(count * this.drawFraction));
		// The front buffer now reflects this jd; the gate measures drift from here.
		this.lastSolvedJd.set(groupId, jd);
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

	/** Copy the worker's compact pick-id bytes into a stable, geometry-owned
	 *  `pickColor` attribute. Owned separately from the pool's ping-pong buffer,
	 *  which gets transferred back to the worker next tick. Normalized so the
	 *  pick shader passes the raw bytes straight through as the fragment colour. */
	private bindPickIds(pts: Points, pickIds: Uint8Array): void {
		const attr = pts.geometry.getAttribute('pickColor') as BufferAttribute | undefined;
		if (attr && attr.array.length === pickIds.length) {
			(attr.array as Uint8Array).set(pickIds);
			attr.needsUpdate = true;
		} else {
			pts.geometry.setAttribute('pickColor', new BufferAttribute(pickIds.slice(), 4, true));
		}
	}

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

	/** Per-frame: write moon dots, then dispatch async asteroid/spacecraft solves.
	 *  `view` drives the subpixel gate: a group whose fastest body would drift
	 *  less than {@link SUBPIXEL_PX} on screen since its last solve is left out of
	 *  the tick — the container transform keeps it placed, the re-solve waits. */
	updateForJd(jd: number, view: CloudViewInfo): void {
		this.writeMoons();

		const parents = this._parentsScratch;
		parents.clear();
		const sunPos = this.ctx.getBody(SUN_ID)?.position ?? ([0, 0, 0] as Vec3);
		// Only visible clouds go in the map; orbitPool.tick solves exactly these,
		// so zooming into a system drops the hidden zones' Kepler solves.
		// groupId/parentVec are cached on userData and mutated in place — no realloc.
		for (const [key, pts] of this.asteroidPoints) {
			if (!this.ctx.visibility.isAsteroidGroupVisible(parentIdFromSubkey(key))) continue;
			const groupId = pts.userData.groupId as string;
			if (!this.shouldSolveGroup(groupId, sunPos, jd, view)) continue;
			const v = pts.userData.parentVec as Vec3;
			v[0] = sunPos[0];
			v[1] = sunPos[1];
			v[2] = sunPos[2];
			parents.set(groupId, v);
		}
		for (const [key, pts] of this.spacecraftPoints) {
			if (!this.ctx.visibility.isSpacecraftGroupVisible(parentIdFromSubkey(key))) continue;
			const groupId = pts.userData.groupId as string;
			const pp = this.ctx.getBody(pts.userData.parentBodyId as string)?.position;
			// No parent position (parent not resident) → always solve; the gate's
			// distance term would be meaningless.
			if (pp && !this.shouldSolveGroup(groupId, pp, jd, view)) continue;
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
			parents.set(groupId, v);
		}
		this.orbitPool.tick(jd, this.basisPos, parents, this.ctx.visibility.getRequiredFlags());
	}

	/** Whether `groupId` should be re-solved this frame: predicted on-screen drift
	 *  of its fastest body since the last solve ≥ {@link SUBPIXEL_PX}. Distance is
	 *  camera→parent rather than the nearer cloud edge — at the rates where this
	 *  skips, motion is sub-pixel well inside the parent's distance anyway, so the
	 *  simpler bound stays safe. Always solves the first frame and unboundable groups. */
	private shouldSolveGroup(
		groupId: string,
		parentWorld: Vec3,
		jd: number,
		view: CloudViewInfo
	): boolean {
		const kin = this.groupKinematics.get(groupId);
		if (!kin || kin.alwaysSolve) return true;
		const last = this.lastSolvedJd.get(groupId);
		if (last === undefined || !isFinite(last)) return true;
		const [fx, fy, fz] = this.focus.focusTruePos;
		const dx = view.camPos[0] - (parentWorld[0] - fx);
		const dy = view.camPos[1] - (parentWorld[1] - fy);
		const dz = view.camPos[2] - (parentWorld[2] - fz);
		const dist = Math.max(1e-6, Math.sqrt(dx * dx + dy * dy + dz * dz));
		const days = Math.abs(jd - last);
		const predictedPx = ((kin.maxSpeedScene * days) / dist) * view.pxPerRad;
		return predictedPx >= SUBPIXEL_PX;
	}

	/** Drop a group's gate bookkeeping when it's unwired (zone shrank, teardown). */
	private forgetGroupGate(groupId: string): void {
		this.groupKinematics.delete(groupId);
		this.lastSolvedJd.delete(groupId);
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
				const m = moons[i];
				// Hide out-of-range moons (undiscovered, or past their validity
				// window): a NaN vertex isn't rasterized, and these Points have
				// frustumCulled = false so NaN can't poison the bounding sphere.
				if (this.bodyObjects.get(m.data.id)?.outOfRange) {
					arr[i * 3] = arr[i * 3 + 1] = arr[i * 3 + 2] = NaN;
					continue;
				}
				arr[i * 3] = m.position[0] - bx;
				arr[i * 3 + 1] = m.position[1] - by;
				arr[i * 3 + 2] = m.position[2] - bz;
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

	/** Terminate the worker pool and free cloud GPU buffers on teardown — else
	 *  each map→credits→map round trip leaks a fresh set of workers. */
	dispose(): void {
		this.orbitPool.destroy();
		this.pickRegistry.clear();
		for (const map of [this.asteroidPoints, this.spacecraftPoints, this.moonPoints]) {
			for (const pts of map.values()) {
				this.scene.remove(pts);
				pts.geometry.dispose();
				(pts.material as PointsMaterial).dispose();
			}
			map.clear();
		}
		for (const pts of this.pendingSceneAdds) {
			pts.geometry.dispose();
			(pts.material as PointsMaterial).dispose();
		}
		this.pendingSceneAdds.length = 0;
	}
}

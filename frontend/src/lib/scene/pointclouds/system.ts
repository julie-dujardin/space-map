import {
	BufferAttribute,
	Float32BufferAttribute,
	Points,
	type CanvasTexture,
	type Scene
} from 'three';
import { ObjectType, type PositionedBody } from '$lib/types/objects';
import { AU_SCALE } from '$lib/math/units';
import type { Vec3 } from '$lib/scene/animation/math';
import type { FocusState } from '$lib/scene/animation/focus';
import type { BodyObjects } from '$lib/scene/types';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
import { OrbitWorkerPool } from '$lib/math/orbit/pool';
import { buildPointClouds } from '$lib/scene/objects/construction';
import { asteroidPointSize, makePointCloudFromBuffer } from '$lib/scene/objects/builders';
import { resolveBodyColor } from '$lib/utils';

const REBASE_THRESHOLD_AU = 0.01;

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
			promotedIds
		);
		this.asteroidPoints = pts.asteroidPoints;
		this.spacecraftPoints = pts.spacecraftPoints;
		this.moonPoints = pts.moonPoints;
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
	 * Existing groups keep the pool's worker-computed front buffer (over-
	 * writing would clobber fresh data with stale load-time positions and
	 * flicker on rebase). New zones get a Points seeded from `body.position`.
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

		for (const zone of this.ctx.bodies.dirtyAsteroidZones) {
			const groupId = `asteroid:${zone}`;
			const bucket = this.ctx.bodies.asteroidBodiesByZone.get(zone);
			if (!bucket || bucket.size === 0) {
				this.orbitPool.unwireOne(groupId);
				const stale = this.asteroidPoints.get(zone);
				if (stale) {
					this.scene.remove(stale);
					this.asteroidPoints.delete(zone);
				}
				continue;
			}
			const bodies = Array.from(bucket.values());
			this.orbitPool.rewireOne(groupId, bodies, skip);
			const front = this.orbitPool.front(groupId);
			if (!front) continue;
			const existing = this.asteroidPoints.get(zone);
			if (existing) {
				existing.geometry.setAttribute('position', new BufferAttribute(front, 3));
			} else {
				this.seedFront(front, bodies);
				const pts = makePointCloudFromBuffer(
					front,
					bodies.length,
					this.circleTexture,
					resolveBodyColor(bodies[0].data),
					asteroidPointSize()
				);
				pts.userData.frontBasis = seedBasis;
				this.asteroidPoints.set(zone, pts);
				this.pendingSceneAdds.push(pts);
			}
		}
		this.ctx.bodies.dirtyAsteroidZones.clear();

		for (const gid of this.ctx.bodies.dirtySpacecraftGroups) {
			const groupId = `spacecraft:${gid}`;
			const bucket = this.ctx.bodies.spacecraftByParent.get(gid);
			if (!bucket || bucket.size === 0) {
				this.orbitPool.unwireOne(groupId);
				const stale = this.spacecraftPoints.get(gid);
				if (stale) {
					this.scene.remove(stale);
					this.spacecraftPoints.delete(gid);
				}
				continue;
			}
			const bodies = Array.from(bucket.values());
			this.orbitPool.rewireOne(groupId, bodies, skip);
			const front = this.orbitPool.front(groupId);
			if (!front) continue;
			const existing = this.spacecraftPoints.get(gid);
			if (existing) {
				existing.geometry.setAttribute('position', new BufferAttribute(front, 3));
			} else {
				this.seedFront(front, bodies);
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
		this.ctx.bodies.dirtySpacecraftGroups.clear();
	}

	/** Fill a pool-owned Float32Array with basis-relative positions for the 1-2 frames before the first worker result. */
	private seedFront(front: Float32Array, bodies: PositionedBody[]): void {
		const [bx, by, bz] = this.basisPos;
		const n = Math.min(bodies.length, front.length / 3);
		for (let i = 0; i < n; i++) {
			const p = bodies[i].position;
			front[i * 3] = p[0] - bx;
			front[i * 3 + 1] = p[1] - by;
			front[i * 3 + 2] = p[2] - bz;
		}
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
		pts.geometry.setAttribute('position', new BufferAttribute(positions, 3));
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
		const parentNowId = kind === 'asteroid' ? 'naif-10' : key;
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
		for (const zone of this.asteroidPoints.keys()) this.ctx.bodies.dirtyAsteroidZones.add(zone);
		for (const gid of this.spacecraftPoints.keys()) this.ctx.bodies.dirtySpacecraftGroups.add(gid);
		this.rebuildMinor();
		// Don't reset parent snapshots: vertex buffers were rewritten from the
		// stale `body.position` left over from the last round-robin write, so
		// the snapshot must stay pinned to that same moment. Resetting it would
		// make parentShift undercompensate and the cluster would jump.
		this.rebuildMoons();
		this.onBasisRebuilt();
		// (basis − focus) = 0 now, but parentShift is non-zero. Repositioning
		// applies the shift; hardcoding 0 misplaces clusters by ~parentShift
		// for one frame — reads as a visibility flicker at high time rates.
		this.reposition();
	}

	/** Per-frame: write moon dots, then dispatch async asteroid/spacecraft solves. */
	updateForJd(jd: number): void {
		this.writeMoons();

		const parents = this._parentsScratch;
		parents.clear();
		const sunPos = this.ctx.getBody('naif-10')?.position ?? ([0, 0, 0] as Vec3);
		for (const [zone] of this.ctx.bodies.asteroidBodiesByZone) {
			parents.set(`asteroid:${zone}`, [sunPos[0], sunPos[1], sunPos[2]]);
		}
		for (const [gid] of this.ctx.bodies.spacecraftByParent) {
			const pp = this.ctx.getBody(gid)?.position ?? ([0, 0, 0] as Vec3);
			parents.set(`spacecraft:${gid}`, [pp[0], pp[1], pp[2]]);
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

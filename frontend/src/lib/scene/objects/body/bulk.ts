import { type CanvasTexture, type Points, type PointsMaterial, type Scene } from 'three';
import { resolveBodyColor } from '$lib/utils';
import { BODY_COLORS } from '$lib/constants';
import { ObjectType, type PositionedBody } from '$lib/types/objects';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
import type { BodyObjects } from '../../types';
import { asteroidPointSize, makePointCloud } from '../pointcloud';
import { makeTrail } from '../trail/builder';
import { isMeshUpgradable } from './lifecycle';
import { partitionForWorkers } from '$lib/math/orbit/partition';

function excludePromoted(
	bodies: Iterable<PositionedBody>,
	promotedIds?: Set<string>
): PositionedBody[] {
	if (!promotedIds || promotedIds.size === 0) return [...bodies];
	const out: PositionedBody[] = [];
	for (const b of bodies) {
		if (!promotedIds.has(b.data.id)) out.push(b);
	}
	return out;
}

/**
 * Per-body trail width in pixels. Planets get a chunky 4px line so they
 * read at a glance against the busier minor-body field; named moons (those
 * with a colour entry in {@link BODY_COLORS}) get 3px to stand out from the
 * mass of unnamed satellites without overwhelming the planet they orbit.
 */
function trailWidthFor(body: PositionedBody): number {
	if (body.data.objectType === ObjectType.PLANET) return 4;
	if (
		(body.data.objectType === ObjectType.MOON ||
			body.data.objectType === ObjectType.DWARF_PLANET) &&
		BODY_COLORS[body.data.id]
	)
		return 3;
	return 1;
}

export function buildTrails(
	bodyObjects: Map<string, BodyObjects>,
	scene: Scene,
	basisPos: [number, number, number] = [0, 0, 0],
	jd?: number
): void {
	for (const [, bo] of bodyObjects) {
		if (bo.trail !== null) continue;
		const { body } = bo;
		// STAR is the Sun — no trail. Halo-only mesh-upgradable bodies
		// (asteroids, comets, probes) render as halo + label only by design,
		// so we skip trail build until focus runs `upgradeBodyMesh` — building
		// it would burn ~512 Kepler solves per body for nothing. Barycenters
		// and Lagrange points stay halo-only forever and keep their trails.
		if (body.data.objectType === ObjectType.STAR) continue;
		if (!bo.mesh && isMeshUpgradable(body)) continue;
		// Probes whose elements were null at processProbes time (typically
		// because systems-global GMs hadn't landed yet) carry a rederive
		// callback — retry it now so the trail self-heals on the next
		// buildTrails pass once GMs are populated. Without this the
		// per-frame refresh path is unreachable: refreshTrail
		// only runs when `bo.trail` exists.
		if (!body.orbitElements && body.rederiveElements && jd !== undefined) {
			const fresh = body.rederiveElements(jd);
			if (fresh) body.orbitElements = fresh;
		}
		// Skip bodies with no trail source. Trail-buffer-backed probes
		// have no `orbitElements` (the buffer takes over the trail entirely),
		// so they take this branch via the buffer instead.
		if (!body.orbitElements && !body.trailBuffer) continue;
		const color = resolveBodyColor(body.data);
		const line = makeTrail(body, color, basisPos, jd, trailWidthFor(body));
		scene.add(line);
		bo.trail = line;
	}
}

export function buildPointClouds(
	ctx: ContextManager,
	scene: Scene,
	circleTexture: CanvasTexture,
	basisPos: [number, number, number] = [0, 0, 0],
	promotedIds: Set<string> | undefined,
	workerCount: number
): {
	asteroidPoints: Map<string, Points>;
	spacecraftPoints: Map<string, Points>;
	moonPoints: Map<string, Points>;
} {
	const asteroidPoints = new Map<string, Points>();
	const spacecraftPoints = new Map<string, Points>();
	const moonPoints = new Map<string, Points>();

	// Asteroid point clouds: each zone hash-partitioned via partitionForWorkers
	// — big zones split into K=workerCount subgroups (`${zone}#${i}`) so each
	// rides its own worker, small zones stay single-bucket on one worker.
	const asteroidSize = asteroidPointSize();
	for (const [zone, byId] of ctx.bodies.asteroidBodiesByZone) {
		const filtered = excludePromoted(byId.values(), promotedIds);
		if (filtered.length === 0) continue;
		const color = resolveBodyColor(filtered[0].data);
		const { buckets } = partitionForWorkers(zone, filtered, workerCount);
		for (let i = 0; i < buckets.length; i++) {
			const bucket = buckets[i];
			if (bucket.length === 0) continue;
			const pts = makePointCloud(bucket, circleTexture, color, basisPos, asteroidSize);
			pts.userData.groupId = `asteroid:${zone}#${i}`;
			pts.userData.parentVec = [0, 0, 0];
			asteroidPoints.set(`${zone}#${i}`, pts);
			scene.add(pts);
		}
	}

	// Spacecraft point clouds: same hash-partition as asteroids.
	for (const [groupParentId, byId] of ctx.bodies.spacecraftByParent.entries()) {
		const filtered = excludePromoted(byId.values(), promotedIds);
		if (filtered.length === 0) continue;
		const color = resolveBodyColor(filtered[0].data);
		const { buckets } = partitionForWorkers(groupParentId, filtered, workerCount);
		for (let i = 0; i < buckets.length; i++) {
			const bucket = buckets[i];
			if (bucket.length === 0) continue;
			const points = makePointCloud(bucket, circleTexture, color, basisPos);
			points.userData.groupId = `spacecraft:${groupParentId}#${i}`;
			points.userData.parentBodyId = groupParentId;
			points.userData.parentVec = [0, 0, 0];
			spacecraftPoints.set(`${groupParentId}#${i}`, points);
			scene.add(points);
		}
	}

	// Moon point clouds (one per parent body, initially hidden)
	const moonsByParent = new Map<string, PositionedBody[]>();
	for (const body of ctx.bodies.majorBodies) {
		if (body.data.objectType === ObjectType.MOON) {
			const list = moonsByParent.get(body.data.parentId) ?? [];
			list.push(body);
			moonsByParent.set(body.data.parentId, list);
		}
	}
	for (const [parentId, moons] of moonsByParent) {
		const pts = makePointCloud(moons, circleTexture, resolveBodyColor(moons[0].data), basisPos);
		const mat = pts.material as PointsMaterial;
		// Render moon dots in the opaque pass with alpha-tested cutout. Lets the
		// body mesh occlude its own dot cleanly via depth test once the camera
		// is close enough that the mesh fills the sprite footprint — without
		// this, the transparent-pass dot punches through the mesh at center.
		mat.transparent = false;
		mat.alphaTest = 0.5;
		mat.depthTest = true;
		mat.depthWrite = true;
		pts.visible = false;
		moonPoints.set(parentId, pts);
		scene.add(pts);
	}

	return { asteroidPoints, spacecraftPoints, moonPoints };
}

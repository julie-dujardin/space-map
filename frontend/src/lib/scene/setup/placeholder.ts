import { ObjectType, isAsteroid, type BodyData, type PositionedBody } from '$lib/types/objects';
import { fetchObjectDetail } from '$lib/fetch/objects/object-data';
import { bodyDataFromGlobal, unplacedBodyDataFromGlobal } from '$lib/fetch/objects/global-body';
import { orbitalElementsToPosition, parabolicToPosition } from '$lib/math/orbit/position';
import { sgp4PositionScene } from '$lib/math/orbit/sgp4';
import { dateToJD } from '$lib/format/date';
import { fetchLabels } from '$lib/fetch/position/labels';
import { MinorBucket } from '$lib/fetch/position/minor-columns';
import type { ChunkLoader } from '$lib/fetch/position/chunk';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';

/**
 * Placeholder PositionedBodies from the __global__ object file. If the
 * target's parent isn't yet in `loader.positions` (e.g. a moon-of-asteroid
 * URL-loaded before its host's chunk), recurses up the chain so the target
 * anchors on a real point instead of the SSB — ancestors are appended to the
 * result too. Last entry is the target.
 *
 * A target the catalogue can't place — no orbit of its own, no anchorable
 * parent, a propagator that fails — still comes back, flagged `unplaceable`
 * with a stand-in position: it has a page to open, and nothing frames the
 * camera on it. Only an object with no bundle at all (or a cycle) yields an
 * empty array.
 *
 * Each entry's `zone` is the SBDB-class id (e.g. `"APO"`); null when the body
 * has no SBDB record, in which case the caller falls back to `parentId`-based
 * routing or `bodiesById`.
 */
export async function createPlaceholderBody(
	targetId: string,
	date: Date,
	loader: ChunkLoader,
	visited: Set<string> = new Set()
): Promise<Array<{ body: PositionedBody; zone: string | null }>> {
	if (visited.has(targetId)) {
		console.warn(`createPlaceholderBody: cycle detected at ${targetId} — hiding`);
		return [];
	}
	visited.add(targetId);
	let detail: Awaited<ReturnType<typeof fetchObjectDetail>>;
	try {
		detail = await fetchObjectDetail(targetId);
	} catch {
		console.warn(`createPlaceholderBody: failed to fetch global data for ${targetId} — hiding`);
		return [];
	}
	const global = detail.global;
	if (!global) {
		console.warn(`createPlaceholderBody: no catalogue record for ${targetId} — hiding`);
		return [];
	}
	const zone = global.sbdb?.class ?? null;
	const unplaced = (from?: BodyData) => {
		const unplacedData = from
			? { ...from, unplaceable: true }
			: unplacedBodyDataFromGlobal(targetId, detail);
		if (!unplacedData) return [];
		const body: PositionedBody = {
			data: unplacedData,
			position: [0, 0, 0],
			positionUnknown: true
		};
		return [{ body, zone }];
	};
	const data = bodyDataFromGlobal(targetId, detail);
	if (!data) return unplaced();
	const satrec = data.satrec;
	const isParabolic = data.q != null;

	const ancestors: Array<{ body: PositionedBody; zone: string | null }> = [];
	let parentPos = loader.positions.get(data.parentId);
	if (!parentPos) {
		// Recurse so e.g. a moon-of-asteroid can anchor on a placeholder of its
		// host, registering the parent's position for siblings to share. Hide
		// rather than fall back to SSB, which would place the body at the Sun.
		const parentChain = await createPlaceholderBody(data.parentId, date, loader, visited);
		const parentEntry = parentChain[parentChain.length - 1];
		if (!parentEntry || parentEntry.body.positionUnknown) {
			// Nothing to anchor on: the target keeps its page, not a place.
			return [...parentChain, ...unplaced(data)];
		}
		parentPos = parentEntry.body.position;
		loader.positions.set(data.parentId, parentPos);
		ancestors.push(...parentChain);
	}
	const offset = satrec
		? sgp4PositionScene(satrec, dateToJD(date))
		: isParabolic
			? parabolicToPosition(data, date)
			: orbitalElementsToPosition(data, date);
	if (!offset) {
		console.warn(`Failed to compute position for ${targetId} (e=${data.e})`);
		return [...ancestors, ...unplaced(data)];
	}
	const position: [number, number, number] = [
		parentPos[0] + offset[0],
		parentPos[1] + offset[1],
		parentPos[2] + offset[2]
	];

	ancestors.push({
		body: { data, position, orbitElements: data, orbitCenter: parentPos },
		zone
	});
	return ancestors;
}

/** Stream a single target into the running scene if absent — the in-session
 *  equivalent of {@link loadScene}'s URL-target placeholder pass (no reload). */
export async function ensureTargetStreamed(
	ctx: ContextManager,
	targetId: string,
	date: Date,
	loader: ChunkLoader
): Promise<void> {
	if (ctx.getBody(targetId)) return;
	const placeholders = await createPlaceholderBody(targetId, date, loader);
	if (placeholders.length === 0) return;

	const labels = await fetchLabels();
	const asteroidBucket = (zone: string): MinorBucket => {
		let b = ctx.bodies.asteroidBodiesByZone.get(zone);
		if (!b) ctx.bodies.asteroidBodiesByZone.set(zone, (b = new MinorBucket(labels)));
		return b;
	};
	const spacecraftBucket = (key: string): Map<string, PositionedBody> => {
		let b = ctx.bodies.spacecraftByParent.get(key);
		if (!b) ctx.bodies.spacecraftByParent.set(key, (b = new Map()));
		return b;
	};
	const added: string[] = [];

	for (let i = 0; i < placeholders.length; i++) {
		const { body, zone } = placeholders[i];
		if (ctx.getBody(body.data.id)) continue;
		const type = body.data.objectType;
		if (body.data.unplaceable) {
			// Nowhere to route it: the zone buckets and spacecraft groups are
			// keyed by a place this body doesn't have.
			ctx.bodies.addBodies([body]);
			added.push(body.data.id);
			continue;
		}
		const parentEntry = i > 0 ? placeholders[i - 1] : null;
		const resolvedZone =
			type === ObjectType.MOON && parentEntry && isAsteroid(parentEntry.body.data.objectType)
				? 'small_body_moons'
				: zone;
		if (type === ObjectType.SPACECRAFT || type === ObjectType.DEBRIS) {
			const key = body.data.parentId;
			spacecraftBucket(key).set(body.data.id, body);
			ctx.bodies.dirtySpacecraftGroups.add(key);
			added.push(body.data.id);
		} else if (resolvedZone) {
			asteroidBucket(resolvedZone).addPlaceholder(body);
			ctx.bodies.dirtyAsteroidZones.add(resolvedZone);
			added.push(body.data.id);
		} else {
			ctx.bodies.addBodies([body]);
		}
		ctx.credits.recordOrbitSources([body]);
	}

	// Re-wrap the outer Maps so reactive observers see a new ref, then notify the
	// promotion registry so the freshly-added bodies get a visual representation.
	ctx.bodies.asteroidBodiesByZone = new Map(ctx.bodies.asteroidBodiesByZone);
	ctx.bodies.spacecraftByParent = new Map(ctx.bodies.spacecraftByParent);
	ctx.bodies.minorBodyVersion++;
	if (added.length > 0) ctx.bodies.notifyBodiesAdded(added);
}

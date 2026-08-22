/**
 * Columnar store for one minor-body group (asteroid zone / spacecraft parent).
 * Holds the parsed element chunks and serves two needs: {@link buildWorkerGroups}
 * fills the worker SoA straight from the chunk views (the bulk dots, no per-body
 * object), and {@link get} materializes a `PositionedBody` on demand for the few
 * bodies that become objects (click / promotion / detail). Drop-in for the old
 * `Map<string, PositionedBody>` bucket: `size`/`has`/`get`/`values`/`ids`.
 */

import { Color } from 'three';
import type { ElementColumns } from '$lib/fetch/position/elements/parse';
import type { LabelMap } from '$lib/fetch/position/labels';
import type { PositionedBody } from '$lib/types/objects';
import { materializeBodyData, fillOrbitColumnRow } from '$lib/fetch/position/elements/row';
import { allocColumns, type OrbitColumns } from '$lib/math/orbit/soa';
import { resolveBodyColor } from '$lib/utils';
import { MIN_BODIES_PER_BUCKET, hashString } from '$lib/math/orbit/partition';
import { yieldToMain } from '$lib/yield';

/** One worker-bound subgroup: the SoA to solve (KIND_SKIP rows included —
 *  `writePositions` packs survivors to the front), plus per-vertex `colors`
 *  for spacecraft (null for asteroid zones). */
export interface WorkerGroup {
	cols: OrbitColumns;
	colors: Float32Array | null;
	/** Body id per SoA row (KIND_SKIP rows included), so a GPU pick's global
	 *  pick-id (`cols.pickBase + row`) resolves back to a body. */
	ids: string[];
}

/** Integer hash for numeric-id partitioning — avoids building the id string. */
function mixId(id: number): number {
	let h = id >>> 0;
	h = Math.imul(h ^ (h >>> 16), 0x45d9f3b);
	h = Math.imul(h ^ (h >>> 16), 0x45d9f3b);
	return (h ^ (h >>> 16)) >>> 0;
}

export class MinorBucket {
	private readonly chunks: ElementColumns[] = [];
	/** id → (chunk, row). Latest chunk wins on collision (hot-reload). */
	private readonly rowOf = new Map<string, { c: number; i: number }>();
	private readonly cache = new Map<string, PositionedBody>();
	/** URL-loaded placeholders: full bodies whose ref the renderer may already
	 *  hold (promoted mesh), so `addChunk` reconciles their `data` in place. */
	private readonly placeholders = new Map<string, PositionedBody>();

	/** Prefix for column rows' parent-id strings; set from zone metadata on
	 *  `addChunk`, default for a placeholder-seeded bucket. */
	parentIdType = 'naif';

	constructor(private readonly labels: LabelMap) {}

	/** Ingest one parsed chunk; returns the ids new to this bucket. `keep` (the
	 *  Earth-sat group filter) indexes only its members. */
	addChunk(cols: ElementColumns, parentIdType: string, keep?: Set<string> | null): string[] {
		this.parentIdType = parentIdType;
		const c = this.chunks.length;
		this.chunks.push(cols);
		const added: string[] = [];
		for (let i = 0; i < cols.rowCount; i++) {
			const id = cols.idMap.get(i);
			if (id === undefined) continue;
			if (keep && !keep.has(id)) continue;
			if (!this.rowOf.has(id)) added.push(id);
			this.rowOf.set(id, { c, i });
			const ph = this.placeholders.get(id);
			if (ph) {
				const fresh = materializeBodyData(cols, i, this.labels, this.parentIdType);
				if (fresh) Object.assign(ph.data, fresh);
			}
		}
		return added;
	}

	/** Register a URL-loaded placeholder (already announced when created). */
	addPlaceholder(body: PositionedBody): void {
		this.placeholders.set(body.data.id, body);
		this.cache.set(body.data.id, body);
	}

	get size(): number {
		let extra = 0;
		for (const id of this.placeholders.keys()) if (!this.rowOf.has(id)) extra++;
		return this.rowOf.size + extra;
	}

	has(id: string): boolean {
		return this.rowOf.has(id) || this.placeholders.has(id);
	}

	*ids(): IterableIterator<string> {
		yield* this.rowOf.keys();
		for (const id of this.placeholders.keys()) if (!this.rowOf.has(id)) yield id;
	}

	/** Materialize (and cache) the body for one id. Position starts at the
	 *  origin, flagged as a stand-in until `refreshMinorBodyPosition` places it
	 *  at pick/promotion time — framing the origin would read as a jump to the
	 *  barycentre. */
	get(id: string): PositionedBody | undefined {
		const cached = this.cache.get(id);
		if (cached) return cached;
		const ref = this.rowOf.get(id);
		if (!ref) return undefined;
		const data = materializeBodyData(this.chunks[ref.c], ref.i, this.labels, this.parentIdType);
		if (!data) return undefined;
		const body: PositionedBody = { data, position: [0, 0, 0], positionUnknown: true };
		this.cache.set(id, body);
		return body;
	}

	*values(): IterableIterator<PositionedBody> {
		for (const id of this.ids()) {
			const b = this.get(id);
			if (b) yield b;
		}
	}

	/** Cloud color for an asteroid zone — painted from one row's type. */
	cloudColor(): string {
		const first = this.chunks.find((c) => c.rowCount > 0);
		if (!first) return '#888888';
		const data = materializeBodyData(first, 0, this.labels, this.parentIdType);
		return data ? resolveBodyColor(data) : '#888888';
	}

	/**
	 * Partition rows across `workerCount` subgroups by numeric-id hash and fill
	 * each subgroup's `OrbitColumns` from the chunk views (mirrors the split
	 * rule of {@link partitionForWorkers}). `skip` drops promoted ids;
	 * `withColors` builds per-vertex colors (spacecraft). Time-sliced — the main
	 * belt is >1M rows, so a synchronous build would block for hundreds of ms.
	 */
	async buildWorkerGroups(
		name: string,
		workerCount: number,
		skip: Set<string>,
		withColors: boolean
	): Promise<{ groups: WorkerGroup[]; baseWorker: number }> {
		const total = this.rowOf.size;
		const k = total >= workerCount * MIN_BODIES_PER_BUCKET ? workerCount : 1;

		// Pass 1: snapshot row order (stable — rowOf is append-only, and the order
		// is the subgroups' vertex order) + bucket assignment + counts.
		const refs: { c: number; i: number }[] = [];
		const bucketOf: number[] = [];
		const counts = new Array<number>(k).fill(0);
		let sliceStart = performance.now();
		for (const ref of this.rowOf.values()) {
			if (refs.length % 16384 === 0 && performance.now() - sliceStart > 6) {
				await yieldToMain();
				sliceStart = performance.now();
			}
			const b = k === 1 ? 0 : mixId(this.chunks[ref.c].id[ref.i]) % k;
			refs.push(ref);
			bucketOf.push(b);
			counts[b]++;
		}

		const groups: WorkerGroup[] = [];
		for (let b = 0; b < k; b++) {
			const cols = allocColumns(counts[b]);
			cols.applyFlagFilter = false;
			groups.push({
				cols,
				colors: withColors ? new Float32Array(counts[b] * 3) : null,
				ids: new Array<string>(counts[b])
			});
		}

		// Pass 2: fill each subgroup, widening its validity window across rows.
		const starts = new Array<number>(k).fill(Infinity);
		const ends = new Array<number>(k).fill(-Infinity);
		const writeIdx = new Array<number>(k).fill(0);
		const tmp = withColors ? new Color() : null;
		sliceStart = performance.now();
		for (let r = 0; r < refs.length; r++) {
			if ((r & 16383) === 16383 && performance.now() - sliceStart > 6) {
				await yieldToMain();
				sliceStart = performance.now();
			}
			const { c, i } = refs[r];
			const cols = this.chunks[c];
			const b = bucketOf[r];
			const g = groups[b];
			const outIdx = writeIdx[b]++;
			const id = cols.idMap.get(i); // needed for both the skip test and pick-id mapping
			g.ids[outIdx] = id ?? '';
			if (fillOrbitColumnRow(cols, i, g.cols, outIdx, id, skip)) {
				if (cols.validityStart < starts[b]) starts[b] = cols.validityStart;
				if (cols.validityEnd > ends[b]) ends[b] = cols.validityEnd;
			}
			if (g.colors && tmp) {
				const data = materializeBodyData(cols, i, this.labels, this.parentIdType);
				tmp.set(data ? resolveBodyColor(data) : '#ffffff');
				g.colors[outIdx * 3] = tmp.r;
				g.colors[outIdx * 3 + 1] = tmp.g;
				g.colors[outIdx * 3 + 2] = tmp.b;
			}
		}
		for (let b = 0; b < k; b++) {
			groups[b].cols.validityStart = starts[b] === Infinity ? -Infinity : starts[b];
			groups[b].cols.validityEnd = ends[b] === -Infinity ? Infinity : ends[b];
		}
		return { groups, baseWorker: hashString(name) % workerCount };
	}
}

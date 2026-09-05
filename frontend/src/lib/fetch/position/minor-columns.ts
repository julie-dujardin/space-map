/**
 * Columnar store for one minor-body group (asteroid zone / spacecraft parent).
 * Holds the parsed element chunks and serves two needs: {@link buildWorkerGroups}
 * fills the worker SoA straight from the chunk views (the bulk dots, no per-body
 * object), and {@link get} materializes a `PositionedBody` on demand for the few
 * bodies that become objects (click / promotion / detail). Drop-in for the old
 * `Map<string, PositionedBody>` bucket: `size`/`has`/`get`/`values`/`ids`.
 */

import { Color } from 'three';
import { rowId, rowKey, type ElementColumns } from '$lib/fetch/position/elements/parse';
import { idToKey, keyToId, NO_KEY, type ObjectKey } from '$lib/fetch/position/object-key';
import type { LabelMap } from '$lib/fetch/position/labels';
import type { PositionedBody } from '$lib/types/objects';
import { materializeBodyData, fillOrbitColumnRow } from '$lib/fetch/position/elements/row';
import { allocColumns, type OrbitColumns } from '$lib/math/orbit/soa';
import { resolveBodyColor } from '$lib/utils';
import { MIN_BODIES_PER_BUCKET, hashString } from '$lib/math/orbit/partition';
import { yieldToMain } from '$lib/yield';
import { RefIndex } from '$lib/fetch/position/ref-index';

/** One worker-bound subgroup: the SoA to solve (KIND_SKIP rows included —
 *  `writePositions` packs survivors to the front), plus per-vertex `colors`
 *  for spacecraft (null for asteroid zones). */
export interface WorkerGroup {
	cols: OrbitColumns;
	colors: Float32Array | null;
	/** Body key per SoA row (KIND_SKIP rows included), so a GPU pick's global
	 *  pick-id (`cols.pickBase + row`) resolves back to a body. */
	keys: Float64Array;
}

/** Rows per chunk the packed row reference allows; a reference is `chunk * ROW_STRIDE + row`. */
/** Row references pack `chunk * ROW_STRIDE + row` into a uint32 in
 *  {@link RefIndex}: 2^20 rows per chunk leaves room for 4095 chunks. */
const ROW_STRIDE = 2 ** 20;

/** Rows walked between yield checks in the time-sliced passes. */
const SLICE_ROWS = 4096;
const SLICE_MS = 6;

/** Integer hash for numeric-id partitioning — avoids building the id string. */
function mixId(id: number): number {
	let h = id >>> 0;
	h = Math.imul(h ^ (h >>> 16), 0x45d9f3b);
	h = Math.imul(h ^ (h >>> 16), 0x45d9f3b);
	return (h ^ (h >>> 16)) >>> 0;
}

export class MinorBucket {
	private readonly chunks: ElementColumns[] = [];
	/** key → packed (chunk, row), see {@link ROW_STRIDE}. Latest chunk wins on
	 *  collision (hot-reload), whichever ingest pass writes last. */
	private readonly rowOf = new RefIndex((ref) => this.keyOfRef(ref));
	private readonly cache = new Map<string, PositionedBody>();
	/** URL-loaded placeholders: full bodies whose ref the renderer may already
	 *  hold (promoted mesh), so `addChunk` reconciles their `data` in place. */
	private readonly placeholders = new Map<string, PositionedBody>();

	/** Prefix for column rows' parent-id strings; set from zone metadata on
	 *  `addChunk`, default for a placeholder-seeded bucket. */
	parentIdType = 'naif';

	constructor(private readonly labels: LabelMap) {}

	/** Ingest one parsed chunk; resolves with how many rows were new. `keep`
	 *  (the Earth-sat group filter) indexes only its members. Time-sliced: the
	 *  main belt is >1M rows, and one synchronous pass over a part blocks
	 *  input for hundreds of milliseconds on a slow phone. */
	async addChunk(
		cols: ElementColumns,
		parentIdType: string,
		keep?: ReadonlySet<ObjectKey> | null
	): Promise<number> {
		this.parentIdType = parentIdType;
		if (cols.rowCount >= ROW_STRIDE)
			throw new Error(`MinorBucket: chunk too large (${cols.rowCount} rows)`);
		const c = this.chunks.length;
		this.chunks.push(cols);
		let added = 0;
		const hasPlaceholders = this.placeholders.size > 0;
		let sliceStart = performance.now();
		for (let i = 0; i < cols.rowCount; i++) {
			if (i % SLICE_ROWS === SLICE_ROWS - 1 && performance.now() - sliceStart > SLICE_MS) {
				await yieldToMain();
				sliceStart = performance.now();
			}
			const key = rowKey(cols, i);
			if (key === NO_KEY || (keep && !keep.has(key))) continue;
			if (this.rowOf.set(key, c * ROW_STRIDE + i, (prev) => Math.floor(prev / ROW_STRIDE) <= c)) {
				added++;
			}
			if (hasPlaceholders) {
				const id = rowId(cols, i);
				const ph = id === null ? undefined : this.placeholders.get(id);
				if (ph) {
					const fresh = materializeBodyData(cols, i, this.labels, this.parentIdType);
					if (fresh) Object.assign(ph.data, fresh);
				}
			}
		}
		return added;
	}

	/** Register a URL-loaded placeholder (already announced when created). */
	addPlaceholder(body: PositionedBody): void {
		this.placeholders.set(body.data.id, body);
		this.cache.set(body.data.id, body);
	}

	private keyOfRef(ref: number): ObjectKey {
		const c = Math.floor(ref / ROW_STRIDE);
		return rowKey(this.chunks[c], ref - c * ROW_STRIDE);
	}

	get size(): number {
		let extra = 0;
		for (const id of this.placeholders.keys()) if (!this.hasRow(id)) extra++;
		return this.rowOf.size + extra;
	}

	private hasRow(id: string): boolean {
		const key = idToKey(id);
		return key !== null && this.rowOf.has(key);
	}

	has(id: string): boolean {
		return this.hasRow(id) || this.placeholders.has(id);
	}

	hasKey(key: ObjectKey): boolean {
		if (this.rowOf.has(key)) return true;
		if (this.placeholders.size === 0) return false;
		const id = keyToId(key);
		return id !== null && this.placeholders.has(id);
	}

	*ids(): IterableIterator<string> {
		for (const key of this.rowOf.keys()) {
			const id = keyToId(key);
			if (id !== null) yield id;
		}
		for (const id of this.placeholders.keys()) if (!this.hasRow(id)) yield id;
	}

	*keys(): IterableIterator<ObjectKey> {
		yield* this.rowOf.keys();
		for (const id of this.placeholders.keys()) {
			const key = idToKey(id);
			if (key !== null && !this.rowOf.has(key)) yield key;
		}
	}

	/** Materialize (and cache) the body for one id. Position starts at the
	 *  origin, flagged as a stand-in until `refreshMinorBodyPosition` places it
	 *  at pick/promotion time — framing the origin would read as a jump to the
	 *  barycentre. */
	get(id: string): PositionedBody | undefined {
		const cached = this.cache.get(id);
		if (cached) return cached;
		const key = idToKey(id);
		const ref = key === null ? undefined : this.rowOf.get(key);
		if (ref === undefined) return undefined;
		const c = Math.floor(ref / ROW_STRIDE);
		const data = materializeBodyData(
			this.chunks[c],
			ref - c * ROW_STRIDE,
			this.labels,
			this.parentIdType
		);
		if (!data) return undefined;
		const body: PositionedBody = { data, position: [0, 0, 0], positionUnknown: true };
		this.cache.set(id, body);
		return body;
	}

	getKey(key: ObjectKey): PositionedBody | undefined {
		const id = keyToId(key);
		return id === null ? undefined : this.get(id);
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
		skip: ReadonlySet<ObjectKey>,
		withColors: boolean
	): Promise<{ groups: WorkerGroup[]; baseWorker: number }> {
		const total = this.rowOf.size;
		const k = total >= workerCount * MIN_BODIES_PER_BUCKET ? workerCount : 1;

		// Pass 1: snapshot row order (stable — rowOf is append-only, and the order
		// is the subgroups' vertex order) + bucket assignment + counts. An
		// ingest still running keeps appending; the snapshot stops at `total`
		// and the zone's dirty mark brings the rest in on the next pass.
		const refs = new Float64Array(total);
		const bucketOf = new Uint8Array(total);
		const counts = new Array<number>(k).fill(0);
		let n = 0;
		let sliceStart = performance.now();
		for (const ref of this.rowOf.values()) {
			if (n === total) break;
			if (n % 16384 === 0 && performance.now() - sliceStart > 6) {
				await yieldToMain();
				sliceStart = performance.now();
			}
			const c = Math.floor(ref / ROW_STRIDE);
			const b = k === 1 ? 0 : mixId(this.chunks[c].id[ref - c * ROW_STRIDE]) % k;
			refs[n] = ref;
			bucketOf[n] = b;
			counts[b]++;
			n++;
		}

		const groups: WorkerGroup[] = [];
		for (let b = 0; b < k; b++) {
			const cols = allocColumns(counts[b]);
			cols.applyFlagFilter = false;
			groups.push({
				cols,
				colors: withColors ? new Float32Array(counts[b] * 3) : null,
				keys: new Float64Array(counts[b]).fill(NO_KEY)
			});
		}

		// Pass 2: fill each subgroup, widening its validity window across rows.
		const starts = new Array<number>(k).fill(Infinity);
		const ends = new Array<number>(k).fill(-Infinity);
		const writeIdx = new Array<number>(k).fill(0);
		const tmp = withColors ? new Color() : null;
		sliceStart = performance.now();
		for (let r = 0; r < n; r++) {
			if ((r & 16383) === 16383 && performance.now() - sliceStart > 6) {
				await yieldToMain();
				sliceStart = performance.now();
			}
			const ref = refs[r];
			const c = Math.floor(ref / ROW_STRIDE);
			const i = ref - c * ROW_STRIDE;
			const cols = this.chunks[c];
			const b = bucketOf[r];
			const g = groups[b];
			const outIdx = writeIdx[b]++;
			const key = rowKey(cols, i);
			g.keys[outIdx] = key;
			if (fillOrbitColumnRow(cols, i, g.cols, outIdx, key, skip)) {
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

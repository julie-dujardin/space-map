/**
 * Per-body IAU nomenclature loader: fetches the SMNF positions blob and the
 * canonical-metadata JSON in parallel, then joins them by `feature_id`.
 *
 * Callers should gate on `objectGlobal.has_nomenclature` before calling — a
 * body without features ships no files, and we'd hit a guaranteed 404. A 404
 * here is treated as "no features" (empty array) to keep the call site simple
 * if the gate is ever bypassed.
 */

import { DATA_BASE } from '$lib/fetch/data-base';
import { parseNomenclature, type NomenclatureRecord } from '$lib/fetch/nomenclature/parse';

interface NomenclatureGlobalEntry {
	name?: string;
	approval_date?: string;
	origin?: string;
}

export interface NomenclatureFeature extends NomenclatureRecord {
	name: string;
	approvalDate?: string;
	origin?: string;
}

const cache = new Map<string, Promise<NomenclatureFeature[]>>();

async function fetchPositions(bodyId: string): Promise<NomenclatureRecord[]> {
	const url = `${DATA_BASE}/v1/nomenclature/positions/${bodyId}.bin.gz`;
	const res = await fetch(url);
	if (!res.ok) {
		if (res.status === 404) return [];
		throw new Error(`fetchPositions: ${url} returned ${res.status} ${res.statusText}`);
	}
	const ds = new DecompressionStream('gzip');
	const buffer = await new Response(res.body!.pipeThrough(ds)).arrayBuffer();
	return parseNomenclature(buffer);
}

async function fetchGlobal(bodyId: string): Promise<Record<string, NomenclatureGlobalEntry>> {
	const url = `${DATA_BASE}/v1/nomenclature/__global__/${bodyId}.json.gz`;
	const res = await fetch(url);
	if (!res.ok) {
		if (res.status === 404) return {};
		throw new Error(`fetchNomenclatureGlobal: ${url} returned ${res.status} ${res.statusText}`);
	}
	const ds = new DecompressionStream('gzip');
	return (await new Response(res.body!.pipeThrough(ds)).json()) as Record<
		string,
		NomenclatureGlobalEntry
	>;
}

export function fetchBodyNomenclature(bodyId: string): Promise<NomenclatureFeature[]> {
	let p = cache.get(bodyId);
	if (!p) {
		p = (async () => {
			const [records, meta] = await Promise.all([fetchPositions(bodyId), fetchGlobal(bodyId)]);
			return records.map((rec) => {
				const entry = meta[String(rec.featureId)] ?? {};
				return {
					...rec,
					name: entry.name ?? `Feature ${rec.featureId}`,
					approvalDate: entry.approval_date,
					origin: entry.origin
				};
			});
		})();
		cache.set(bodyId, p);
	}
	return p;
}

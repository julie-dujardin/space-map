/**
 * Per-body IAU nomenclature loader: fetches the SMNF positions blob and the
 * matching per-language label file in parallel, joining them by *position
 * index* — line i of `labels/{lang}/{bodyId}.txt.gz` names record i of
 * `positions/{bodyId}.bin.gz`. The writer pins that order invariant
 * (`test_labels_order_matches_positions_order`).
 *
 * Callers should gate on `objectGlobal.has_nomenclature` before calling — a
 * body without features ships no files, and we'd hit a guaranteed 404. A 404
 * here is treated as "no features" (empty array) to keep the call site simple
 * if the gate is ever bypassed.
 */

import { getLocale } from '$lib/paraglide/runtime.js';
import { DATA_BASE } from '$lib/fetch/data-base';
import { parseNomenclature, type NomenclatureRecord } from '$lib/fetch/nomenclature/parse';

export interface NomenclatureFeature extends NomenclatureRecord {
	name: string;
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

async function fetchLabels(bodyId: string, lang: string): Promise<string[]> {
	const url = `${DATA_BASE}/v1/nomenclature/labels/${lang}/${bodyId}.txt.gz`;
	const res = await fetch(url);
	if (!res.ok) {
		if (res.status === 404) return [];
		throw new Error(`fetchNomenclatureLabels: ${url} returned ${res.status} ${res.statusText}`);
	}
	const ds = new DecompressionStream('gzip');
	const text = await new Response(res.body!.pipeThrough(ds)).text();
	// "".split("\n") returns [""] (one empty line) — empty bodies stay empty.
	return text === '' ? [] : text.split('\n');
}

export function fetchBodyNomenclature(
	bodyId: string,
	lang: string = getLocale()
): Promise<NomenclatureFeature[]> {
	const key = `${bodyId}:${lang}`;
	let p = cache.get(key);
	if (!p) {
		p = (async () => {
			const [records, labels] = await Promise.all([
				fetchPositions(bodyId),
				fetchLabels(bodyId, lang)
			]);
			return records.map((rec, i) => ({
				...rec,
				name: labels[i] ?? `Feature ${rec.featureId}`
			}));
		})();
		cache.set(key, p);
	}
	return p;
}

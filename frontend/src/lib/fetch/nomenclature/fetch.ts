/**
 * Per-body IAU nomenclature loader: fetches the SMNF positions blob and the
 * matching per-language label file in parallel, joining them by *position
 * index* — line i of `labels/{lang}/{bodyId}.txt.gz` names record i of
 * `positions/{bodyId}.bin.gz`. Callers should gate on
 * `objectGlobal.has_nomenclature` first, since a body with no features ships
 * no files; a 404 here still degrades to an empty array.
 */

import { getLocale } from '$lib/host';
import { versionedUrl } from '$lib/fetch/data-base';
import { gunzip } from '$lib/fetch/gz';
import { parseNomenclature, type NomenclatureRecord } from '$lib/fetch/nomenclature/parse';

export interface NomenclatureFeature extends NomenclatureRecord {
	name: string;
}

const cache = new Map<string, Promise<NomenclatureFeature[]>>();

async function fetchPositions(bodyId: string): Promise<NomenclatureRecord[]> {
	const url = versionedUrl(`/v1/nomenclature/positions/${bodyId}.bin.gz`, 'nomenclature');
	const res = await fetch(url);
	if (!res.ok) {
		if (res.status === 404) return [];
		throw new Error(`fetchPositions: ${url} returned ${res.status} ${res.statusText}`);
	}
	return parseNomenclature(await gunzip(res).arrayBuffer());
}

/** The label file of a body, as text; empty when it has none. */
async function fetchLabelText(bodyId: string, lang: string): Promise<string> {
	const url = versionedUrl(`/v1/nomenclature/labels/${lang}/${bodyId}.txt.gz`, 'nomenclature');
	const res = await fetch(url);
	if (!res.ok) {
		if (res.status === 404) return '';
		throw new Error(`fetchNomenclatureLabels: ${url} returned ${res.status} ${res.statusText}`);
	}
	return gunzip(res).text();
}

/** The records with their names: line i of the label file names record i. */
export function nameFeatures(
	records: NomenclatureRecord[],
	labelText: string
): NomenclatureFeature[] {
	// "".split("\n") returns [""] (one empty line) — empty bodies stay empty.
	const labels = labelText === '' ? [] : labelText.split('\n');
	return records.map((rec, i) => ({ ...rec, name: labels[i] ?? `Feature ${rec.featureId}` }));
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
				fetchLabelText(bodyId, lang)
			]);
			return nameFeatures(records, labels);
		})();
		cache.set(key, p);
		// Evict on rejection so a transient failure doesn't leave the body's
		// features missing for the session.
		p.catch(() => {
			if (cache.get(key) === p) cache.delete(key);
		});
	}
	return p;
}

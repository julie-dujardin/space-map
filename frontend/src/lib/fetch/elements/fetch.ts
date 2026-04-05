/**
 * Fetch per-language element labels (array index → localized name) and object file flags.
 */

import { getLocale } from '$lib/paraglide/runtime.js';
import { elementIdsUrl, elementLabelsUrl } from '$lib/fetch/elements/constants';

/** ASCII Unit Separator — delimiter between flag and name in label files. */
const US = '\x1f';

export interface LabelData {
	labels: Map<number, string>;
	/** 0 = no object file, 1 = localized file, 2 = English fallback file */
	flags: Map<number, number>;
}

async function fetchTextMap(url: string): Promise<Map<number, string>> {
	const res = await fetch(url);
	if (!res.ok) throw new Error(`Failed to fetch ${url}: ${res.status}`);
	return new Map((await res.text()).split('\n').map((v, i) => [i, v]));
}

export function fetchIds(zone: string, zoom: number, part: number): Promise<Map<number, string>> {
	return fetchTextMap(elementIdsUrl(zone, zoom, part));
}

export async function fetchLabels(zone: string, zoom: number, part: number): Promise<LabelData> {
	const url = elementLabelsUrl(getLocale(), zone, zoom, part);
	const res = await fetch(url);
	if (!res.ok) throw new Error(`Failed to fetch ${url}: ${res.status}`);
	const labels = new Map<number, string>();
	const flags = new Map<number, number>();
	const lines = (await res.text()).split('\n');
	for (let i = 0; i < lines.length; i++) {
		const sepIdx = lines[i].indexOf(US);
		if (sepIdx === -1) {
			flags.set(i, 0);
			labels.set(i, lines[i]);
		} else {
			flags.set(i, parseInt(lines[i].slice(0, sepIdx), 10));
			labels.set(i, lines[i].slice(sepIdx + 1));
		}
	}
	return { labels, flags };
}

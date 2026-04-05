/**
 * Fetch per-language element labels (array index → localized name).
 */

import { getLocale } from '$lib/paraglide/runtime.js';
import { elementIdsUrl, elementLabelsUrl } from '$lib/fetch/elements/constants';

async function fetchTextMap(url: string): Promise<Map<number, string>> {
	const res = await fetch(url);
	if (!res.ok) throw new Error(`Failed to fetch ${url}: ${res.status}`);
	return new Map((await res.text()).split('\n').map((v, i) => [i, v]));
}

export function fetchIds(zone: string, zoom: number, part: number): Promise<Map<number, string>> {
	return fetchTextMap(elementIdsUrl(zone, zoom, part));
}

export function fetchLabels(
	zone: string,
	zoom: number,
	part: number
): Promise<Map<number, string>> {
	return fetchTextMap(elementLabelsUrl(getLocale(), zone, zoom, part));
}

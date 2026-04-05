/**
 * Fetch per-language element labels (array index → localized name).
 */

import { getLocale } from '$lib/paraglide/runtime.js';
import { elementIdsUrl, elementLabelsUrl } from '$lib/fetch/elements/constants';

export async function fetchIds(
	zone: string,
	zoom: number,
	part: number
): Promise<Map<number, string>> {
	const lang = getLocale();

	const res = await fetch(elementIdsUrl(zone, zoom, part));
	if (!res.ok) throw new Error(`Failed to fetch labels for ${lang}: ${res.status}`);
	const data = (await res.text()).split('\n');
	return new Map(data.map((id, index) => [index, id]));
}

export async function fetchLabels(
	zone: string,
	zoom: number,
	part: number
): Promise<Map<number, string>> {
	const lang = getLocale();

	const res = await fetch(elementLabelsUrl(lang, zone, zoom, part));
	if (!res.ok) throw new Error(`Failed to fetch labels for ${lang}: ${res.status}`);
	const data = (await res.text()).split('\n');
	return new Map(data.map((id, index) => [index, id]));
}

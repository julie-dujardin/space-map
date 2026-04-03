/**
 * Fetch per-language element labels (array index → localized name).
 */

import { getLocale } from '$lib/paraglide/runtime.js';
import { BASE_ELEMENT_PATH, BASE_LABEL_PATH } from '$lib/fetch/elements/constants';

export async function fetchIds(
	zone: string,
	zoom: number,
	part: number
): Promise<Map<number, string>> {
	const lang = getLocale();

	const res = await fetch(`${BASE_ELEMENT_PATH}/${zone}/${zoom}/${part}.txt`);
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

	const res = await fetch(`${BASE_LABEL_PATH}/${lang}/${zone}/${zoom}/${part}.txt`);
	if (!res.ok) throw new Error(`Failed to fetch labels for ${lang}: ${res.status}`);
	const data = (await res.text()).split('\n');
	return new Map(data.map((id, index) => [index, id]));
}

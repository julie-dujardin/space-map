/**
 * Fetch per-language element labels (array index → localized name).
 */

import { getLocale } from '$lib/paraglide/runtime.js';

const BASE_ID_PATH = '/data/v1/elements';
const BASE_LABEL_PATH = '/data/v1/element_labels';

export async function fetchIds(
	context: string,
	zoom: number,
	part: number
): Promise<Map<number, string>> {
	const lang = getLocale();

	const res = await fetch(`${BASE_ID_PATH}/${context}/${zoom}/${part}.txt`);
	if (!res.ok) throw new Error(`Failed to fetch labels for ${lang}: ${res.status}`);
	const data = (await res.text()).split('\n');
	return new Map(data.map((id, index) => [index, id]));
}

export async function fetchLabels(
	context: string,
	zoom: number,
	part: number
): Promise<Map<number, string>> {
	const lang = getLocale();

	const res = await fetch(`${BASE_LABEL_PATH}/${lang}/${context}/${zoom}/${part}.txt`);
	if (!res.ok) throw new Error(`Failed to fetch labels for ${lang}: ${res.status}`);
	const data = (await res.text()).split('\n');
	return new Map(data.map((id, index) => [index, id]));
}

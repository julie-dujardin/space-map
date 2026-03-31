/**
 * Fetch per-language element labels (array index → localized name).
 */

import { getLocale } from '$lib/paraglide/runtime.js';

export async function fetchLabels(lang = getLocale()): Promise<Map<number, string>> {
	const res = await fetch(`/data/v1/element_labels/${lang}.json`);
	if (!res.ok) throw new Error(`Failed to fetch labels for ${lang}: ${res.status}`);
	const data: Record<string, string> = await res.json();
	return new Map(Object.entries(data).map(([k, v]) => [Number(k), v]));
}

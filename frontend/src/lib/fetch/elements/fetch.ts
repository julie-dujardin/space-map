/**
 * Global per-language labels fetcher.
 *
 * Replaces the previous per-chunk `.loc.{lang}.gz` files: there's now one
 * `/v1/labels/{lang}.gz` per language listing only the *promoted* set —
 * planets, dwarf planets, moons, stars, barycenters, Lagrange points, plus
 * the curated extras in `data/src/space_map_data/constants/promoted.py`.
 *
 * The frontend's promoted set is exactly this file's keys; there is no
 * separate hardcoded list.
 */

import { getLocale } from '$lib/paraglide/runtime.js';
import { labelsUrl } from '$lib/fetch/elements/constants';

/** ASCII Unit Separator — delimiter between id and name in label files. */
const US = '\x1f';

export type LabelMap = ReadonlyMap<string, string>;

export function parseLabels(text: string): Map<string, string> {
	const out = new Map<string, string>();
	if (!text) return out;
	for (const line of text.split('\n')) {
		const sep = line.indexOf(US);
		if (sep === -1) {
			// Older/odd line — treat the whole line as an id with empty name.
			if (line) out.set(line, '');
		} else {
			out.set(line.slice(0, sep), line.slice(sep + 1));
		}
	}
	return out;
}

/** Locale switching reloads the page (paraglide default), so a single
 *  in-memory promise per lang is enough — no LRU. */
const labelsByLang = new Map<string, Promise<LabelMap>>();

export async function fetchLabels(lang: string = getLocale()): Promise<LabelMap> {
	let p = labelsByLang.get(lang);
	if (!p) {
		p = (async () => {
			const url = labelsUrl(lang);
			const res = await fetch(url);
			if (!res.ok) throw new Error(`Failed to fetch ${url}: ${res.status}`);
			const ds = new DecompressionStream('gzip');
			const text = await new Response(res.body!.pipeThrough(ds)).text();
			return parseLabels(text);
		})();
		labelsByLang.set(lang, p);
	}
	return p;
}

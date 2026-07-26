/** Range descriptors + slider scale math (display value ↔ position in [0,1]).
 *  Scales: diameter log (~7 decades), inception reverse-log (dense recent
 *  decades), magnitude linear (H is already log and goes negative). */

import type { RangeFacet } from './client';

export type ScaleKind = 'log' | 'linear' | 'revlog';

export interface RangeDef {
	facet: RangeFacet;
	/** i18n key for the label (magnitude has its own; the rest reuse sort labels). */
	labelKey: 'search_sort_size' | 'search_range_magnitude' | 'search_sort_date';
	/** 'km' renders a unit suffix; 'mag'/'year' show the bare number. */
	unit: 'km' | 'mag' | 'year';
	/** Slider domain in display units. */
	lo: number;
	hi: number;
	scale: ScaleKind;
}

// inception `hi` is the current year; other bounds are generous slider
// envelopes — values outside still filter via the number inputs.
export const RANGE_DEFS: RangeDef[] = [
	{
		facet: 'diameter',
		labelKey: 'search_sort_size',
		unit: 'km',
		lo: 0.01,
		hi: 150000,
		scale: 'log'
	},
	{
		facet: 'magnitude',
		labelKey: 'search_range_magnitude',
		unit: 'mag',
		lo: -10,
		hi: 35,
		scale: 'linear'
	},
	{
		// Covers both an object's discovery/launch year and a surface feature's
		// IAU naming year (1935 onwards) — see RANGE_FIELDS.
		facet: 'inception',
		labelKey: 'search_sort_date',
		unit: 'year',
		lo: 1700,
		hi: 2026,
		scale: 'revlog'
	}
];

export function rangeDef(facet: RangeFacet): RangeDef {
	return RANGE_DEFS.find((d) => d.facet === facet)!;
}

const clamp01 = (p: number) => Math.min(1, Math.max(0, p));

/** Display value → slider position in [0,1]. Out-of-domain values clamp. */
export function toPos(def: RangeDef, v: number): number {
	const { lo, hi, scale } = def;
	const c = Math.min(hi, Math.max(lo, v));
	if (scale === 'log') {
		return clamp01((Math.log(c) - Math.log(lo)) / (Math.log(hi) - Math.log(lo)));
	}
	if (scale === 'revlog') {
		const L = Math.log(hi - lo + 1);
		return clamp01(1 - Math.log(hi - c + 1) / L);
	}
	return clamp01((c - lo) / (hi - lo));
}

/** Slider position in [0,1] → a snapped, human-friendly display value. */
export function fromPos(def: RangeDef, p: number): number {
	const { lo, hi, scale } = def;
	const t = clamp01(p);
	if (scale === 'log') {
		return sigFig(Math.exp(Math.log(lo) + t * (Math.log(hi) - Math.log(lo))), 2);
	}
	if (scale === 'revlog') {
		const L = Math.log(hi - lo + 1);
		return Math.round(hi + 1 - Math.exp((1 - t) * L));
	}
	return Math.round((lo + t * (hi - lo)) * 2) / 2; // nearest 0.5
}

/** Round to `n` significant figures (keeps log-scale slider stops tidy). */
function sigFig(v: number, n: number): number {
	if (v === 0) return 0;
	const power = n - Math.ceil(Math.log10(Math.abs(v)));
	const m = 10 ** power;
	return Math.round(v * m) / m;
}

/** Compact magnitudes for the search UI (counts, member tallies). */

/** 1_339_000 → "1.3M", 12_400 → "12K", 940 → "940". */
export function compact(n: number): string {
	if (n >= 1e6) return `${+(n / 1e6).toFixed(1)}M`;
	if (n >= 1e4) return `${Math.round(n / 1e3)}K`;
	if (n >= 1e3) return `${+(n / 1e3).toFixed(1)}K`;
	return n.toLocaleString();
}

/** YYYYMMDD int → calendar year (negative = BCE). */
export function inceptionYear(yyyymmdd: number): number {
	return Math.trunc(yyyymmdd / 10000);
}

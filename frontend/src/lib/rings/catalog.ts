import type { RingFeature, RingFeatureKind } from '$lib/fetch/objects/object-data';
import * as m from '$lib/paraglide/messages.js';

/** A feature plus the parts of its geometry the panel derives once. */
export interface RingRow {
	slug: string;
	feature: RingFeature;
	/** Radial extent in km. Equal bounds for the features published as a bare
	 *  radius (the co-orbital rings, whose "width" nobody has measured). */
	inner: number;
	outer: number;
	children: string[];
}

/** Radial span, collapsing to a point where only a radius is published. */
export function span(feature: RingFeature): [number, number] {
	return [
		feature.inner_radius_km ?? feature.mid_radius_km,
		feature.outer_radius_km ?? feature.mid_radius_km
	];
}

export function buildRows(features: Record<string, RingFeature>): Map<string, RingRow> {
	const rows = new Map<string, RingRow>();
	for (const [slug, feature] of Object.entries(features)) {
		const [inner, outer] = span(feature);
		rows.set(slug, { slug, feature, inner, outer, children: [] });
	}
	for (const row of rows.values()) {
		// A parent that isn't in the map would orphan the row out of the tree
		// entirely, so treat it as a root rather than dropping it.
		const parent = row.feature.parent ? rows.get(row.feature.parent) : undefined;
		if (parent) parent.children.push(row.slug);
	}
	for (const row of rows.values()) {
		row.children.sort((a, b) => rows.get(a)!.inner - rows.get(b)!.inner);
	}
	return rows;
}

export function rootSlugs(rows: Map<string, RingRow>): string[] {
	return [...rows.values()]
		.filter((row) => !row.feature.parent || !rows.has(row.feature.parent))
		.sort((a, b) => a.inner - b.inner)
		.map((row) => row.slug);
}

const KIND_COUNTS: Record<RingFeatureKind, (i: { count: number }) => string> = {
	ring: m.rings_count_ring,
	division: m.rings_count_division,
	gap: m.rings_count_gap,
	ringlet: m.rings_count_ringlet,
	region: m.rings_count_region,
	arc: m.rings_count_arc,
	dust: m.rings_count_dust
};

/** "4 gaps · 4 ringlets" — a set of features by kind rather than a bare total,
 *  since a gap and a ringlet inside it are different things. */
export function kindSummary(rows: Map<string, RingRow>, slugs: string[]): string {
	const counts = new Map<RingFeatureKind, number>();
	for (const slug of slugs) {
		const kind = rows.get(slug)?.feature.kind;
		if (kind) counts.set(kind, (counts.get(kind) ?? 0) + 1);
	}
	return [...counts].map(([kind, count]) => KIND_COUNTS[kind]({ count })).join(' · ');
}

export function childSummary(rows: Map<string, RingRow>, slug: string): string {
	return kindSummary(rows, rows.get(slug)?.children ?? []);
}

/** Optical depth mapped to 0–1 opacity across eight decades.
 *
 * Logarithmic because the range is: Saturn's B ring is τ ≈ 5 and the
 * Janus/Epimetheus ring τ ≈ 1e-7, so a linear ramp would draw everything but
 * the main rings as empty black. Shared with the rendered ring strips, so a
 * measured profile and a catalogued number read at the same darkness. */
export function tauOpacity(tau: number): number {
	if (!(tau > 0)) return 0;
	const decades = (Math.log10(tau) + 8) / 9;
	return 0.06 + 0.94 * Math.min(1, Math.max(0, decades));
}

export function opacity(feature: RingFeature): number {
	const tau = feature.optical_depth?.low;
	if (!tau) return 0.04;
	return tauOpacity(tau);
}

const SUPERSCRIPT: Record<string, string> = {
	'0': '\u2070',
	'1': '\u00b9',
	'2': '\u00b2',
	'3': '\u00b3',
	'4': '\u2074',
	'5': '\u2075',
	'6': '\u2076',
	'7': '\u2077',
	'8': '\u2078',
	'9': '\u2079',
	'-': '\u207b'
};

export function formatOpticalDepth(tau: NonNullable<RingFeature['optical_depth']>): string {
	const digits = (v: number) => {
		if (v === 0) return '0';
		if (v >= 0.01 && v < 10000) return String(v);
		// Gaps and dust bands live at τ ~1e-7; an exponent renders as a real
		// superscript rather than the "1e-7" the platform formatter emits. Two
		// significant figures, because the sources publish them — Uranus' ν ring
		// is 5.6e-6, and one figure would restate it as 6e-6.
		const [mantissa, exponent] = v.toExponential(1).split('e');
		const value = mantissa.replace(/\.0$/, '');
		return `${value}\u00d710${[...exponent].map((c) => SUPERSCRIPT[c] ?? c).join('')}`;
	};
	if (tau.upper_limit) return `< ${digits(tau.low)}`;
	const prefix = tau.approximate ? '≈ ' : '';
	return tau.high !== undefined && tau.high !== tau.low
		? `${digits(tau.low)}–${digits(tau.high)}`
		: `${prefix}${digits(tau.low)}`;
}

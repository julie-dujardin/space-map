/**
 * Representative surface tints for the small-body lineup hero.
 *
 * Small bodies almost never ship a 3D texture (only a handful of visited
 * asteroids do), so the lineup colours each sphere from a heuristic instead of
 * a render. This is a deliberately approximate, MVP-grade classification kept
 * in the frontend rather than the export. Priority, most→least specific:
 *   1. SBDB taxonomic type (`spec`) → a per-complex tint;
 *   2. SBDB `albedo` → lightness nudge on the orbit-class default;
 *   3. the orbit-class / flag / category default;
 *   4. the generic body fallback.
 */

import { DEFAULT_BODY_COLOR } from '$lib/constants';
import { CLASS_SLUG_PREFIX, SMALL_BODY_FLAG_SLUG_PREFIX } from '$lib/fetch/groups/registry';

/** Group slug → the key `smallBodyColor` keys its per-group default on
 *  (OrbitClass name, NEO/PHA flag, or bare category). */
export function groupColorKey(slug: string | undefined): string | undefined {
	if (!slug) return undefined;
	if (slug.startsWith(CLASS_SLUG_PREFIX)) return slug.slice(CLASS_SLUG_PREFIX.length);
	if (slug.startsWith(SMALL_BODY_FLAG_SLUG_PREFIX))
		return slug.slice(SMALL_BODY_FLAG_SLUG_PREFIX.length);
	return slug.replace(/^cat-/, '');
}

/** Tint per taxonomic complex, keyed by the leading letter of the SMASS/Tholen
 *  class. Hues follow the conventional reflectance picture: C-complex dark and
 *  grey, S-complex reddish silicate, V basaltic, D/T/P dark and red. */
function taxonomyTint(spec: string): string | undefined {
	const head = spec.trim().toUpperCase()[0];
	switch (head) {
		case 'C':
		case 'B':
		case 'F':
		case 'G':
			return '#4c4a45'; // carbonaceous — dark neutral grey
		case 'S':
		case 'Q':
		case 'R':
			return '#a8794e'; // silicaceous — reddish tan
		case 'A':
			return '#8f3f2c'; // olivine-rich — strongly red
		case 'V':
			return '#bf9152'; // basaltic (Vesta family) — warm
		case 'K':
		case 'L':
		case 'O':
			return '#9a7351'; // reddish transitional
		case 'M':
			return '#8d877c'; // metallic — neutral grey
		case 'E':
			return '#cabfa8'; // enstatite — bright pale
		case 'P':
			return '#5b4d40'; // primitive — dark red-grey
		case 'X':
			return '#7d766a'; // X-type — neutral grey
		case 'T':
			return '#6f5743'; // dark reddish
		case 'D':
			return '#4e3a30'; // organic-rich — very dark red
		default:
			return undefined;
	}
}

/** Default tint per group, keyed by OrbitClass name, NEO/PHA flag, or category.
 *  Used when a member carries no taxonomy. Inner-belt/near-Earth zones skew
 *  S-type, outer belt and Trojans darker, TNOs/Centaurs red, comets icy. */
const GROUP_TINT: Record<string, string> = {
	// Asteroid belt zones
	IMB: '#a8794e',
	MBA: '#8a6f55',
	OMB: '#5f5447',
	// Near-Earth zones (mostly S/Q)
	ATE: '#a8794e',
	APO: '#a8794e',
	AMO: '#a8794e',
	IEO: '#a8794e',
	// Mars-crossers
	MCA: '#9a7351',
	// Resonant / distant
	TJN: '#5a4a3c', // Jupiter Trojans — dark D/P-rich
	CEN: '#7a4a38', // Centaurs — red
	TNO: '#7a4636', // trans-Neptunian — red
	AST: '#8a6f55',
	// Comet families — icy blue-grey
	COM: '#7d8a90',
	JFc: '#7d8a90',
	HTC: '#7d8a90',
	ETc: '#7d8a90',
	CTc: '#7d8a90',
	PAR: '#7d8a90',
	HYP: '#7d8a90',
	// Flags
	neo: '#a8794e',
	pha: '#a8794e',
	// Top-level categories
	asteroids: '#8a6f55',
	comets: '#7d8a90'
};

function clamp(v: number, lo: number, hi: number): number {
	return Math.max(lo, Math.min(hi, v));
}

/** Nudge a hex colour's lightness toward white (bright) or black (dark) by
 *  albedo, so a textureless zone still reads as light vs dark surfaces. Albedo
 *  ≈ 0.10 is neutral; the belt spans roughly 0.03 (sooty) to 0.5 (fresh). */
function albedoAdjust(hex: string, albedo: number): string {
	const n = parseInt(hex.slice(1), 16);
	const r = (n >> 16) & 0xff;
	const g = (n >> 8) & 0xff;
	const b = n & 0xff;
	const t = clamp((albedo - 0.1) / 0.35, -0.55, 0.55);
	const mix = (c: number) => Math.round(t >= 0 ? c + (255 - c) * t : c * (1 + t));
	const to2 = (c: number) => clamp(c, 0, 255).toString(16).padStart(2, '0');
	return `#${to2(mix(r))}${to2(mix(g))}${to2(mix(b))}`;
}

/** Resolve a lineup sphere colour for a small body. `groupKey` is the group's
 *  OrbitClass name / flag / category (e.g. "MBA", "neo", "asteroids"). */
export function smallBodyColor(
	member: { spec?: string; albedo?: number },
	groupKey: string | undefined
): string {
	if (member.spec) {
		const tint = taxonomyTint(member.spec);
		if (tint) return tint;
	}
	const base = (groupKey && GROUP_TINT[groupKey]) || DEFAULT_BODY_COLOR;
	if (member.albedo != null) return albedoAdjust(base, member.albedo);
	return base;
}

/** One-level "parent" crumb for the drawer header: each focusable resolves to
 *  at most one ancestor (moon→planet, small body→zone, sat→constellation/class,
 *  planet/group→category, category→Solar System root, feature→body). */

import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
import type { ObjectDetailData } from '$lib/fetch/objects/object-data';
import type { GlobalGroupData } from '$lib/fetch/groups/details';
import { ObjectType, type PositionedBody } from '$lib/types/objects';
import { dominantPlanetId } from '$lib/scene/state/bodies.svelte';
import {
	CATEGORY_LABELS,
	CATEGORY_SLUG_PREFIX,
	CAT_ASTEROIDS,
	CAT_COMETS,
	CAT_DWARF_PLANETS,
	CAT_PLANETS,
	CAT_PROBES,
	CAT_SATELLITES,
	CAT_SOLAR_SYSTEM,
	CLASS_SLUG_PREFIX,
	COMET_FAMILY_SLUG_PREFIX,
	CONSTELLATION_SLUG_PREFIX,
	smallBodyCategory
} from '$lib/fetch/groups/registry';
import { classifyEarthOrbit, classNameFromSlug, orbitClassLabel } from '$lib/charts/orbit-zones';
import type { Focusable } from './focusable';
import { urlTypeFromId } from './url';
import { UrlType } from './view';

/** Earth's Object.id — parent of the Satellites category. Mirrors EARTH_ID in
 *  data/constants/earth_sats/featured.py. */
const EARTH_ID = 'naif-399';

/** A moon's real parent: the dominant planet (not its nameless barycenter),
 *  or the host body directly (e.g. the asteroid an asteroid-moon orbits). */
function parentPlanet(
	ctx: ContextManager | undefined,
	parentId: string
): PositionedBody | undefined {
	const planetId = dominantPlanetId(parentId);
	if (planetId) {
		const planet = ctx?.getBody(planetId);
		if (planet) return planet;
	}
	return ctx?.getBody(parentId);
}

export type CrumbTarget =
	| { kind: 'focus'; id: string; name: string; moveCamera?: boolean }
	| { kind: 'group'; slug: string; name: string };

export interface Crumb {
	label: string;
	target: CrumbTarget;
}

function classGroup(className: string): Crumb {
	const label = orbitClassLabel(className);
	return {
		label,
		target: { kind: 'group', slug: `${CLASS_SLUG_PREFIX}${className}`, name: label }
	};
}

function categoryCrumb(slug: string): Crumb {
	const label = CATEGORY_LABELS[slug] ?? slug;
	return { label, target: { kind: 'group', slug, name: label } };
}

/** Title-case a bare constellation slug as a last resort when the localized
 *  detail hasn't supplied a display name. */
function prettifySlug(slug: string): string {
	return slug.charAt(0).toUpperCase() + slug.slice(1);
}

export function parentCrumb(
	focusable: Focusable,
	ctx: ContextManager | undefined,
	detail: ObjectDetailData | null,
	groupGlobal: GlobalGroupData | null
): Crumb | null {
	// A surface feature belongs to the body it sits on.
	if (focusable.kind === 'feature') {
		const b = focusable.body.data;
		return b.name ? { label: b.name, target: { kind: 'focus', id: b.id, name: b.name } } : null;
	}
	// Groups climb to their category; categories climb to the Solar System root.
	if (focusable.kind === 'group') {
		const slug = focusable.slug;
		if (slug.startsWith(CATEGORY_SLUG_PREFIX)) {
			if (slug === CAT_SOLAR_SYSTEM) return null;
			// Satellites' real parent is Earth, not the Solar System root.
			if (slug === CAT_SATELLITES) {
				const name = ctx?.getBody(EARTH_ID)?.data.name ?? 'Earth';
				return { label: name, target: { kind: 'focus', id: EARTH_ID, name } };
			}
			return categoryCrumb(CAT_SOLAR_SYSTEM);
		}
		// A split-comet family is always a comet, regardless of orbit class.
		if (slug.startsWith(COMET_FAMILY_SLUG_PREFIX)) return categoryCrumb(CAT_COMETS);
		const appliesTo = groupGlobal?.applies_to;
		if (appliesTo === 'small_body') {
			const cls = classNameFromSlug(slug);
			return categoryCrumb(cls && smallBodyCategory(cls) === 'comet' ? CAT_COMETS : CAT_ASTEROIDS);
		}
		if (appliesTo === 'earth_sat') return categoryCrumb(CAT_SATELLITES);
		return null;
	}

	const data = focusable.body.data;

	// Dwarf planets climb to their category page; the orbit-class zone stays
	// reachable via the body page's cross-ref tile.
	if (data.objectType === ObjectType.DWARF_PLANET) return categoryCrumb(CAT_DWARF_PLANETS);

	// Planets → the Planets category; the Sun → the Solar System root.
	if (data.objectType === ObjectType.PLANET) return categoryCrumb(CAT_PLANETS);
	if (data.objectType === ObjectType.STAR) return categoryCrumb(CAT_SOLAR_SYSTEM);

	// Moon (planetary or small-body) → its parent (planet, not the barycenter;
	// or the host asteroid). Must precede the URL-type branches: small-body
	// moons carry spkid- ids and would otherwise resolve to an orbit-class zone.
	// Prefer the resident body (localized name, barycenter→planet remap); fall
	// back to the bundle's host name + raw parentId when the host has been
	// culled from the scene, so the crumb doesn't blink out (focus reloads it).
	if (data.objectType === ObjectType.MOON) {
		const parent = parentPlanet(ctx, data.parentId);
		const id = parent?.data.id ?? data.parentId;
		const name = parent?.data.name ?? detail?.global?.parent_name;
		return name ? { label: name, target: { kind: 'focus', id, name } } : null;
	}

	// Split-comet fragment → its parent comet, or the family group when the
	// intact body isn't catalogued. Precedes the small-body branch: a fragment
	// carries a spkid- id and would otherwise resolve to its orbit-class zone.
	const fragmentOf = detail?.global?.fragment_of;
	if (fragmentOf) {
		return fragmentOf.primary_type === 'group'
			? {
					label: fragmentOf.name,
					target: { kind: 'group', slug: fragmentOf.primary_id, name: fragmentOf.name }
				}
			: {
					label: fragmentOf.name,
					// Parent comet's mesh isn't worth flying to — just select it.
					target: {
						kind: 'focus',
						id: fragmentOf.primary_id,
						name: fragmentOf.name,
						moveCamera: false
					}
				};
	}

	// Probe in a mission → the mission group page (primary craft and members
	// alike). Precedes the Probes-category fallback below.
	const missionLink = detail?.global?.mission ?? detail?.global?.part_of_mission;
	if (missionLink) {
		return {
			label: missionLink.name,
			target: { kind: 'group', slug: missionLink.primary_id, name: missionLink.name }
		};
	}

	const urlType = urlTypeFromId(data.id);

	// Earth satellite → its constellation, else its orbit-class zone.
	if (urlType === UrlType.EarthSatellite) {
		const ct = detail?.global?.celestrak;
		if (ct?.constellation_slug) {
			const name = detail?.localized?.constellation?.name ?? prettifySlug(ct.constellation_slug);
			const slug = `${CONSTELLATION_SLUG_PREFIX}${ct.constellation_slug}`;
			return { label: name, target: { kind: 'group', slug, name } };
		}
		if (ct) {
			const classes = classifyEarthOrbit(ct.perigee, ct.apogee, data.i);
			if (classes.length > 0) return classGroup(classes[0]);
		}
		return null;
	}

	// Small body → its SBDB orbit-class zone.
	if (urlType === UrlType.SmallBody) {
		const cls = detail?.global?.sbdb?.class;
		return cls ? classGroup(cls) : null;
	}

	// Probe → the Probes category.
	if (urlType === UrlType.Probe) return categoryCrumb(CAT_PROBES);

	return null;
}

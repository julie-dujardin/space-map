/** One-level "parent" crumb for the drawer header. A page keeps its type on the
 *  way up: a place climbs to a place, a category or group to its parent category,
 *  and cross-ref tiles link the two. Spacecraft are kinds, not places: their
 *  position changes with time, and a crumb should not. Several roots have no
 *  crumb at all. */

import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
import { localizeLink, type ObjectDetailData } from '$lib/fetch/objects/object-data';
import { localName } from '$lib/format/name';
import type { GlobalGroupData } from '$lib/fetch/groups/details';
import { ObjectType } from '$lib/types/objects';
import { dominantPlanetId } from '$lib/constants';
import { extrasolarObjectId } from '$lib/fetch/extrasolar/ids';
import {
	CATEGORY_SLUG_PREFIX,
	CAT_ASTEROIDS,
	CAT_COMETS,
	CAT_DEBRIS,
	CAT_DWARF_PLANETS,
	CAT_MOONS,
	CAT_RING_SYSTEMS,
	CAT_STRUCTURE_ACTIVITY,
	CAT_PLANETS,
	CAT_PLANETARY_SYSTEMS,
	CAT_PROBES,
	CAT_SATELLITES,
	CAT_SOLAR_SYSTEM,
	CAT_SATELLITE_SYSTEMS,
	CAT_SPACECRAFT,
	CLASS_SLUG_PREFIX,
	COMET_FAMILY_SLUG_PREFIX,
	CAT_SURFACE_FEATURES,
	FEATURE_TYPE_SLUG_PREFIX,
	isFamilySlug,
	SKY_CULTURE_SLUG_PREFIX
} from '$lib/fetch/groups/registry';
import { categoryLabel, familyLabel } from '$lib/format/group';
import { classifyEarthOrbit, classNameFromSlug, orbitClassLabel } from '$lib/charts/orbit-zones';
import { isPropertyCollection } from './category-config';
import type { Focusable } from './focusable';
import { urlTypeFromId } from './url';
import { UrlType, type DrawerTab } from './view';

/** The category above a category. One not listed here is a root. */
const PARENT_CATEGORY: Record<string, string> = {
	[CAT_PLANETS]: CAT_PLANETARY_SYSTEMS,
	[CAT_DWARF_PLANETS]: CAT_PLANETARY_SYSTEMS,
	[CAT_ASTEROIDS]: CAT_PLANETARY_SYSTEMS,
	[CAT_COMETS]: CAT_PLANETARY_SYSTEMS,
	[CAT_SATELLITE_SYSTEMS]: CAT_PLANETARY_SYSTEMS,
	[CAT_MOONS]: CAT_SATELLITE_SYSTEMS,
	[CAT_RING_SYSTEMS]: CAT_SATELLITE_SYSTEMS,
	[CAT_SATELLITES]: CAT_SPACECRAFT,
	[CAT_DEBRIS]: CAT_SPACECRAFT,
	[CAT_PROBES]: CAT_SPACECRAFT
};

/** A moon's host page: the planet for a planet's moon (not the barycenter),
 *  else the host body (the asteroid an asteroid moon orbits). The moon's
 *  bundle names it; the resident body with that id names it while the bundle
 *  loads, so the label and the link name one page. A host culled from the
 *  scene keeps its link, so the crumb does not blink out. */
export function moonHost(
	ctx: ContextManager | undefined,
	parentId: string,
	detail: ObjectDetailData | null
): { id: string; name: string | undefined } {
	const id = dominantPlanetId(parentId) ?? parentId;
	return {
		id,
		name:
			detail?.localized?.parent_name ??
			detail?.global?.parent_name ??
			ctx?.getBody(id)?.data.name ??
			undefined
	};
}

export type CrumbTarget =
	| {
			kind: 'focus';
			id: string;
			name: string;
			moveCamera?: boolean;
			tab?: Exclude<DrawerTab, 'overview'>;
	  }
	| { kind: 'group'; slug: string; name: string }
	// Stays on this object and only changes tab — what a tab promoted out of the
	// bar puts in the crumb slot to get back to the object it belongs to.
	| { kind: 'tab'; tab: DrawerTab }
	// Stays on this trip and only puts the trajectory being read back on the list
	// it was chosen from — the planner's own step back, in the slot the object
	// drawer uses for its parent.
	| { kind: 'trip' }
	// A site page outside the map, left to the router: the planner's parent is
	// the Δv map, not a body.
	| { kind: 'page'; href: string };

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
	const label = categoryLabel(slug);
	return { label, target: { kind: 'group', slug, name: label } };
}

export function parentCrumb(
	focusable: Focusable,
	ctx: ContextManager | undefined,
	detail: ObjectDetailData | null,
	groupGlobal: GlobalGroupData | null,
	starSystem: { id: number; name: string } | null = null,
	parentGroupName?: string
): Crumb | null {
	// A surface feature climbs to its host, on the Features tab: its neighbours,
	// not the body's overview.
	if (focusable.kind === 'feature') {
		const { id, name } = focusable.body.data;
		return name ? { label: name, target: { kind: 'focus', id, name, tab: 'features' } } : null;
	}
	if (focusable.kind === 'group') {
		const slug = focusable.slug;
		if (slug.startsWith(CATEGORY_SLUG_PREFIX)) {
			// The property collections hang off Structure & Activity, the way the
			// ft- pages hang off Surface Features.
			if (isPropertyCollection(slug)) return categoryCrumb(CAT_STRUCTURE_ACTIVITY);
			const parent = PARENT_CATEGORY[slug];
			return parent ? categoryCrumb(parent) : null;
		}
		// A split-comet family is always a comet, regardless of orbit class.
		if (slug.startsWith(COMET_FAMILY_SLUG_PREFIX)) return categoryCrumb(CAT_COMETS);
		if (slug.startsWith(FEATURE_TYPE_SLUG_PREFIX)) return categoryCrumb(CAT_SURFACE_FEATURES);
		// A family climbs to the first family that contains it. A top family
		// climbs to the Stars or the Planets page.
		if (isFamilySlug(slug)) {
			const parent = groupGlobal?.parent_families?.[0];
			if (!parent) return null;
			const label = familyLabel(parent);
			return { label, target: { kind: 'group', slug: parent, name: label } };
		}
		// A figure climbs to its culture, a culture to the Constellations page.
		if (slug.startsWith(SKY_CULTURE_SLUG_PREFIX)) {
			const parent = groupGlobal?.parent_group;
			if (!parent) return null;
			const label = parentGroupName ?? familyLabel(parent);
			return { label, target: { kind: 'group', slug: parent, name: label } };
		}
		const appliesTo = groupGlobal?.applies_to;
		// An orbit zone is a place; NEO and PHA are kinds of asteroid.
		if (appliesTo === 'small_body') {
			return categoryCrumb(classNameFromSlug(slug) ? CAT_SOLAR_SYSTEM : CAT_ASTEROIDS);
		}
		// Earth orbiters split between Satellites and Debris; the export resolves
		// which, since spent stages and breakup clouds look like any other fleet
		// from here.
		if (appliesTo === 'earth_sat') {
			return categoryCrumb(groupGlobal?.parent_category ?? CAT_SATELLITES);
		}
		// A mission collects craft, so it climbs where its craft do. Closes the
		// chain: a probe already climbs to its mission, which would otherwise end
		// there.
		if (appliesTo === 'probe') return categoryCrumb(CAT_PROBES);
		return null;
	}

	// A star or an inner node climbs to the root of its system, which is a root
	// of the tree; a planet climbs to its star.
	if (focusable.kind === 'star') {
		if (!starSystem) return null;
		const { id, name } = starSystem;
		return { label: name, target: { kind: 'focus', id: extrasolarObjectId(id), name } };
	}
	if (focusable.kind === 'planet') {
		const host = focusable.anchor.hostRecord;
		const name = localName(host) ?? String(host.id);
		return { label: name, target: { kind: 'focus', id: extrasolarObjectId(host.id), name } };
	}

	const data = focusable.body.data;

	// The Sun, the planets, the dwarf planets and the planetary systems sit in
	// the Solar System; their collections are cross-ref tiles.
	if (
		data.objectType === ObjectType.STAR ||
		data.objectType === ObjectType.PLANET ||
		data.objectType === ObjectType.DWARF_PLANET ||
		data.objectType === ObjectType.BARYCENTER
	)
		return categoryCrumb(CAT_SOLAR_SYSTEM);

	// Moon (planetary or small-body) → its host (planet, not the barycenter;
	// or the host asteroid). Must precede the URL-type branches: small-body
	// moons carry spkid- ids and would otherwise resolve to an orbit-class zone.
	if (data.objectType === ObjectType.MOON) {
		const { id, name } = moonHost(ctx, data.parentId, detail);
		// Land on the parent's Moons tab so the moon's siblings are in view. A
		// moon the catalogue names no host for has nowhere to climb to.
		return name && id ? { label: name, target: { kind: 'focus', id, name, tab: 'members' } } : null;
	}

	const localized = detail?.localized;

	// Split-comet fragment → its parent comet. Precedes the small-body branch: a
	// fragment carries a spkid- id and would otherwise resolve to its orbit-class
	// zone. A family is a kind, so a fragment with no intact parent takes the zone
	// and the family stays on its tile.
	const fragmentOf =
		detail?.global?.fragment_of && localizeLink(detail.global.fragment_of, localized);
	if (fragmentOf?.primary_type === 'object') {
		return {
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

	// A carried craft → the carrier whose position it borrows (Huygens → the
	// Cassini orbiter), not the mission that holds them both.
	const carriedBy = detail?.global?.carried_by && localizeLink(detail.global.carried_by, localized);
	if (carriedBy?.primary_type === 'object') {
		return {
			label: carriedBy.name,
			target: { kind: 'focus', id: carriedBy.primary_id, name: carriedBy.name }
		};
	}

	// Probe in a mission → the mission group page (primary craft and members
	// alike). Precedes the Probes-category fallback below.
	const mission = detail?.global?.mission ?? detail?.global?.part_of_mission;
	const missionLink = mission && localizeLink(mission, localized);
	if (missionLink) {
		return {
			label: missionLink.name,
			target: { kind: 'group', slug: missionLink.primary_id, name: missionLink.name }
		};
	}

	const urlType = urlTypeFromId(data.id);

	// Earth satellite → its constellation, else its orbit-class zone.
	if (urlType === UrlType.EarthSatellite) {
		// The export resolves the destination itself (ROCKET constellations land on
		// their lv- page, not a const- one that doesn't exist), so never re-derive
		// the slug from `celestrak.constellation_slug`.
		const con = detail?.localized?.constellation;
		if (con?.primary_type === 'group' && con.primary_id) {
			return {
				label: con.name,
				target: { kind: 'group', slug: con.primary_id, name: con.name }
			};
		}
		const ct = detail?.global?.celestrak;
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

/** One-level "parent" crumb for the drawer header. Each focusable resolves to
 *  at most one ancestor: a moon to its planet, a small body to its orbit-class
 *  zone, a satellite to its constellation (else its orbit class), a feature to
 *  its body. Planets, the Sun, groups and probes anchor on category pages that
 *  don't exist yet — they return null. */

import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
import type { ObjectDetailData } from '$lib/fetch/objects/object-data';
import { ObjectType, sbdbOrbitClass, type PositionedBody } from '$lib/types/objects';
import { dominantPlanetId, isTopLevelParent } from '$lib/scene/state/bodies.svelte';
import { CLASS_SLUG_PREFIX } from '$lib/fetch/groups/registry';
import { classifyEarthOrbit, orbitClassLabel } from '$lib/charts/orbit-zones';
import type { Focusable } from './focusable';
import { urlTypeFromId } from './url';
import { UrlType } from './view';

/** A moon's real parent is the dominant planet, not its (nameless) barycenter. */
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
	| { kind: 'focus'; id: string; name: string }
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

/** Title-case a bare constellation slug as a last resort when the localized
 *  detail hasn't supplied a display name. */
function prettifySlug(slug: string): string {
	return slug.charAt(0).toUpperCase() + slug.slice(1);
}

export function parentCrumb(
	focusable: Focusable,
	ctx: ContextManager | undefined,
	detail: ObjectDetailData | null
): Crumb | null {
	// A surface feature belongs to the body it sits on.
	if (focusable.kind === 'feature') {
		const b = focusable.body.data;
		return b.name ? { label: b.name, target: { kind: 'focus', id: b.id, name: b.name } } : null;
	}
	// Group parents are category pages (phase 2).
	if (focusable.kind === 'group') return null;

	const data = focusable.body.data;

	// Dwarf planets aren't zoned — derive the class from heliocentric (a, e).
	// Pluto's own elements orbit its barycenter, so walk one level up for it.
	if (data.objectType === ObjectType.DWARF_PLANET) {
		let a = data.a;
		let e = data.e;
		if (!isTopLevelParent(data.parentId)) {
			const parent = ctx?.getBody(data.parentId);
			if (parent?.data.a) {
				a = parent.data.a;
				e = parent.data.e;
			}
		}
		const cls = sbdbOrbitClass(a, e);
		return cls ? classGroup(cls) : null;
	}

	const urlType = urlTypeFromId(data.id);

	// Earth satellite → its constellation, else its orbit-class zone.
	if (urlType === UrlType.EarthSatellite) {
		const ct = detail?.global?.celestrak;
		if (ct?.constellation_slug) {
			const name = detail?.localized?.constellation?.name ?? prettifySlug(ct.constellation_slug);
			return { label: name, target: { kind: 'group', slug: ct.constellation_slug, name } };
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

	// Moon (planetary or small-body) → its parent planet (not the barycenter).
	if (data.objectType === ObjectType.MOON) {
		const parent = parentPlanet(ctx, data.parentId);
		const name = parent?.data.name;
		return parent && name
			? { label: name, target: { kind: 'focus', id: parent.data.id, name } }
			: null;
	}

	// Planets, dwarf planets, the Sun, probes: parents land in phase 2.
	return null;
}

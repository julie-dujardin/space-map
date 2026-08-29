/**
 * A planetary system as the barycenter page draws it: the primary planet plus
 * every moon the scene has loaded under that barycenter, measured in planet
 * radii.
 *
 * Orbits come from the live scene rather than the export — the barycenter's
 * own bundle carries nothing but its orbit, and no export block pairs a moon's
 * semi-major axis with its size. `BodyIndex` already holds both for every
 * loaded body, so the map reads them straight off it and re-derives as the
 * system streams in.
 */

import { AU_KM } from '$lib/math/units';
import { BODY_COLORS, DEFAULT_BODY_COLOR } from '$lib/constants';
import { dominantPlanetId } from '$lib/scene/state/bodies.svelte';
import { ObjectType, type PositionedBody } from '$lib/types/objects';
import * as m from '$lib/paraglide/messages.js';
import { resolveBodyColor } from '$lib/utils';
import { buildLineup, geometryFromMember } from './lineup';
import { fetchMoonDiscovery, type MoonDiscoveryFile } from '$lib/fetch/groups/moon-discovery';
import type { LineupBody } from './BodyLineup.svelte';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
import {
	fetchObjectDetail,
	type GlobalObjectData,
	type ObjectDetailData
} from '$lib/fetch/objects/object-data';

export interface SystemMoon {
	id: string;
	name: string;
	/** Orbit semi-major axis in primary equatorial radii — the map's x axis. */
	aRp: number;
	/** Orbit tilt to the *primary's equator* [deg]; > 90° is retrograde about the
	 *  primary. The exported elements are ecliptic, which would read the primary's
	 *  own obliquity as inclination and lay the whole regular system off-axis. */
	tiltDeg: number;
	radiusKm: number;
	color: string;
}

export interface SystemRings {
	/** Ring span in primary equatorial radii, across every ring bundle. */
	innerRp: number;
	outerRp: number;
}

export interface PlanetarySystem {
	planet: PositionedBody;
	planetName: string;
	planetRadiusKm: number;
	planetColor: string;
	moons: SystemMoon[];
	rings: SystemRings | null;
	/** The primary has a named-ring catalogue, so its Rings tab is worth a tile. */
	hasRingCatalog: boolean;
	/** The primary's notable moons, largest first, for the moon tile's disc row. */
	moonDiscs: LineupBody[];
	/** Moons the catalogue knows about, which is more than the scene loads. */
	moonCount: number;
}

const DEG2RAD = Math.PI / 180;
const ECLIPTIC_RAD = 23.4392911 * DEG2RAD;

/** The primary's spin axis as an ecliptic-frame unit vector, from the IAU pole.
 *  Falls back to the ecliptic pole when the bundle carries no orientation, which
 *  makes the tilt degrade to the plain ecliptic inclination. */
function poleVector(global: GlobalObjectData | null): [number, number, number] {
	const o = global?.orientation;
	if (!o) return [0, 0, 1];
	const ra = o.pole_ra_0 * DEG2RAD;
	const dec = o.pole_dec_0 * DEG2RAD;
	const x = Math.cos(dec) * Math.cos(ra);
	const y = Math.cos(dec) * Math.sin(ra);
	const z = Math.sin(dec);
	return [
		x,
		y * Math.cos(ECLIPTIC_RAD) + z * Math.sin(ECLIPTIC_RAD),
		-y * Math.sin(ECLIPTIC_RAD) + z * Math.cos(ECLIPTIC_RAD)
	];
}

/** Angle between an orbit's normal and the primary's spin axis [deg] — the
 *  inclination a moon actually has within its system. 0 is equatorial and
 *  prograde, 180 equatorial and retrograde. */
function tiltToEquator(iDeg: number, omDeg: number, pole: [number, number, number]): number {
	const i = iDeg * DEG2RAD;
	const om = omDeg * DEG2RAD;
	const n: [number, number, number] = [
		Math.sin(i) * Math.sin(om),
		-Math.sin(i) * Math.cos(om),
		Math.cos(i)
	];
	const dot = n[0] * pole[0] + n[1] * pole[1] + n[2] * pole[2];
	return Math.acos(Math.max(-1, Math.min(1, dot))) / DEG2RAD;
}

/** Ring span across every bundle, in primary radii; null when the primary has
 *  no rings or no radius to scale them by. */
function ringSpan(global: GlobalObjectData | null, radiusKm: number): SystemRings | null {
	const bundles = global?.rings;
	if (!bundles?.length || radiusKm <= 0) return null;
	let inner = Infinity;
	let outer = 0;
	for (const r of bundles) {
		if (r.inner_radius_km < inner) inner = r.inner_radius_km;
		if (r.outer_radius_km > outer) outer = r.outer_radius_km;
	}
	if (!Number.isFinite(inner) || outer <= inner) return null;
	return { innerRp: inner / radiusKm, outerRp: outer / radiusKm };
}

/** The primary's equatorial radius: the export's triaxial `radii` when the
 *  bundle is loaded, else the scene's render radius. */
function primaryRadiusKm(planet: PositionedBody, global: GlobalObjectData | null): number {
	const radii = global?.radii;
	if (radii) return Math.max(radii.a, radii.b, radii.c);
	return planet.data.radiusKm;
}

/** The planetary system a body belongs to, as its barycenter id — the
 *  barycenter itself, or the one a planet or moon hangs off. Null for anything
 *  outside a planetary system (the Sun, small bodies, the SSB). */
export function systemBarycenterId(
	body: PositionedBody | null,
	ctx: ContextManager | undefined
): string | null {
	if (!body) return null;
	if (dominantPlanetId(body.data.id)) return body.data.id;
	const parent = ctx?.getBody(body.data.parentId);
	if (parent?.data.objectType !== ObjectType.BARYCENTER) return null;
	return dominantPlanetId(parent.data.id) ? parent.data.id : null;
}

export interface PlanetarySystemDeps {
	/** Focused body; its system is resolved with `systemBarycenterId`, so a
	 *  planet and its moons all resolve the same one. */
	body: () => PositionedBody | null;
	ctx: () => ContextManager | undefined;
}

/**
 * Builds the focused body's planetary system, or null outside one. Every member
 * resolves the same system, so a planet and a moon can both cross-refer to it;
 * `isSystemPage` is what separates the barycenter's own page from those.
 * Bodies stream in after the first paint, so the class subscribes to
 * `onBodiesAdded` and re-derives — a plain `$derived` over the index's Maps
 * would never see the moons arrive.
 */
export class PlanetarySystemState {
	#version = $state(0);
	// The primary's own bundle: the barycenter's carries no radii and no rings,
	// and the moons are localized there too.
	#primary = $state<ObjectDetailData | null>(null);
	#discovery = $state<MoonDiscoveryFile | null>(null);
	readonly system: PlanetarySystem | null;
	/** The barycenter this system is keyed by, and the page a tile links to. */
	readonly systemId: string | null;
	/** True only on the barycenter's own page, which the system map heroes. */
	readonly isSystemPage: boolean;
	/** "<primary> system" — the name the drawer titles this page with, in place
	 *  of the SPICE "<primary> Barycenter" the 3D labels keep. */
	readonly systemName: string | undefined;
	/** Moons found per year in this system, for the discovery chart. Undefined
	 *  where no moon carries a discovery year — the Moon has none. */
	readonly discoveryHistogram: Record<string, number> | undefined;
	/** The primary's id — `null` when this page is not a planetary system. */
	readonly primaryId: string | undefined;

	constructor(d: PlanetarySystemDeps) {
		this.systemId = $derived(systemBarycenterId(d.body(), d.ctx()));
		this.isSystemPage = $derived(!!this.systemId && d.body()?.data.id === this.systemId);
		this.primaryId = $derived.by(() => {
			const id = this.systemId;
			return id ? (dominantPlanetId(id) ?? undefined) : undefined;
		});
		// Named off the primary's own bundle, so it does not wait on the moons the
		// map needs — Mercury and Venus are systems too, they just have no moons.
		this.systemName = $derived.by(() => {
			const planetId = this.primaryId;
			if (!planetId) return undefined;
			const detail = this.#primary?.global?.id === planetId ? this.#primary : null;
			const primary = detail?.localized?.name ?? detail?.global?.name;
			return primary ? m.planetary_system_title({ primary }) : undefined;
		});

		this.system = $derived.by<PlanetarySystem | null>(() => {
			void this.#version; // re-derive as the system's bodies load
			const baryId = this.systemId;
			const planetId = this.primaryId;
			const ctx = d.ctx();
			if (!baryId || !planetId || !ctx) return null;
			const planet = ctx.getBody(planetId);
			if (!planet) return null;

			const detail = this.#primary?.global?.id === planetId ? this.#primary : null;
			const global = detail?.global ?? null;
			const radiusKm = primaryRadiusKm(planet, global);
			if (radiusKm <= 0) return null;
			const names = detail?.localized?.notable_moon_names;
			const pole = poleVector(global);

			// SPICE hangs a system's moons off the barycenter, but a few sit on the
			// planet itself; take both so no system draws short.
			const childIds = new Set([
				...(ctx.bodies.getChildren(baryId) ?? []),
				...(ctx.bodies.getChildren(planetId) ?? [])
			]);
			const moons: SystemMoon[] = [];
			for (const id of childIds) {
				const b = ctx.getBody(id);
				if (!b || b.data.objectType !== ObjectType.MOON) continue;
				const aRp = (b.data.a * AU_KM) / radiusKm;
				if (!Number.isFinite(aRp) || aRp <= 0) continue;
				moons.push({
					id,
					name: names?.[id] ?? b.data.name ?? id,
					aRp,
					tiltDeg: tiltToEquator(b.data.i, b.data.om, pole),
					// Designation-only moons carry no radius; 0 means "draw at the floor".
					radiusKm: b.data.radiusKm > 0 ? b.data.radiusKm : 0,
					color: BODY_COLORS[id] ?? b.data.color ?? resolveBodyColor(b.data)
				});
			}
			if (moons.length === 0) return null;
			moons.sort((a, b) => a.aRp - b.aRp);

			return {
				planet,
				planetName: detail?.localized?.name ?? global?.name ?? planet.data.name ?? planetId,
				planetRadiusKm: radiusKm,
				planetColor: BODY_COLORS[planetId] ?? DEFAULT_BODY_COLOR,
				moons,
				rings: ringSpan(global, radiusKm),
				hasRingCatalog: Object.values(global?.ring_features ?? {}).some((f) => !f.parent),
				moonDiscs: buildLineup(global?.notable_moons ?? [], geometryFromMember, { names }).sort(
					(a, b) => b.radiusKm - a.radiusKm
				),
				moonCount: global?.moon_count ?? moons.length
			};
		});

		// Keyed on the barycenter: a moon's parent is its system barycenter, which
		// is the id the export groups the tallies by. A system whose moons were all
		// found in one year has no timeline to draw — Mars would be a single block
		// bar — so it keeps the year on its Discovery rows instead.
		this.discoveryHistogram = $derived.by(() => {
			const baryId = this.systemId;
			// The chart belongs to the system's own page; a planet or moon in it
			// cross-refers there rather than repeating the timeline.
			if (!baryId || !this.isSystemPage || !this.system) return undefined;
			const histogram = this.#discovery?.[baryId];
			return histogram && Object.keys(histogram).length >= 2 ? histogram : undefined;
		});

		$effect(() => {
			const ctx = d.ctx();
			if (!ctx) return;
			return ctx.bodies.onBodiesAdded(() => this.#version++);
		});

		$effect(() => {
			if (!this.primaryId) return;
			fetchMoonDiscovery()
				.then((f) => (this.#discovery = f))
				.catch((e) => console.error('Moon discovery timeline failed to load', e));
		});

		$effect(() => {
			const planetId = this.primaryId;
			if (!planetId) {
				this.#primary = null;
				return;
			}
			let cancelled = false;
			fetchObjectDetail(planetId)
				.then((detail) => {
					if (!cancelled) this.#primary = detail;
				})
				.catch((e) => console.error('Primary bundle failed to load', planetId, e));
			return () => {
				cancelled = true;
			};
		});
	}
}

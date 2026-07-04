/** The sphere-lineup hero and its imagery/metadata credits, factored out of
 *  DetailDrawer. Picks which collection page (planets/moons/dwarfs/small-body
 *  zone/planet-moons) gets a lineup, builds it, and tracks the texture credits
 *  the NC-licensed surface maps require. */

import { buildLineup, geometryFromMember, renderableCount } from './lineup';
import { STRIP_CAPACITY } from '../members/MemberStrip.svelte';
import type { LineupBody } from './BodyLineup.svelte';
import { loadTextureCredits, type TextureSource } from '$lib/credits/texture-credits';
import type { NotableMemberEntry } from '$lib/fetch/objects/object-data';
import type { CategoryConfig } from '$lib/state/category-config';
import * as m from '$lib/paraglide/messages.js';

// A small-body zone earns a sphere lineup once enough members carry a measured
// diameter; below the floor it falls back to the plain member-strip page.
const SMALL_BODY_LINEUP_FLOOR = 3;

export interface LineupHeroDeps {
	isGroupMode: () => boolean;
	cat: () => CategoryConfig;
	isPlanetBody: () => boolean;
	satellitesGroup: () => string | undefined;
	moonCount: () => number;
	fallbackName: () => string;
	notableMembers: () => NotableMemberEntry[] | undefined;
	memberNames: () => Record<string, string> | undefined;
	memberDescriptions: () => Record<string, string> | undefined;
	moonDescriptions: () => Record<string, string> | undefined;
}

export interface LineupHeroSpec {
	bodies: LineupBody[];
	ariaLabel: string;
	perPage?: number;
}

type ImageryCredit = { key: string; label: string; url: string };

export class LineupHero {
	#credits = $state<Map<string, TextureSource> | null>(null);

	// A planet's moons get a lineup hero in its Moons tab; ≥2 renderable keeps it
	// a real lineup, not a lone sphere. Mirrors DetailDrawer's showMembersTab.
	readonly isMoonLineup: boolean;
	readonly hero: LineupHeroSpec | null;
	// Solar System: the minimap is the page hero, so the sphere lineup moves into
	// the members tab (paginated).
	readonly solarSystemLineup: { bodies: LineupBody[]; perPage: number } | null;
	readonly imagery: ImageryCredit[];
	readonly pck: boolean;
	readonly wikidata: boolean;
	readonly sbdb: boolean;
	// The moon-lineup hero moves its credits to the members tab where the spheres
	// render, so the overview footer drops them.
	readonly overviewCredits: {
		pck: boolean;
		wikidata: boolean;
		sbdb: boolean;
		imagery: ImageryCredit[];
	};

	constructor(d: LineupHeroDeps) {
		const smallBodyBodies = $derived(
			buildLineup(d.notableMembers() ?? [], geometryFromMember, {
				names: d.memberNames(),
				descriptions: d.memberDescriptions()
			})
		);
		const isSmallBodyLineup = $derived(
			d.isGroupMode() &&
				!d.cat().lineup &&
				renderableCount(d.notableMembers()) >= SMALL_BODY_LINEUP_FLOOR
		);

		this.isMoonLineup = $derived(
			d.isPlanetBody() &&
				!d.satellitesGroup() &&
				d.moonCount() > STRIP_CAPACITY &&
				renderableCount(d.notableMembers()) >= 2
		);

		// Picks the collection page's lineup, or null to keep an image hero.
		// Planets omit hover descriptions by design.
		this.hero = $derived.by<LineupHeroSpec | null>(() => {
			const members = d.notableMembers();
			if (!members || members.length === 0) return null;
			const names = d.memberNames();
			const cat = d.cat();
			if (cat.planets)
				return {
					bodies: buildLineup(members, geometryFromMember, { names }),
					ariaLabel: m.type_planet()
				};
			if (cat.moons)
				return {
					bodies: buildLineup(members, geometryFromMember, {
						names,
						descriptions: d.memberDescriptions()
					}),
					ariaLabel: m.type_moon(),
					perPage: 5
				};
			if (cat.dwarfPlanets)
				return {
					bodies: buildLineup(members, geometryFromMember, {
						names,
						descriptions: d.memberDescriptions()
					}),
					ariaLabel: m.type_dwarf_planet(),
					perPage: 5
				};
			if (isSmallBodyLineup)
				return { bodies: smallBodyBodies, ariaLabel: d.fallbackName(), perPage: 8 };
			if (this.isMoonLineup)
				return {
					bodies: buildLineup(members, geometryFromMember, {
						names,
						descriptions: d.moonDescriptions()
					}),
					ariaLabel: m.type_moon(),
					perPage: 5
				};
			return null;
		});

		this.solarSystemLineup = $derived.by(() => {
			const members = d.notableMembers();
			if (!d.cat().solarSystem || !members || members.length === 0) return null;
			const bodies = buildLineup(members, geometryFromMember, {
				names: d.memberNames(),
				descriptions: d.memberDescriptions()
			});
			return bodies.length === 0 ? null : { bodies, perPage: 8 };
		});

		// Imagery credits narrowed to the on-screen spheres, deduped by author so
		// the footer lists each surface-map source once.
		this.imagery = $derived.by(() => {
			const hero = this.hero;
			const credits = this.#credits;
			if (!hero || !credits) return [];
			const out: ImageryCredit[] = [];
			const seen = new Set<string>();
			for (const b of hero.bodies) {
				const cred = credits.get(b.id);
				if (!cred || seen.has(cred.organisation)) continue;
				seen.add(cred.organisation);
				out.push({ key: cred.organisation, label: cred.organisation, url: cred.source });
			}
			return out;
		});

		// Metadata sources the lineup members draw on: radii/pole/mass ⇒ PCK (moon
		// diameters are PCK mean radii too); radius fallback ⇒ Wikidata; small-body
		// diameter/albedo/spectral data ⇒ SBDB.
		this.pck = $derived(
			!!this.hero &&
				(this.isMoonLineup ||
					(d.notableMembers() ?? []).some((mm) => mm.radii || mm.pole || mm.mass_kg != null))
		);
		this.wikidata = $derived(
			!!this.hero && (d.notableMembers() ?? []).some((mm) => mm.radius_km != null)
		);
		this.sbdb = $derived(!!this.hero && isSmallBodyLineup);

		this.overviewCredits = $derived(
			this.isMoonLineup
				? { pck: false, wikidata: false, sbdb: false, imagery: [] }
				: { pck: this.pck, wikidata: this.wikidata, sbdb: this.sbdb, imagery: this.imagery }
		);

		// Load surface-imagery credits lazily, once a lineup is actually shown.
		$effect(() => {
			if (!this.hero) return;
			loadTextureCredits().then((c) => (this.#credits = c));
		});
	}
}

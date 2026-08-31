/** The sphere-lineup hero and its imagery/metadata credits, factored out of
 *  DetailDrawer. Picks which collection page gets a lineup, builds it, and
 *  tracks the texture credits the NC-licensed surface maps require. */

import {
	buildLineup,
	craftGeometryFromMember,
	geometryFromMember,
	renderableCount
} from './lineup';
import { STRIP_CAPACITY } from '../members/MemberStrip.svelte';
import type { LineupBody } from './BodyLineup.svelte';
import { loadTextureCredits, type TextureSource } from '$lib/credits/texture-credits';
import {
	craftTier,
	fetchBundleMeta,
	modelTierCredit,
	shapeModelCredit
} from '$lib/scene/objects/body/model';
import { lineupDrawsShapeModel } from '$lib/scene/objects/body/shape-model-policy';
import type { NotableMemberEntry } from '$lib/fetch/objects/object-data';
import type { CategoryConfig } from '$lib/state/category-config';
import * as m from '$lib/paraglide/messages.js';

// A small-body zone earns a sphere lineup once enough members carry a measured
// diameter; below the floor it falls back to the plain member-strip page.
const SMALL_BODY_LINEUP_FLOOR = 3;

// Only a PCK pole is the IAU's to credit; an asteroid lineup's poles come from
// DAMIT lightcurve inversions instead. Named, not inlined — boolean groups
// inside `$derived` lose their parens through the .svelte.ts transform.
const hasPckPole = (mm: NotableMemberEntry) => !!mm.pole && !mm.pole.source;
const hasLightcurvePole = (mm: NotableMemberEntry) => mm.pole?.source === 'lightcurve';
const hasPckGeometry = (mm: NotableMemberEntry) =>
	!!mm.radii || mm.mass_kg != null || hasPckPole(mm);

export interface LineupHeroDeps {
	isGroupMode: () => boolean;
	cat: () => CategoryConfig;
	isPlanetBody: () => boolean;
	satellitesGroup: () => string | undefined;
	moonCount: () => number;
	fallbackName: () => string;
	/** Whether this page asked for a sphere lineup — see `CategoryConfig`. */
	sphereLineup: () => boolean;
	notableMembers: () => NotableMemberEntry[] | undefined;
	/** The probes this page lists — a body's visitors, or a collection's. */
	probes: () => NotableMemberEntry[] | undefined;
	probeNames: () => Record<string, string> | undefined;
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
	// Shape-model authors, keyed by body id — the mesh is what renders those
	// members, so its catalogue credit belongs beside the texture credits.
	#modelCredits = $state<Map<string, ImageryCredit>>(new Map());

	// A planet's moons get a lineup hero in its Moons tab; ≥2 renderable keeps it
	// a real lineup, not a lone sphere. Mirrors DetailDrawer's showMembersTab.
	readonly isMoonLineup: boolean;
	readonly hero: LineupHeroSpec | null;
	// The probes tab's own hero: the craft that went there, to scale against each
	// other. Independent of `hero` — an asteroid collection draws both.
	readonly probeLineup: LineupHeroSpec | null;
	// Solar System: the minimap is the page hero, so the sphere lineup moves into
	// the members tab (paginated).
	readonly solarSystemLineup: { bodies: LineupBody[]; perPage: number } | null;
	readonly imagery: ImageryCredit[];
	// The probe lineup's mesh credits, which the probes tab carries; several
	// bundles are CC BY-SA and cannot be drawn uncredited.
	readonly craftImagery: ImageryCredit[];
	readonly pck: boolean;
	readonly lightcurvePole: boolean;
	readonly wikidata: boolean;
	readonly sbdb: boolean;
	// The moon-lineup hero moves its credits to the members tab where the spheres
	// render, so the overview footer drops them.
	readonly overviewCredits: {
		pck: boolean;
		lightcurvePole: boolean;
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
		// A collection of spacecraft: its members resolve to craft models, which
		// only a spacecraft has. Group mode only — a body's own member list can
		// hold satellites without the page being about them — and never the Solar
		// System, whose hero is its minimap and whose credits track the sphere row
		// down in the members tab.
		const craftMembers = $derived(
			d.isGroupMode() && !d.cat().solarSystem
				? buildLineup(d.notableMembers() ?? [], craftGeometryFromMember, {
						names: d.memberNames(),
						descriptions: d.memberDescriptions()
					})
				: []
		);

		// Opt-in: a page must ask for spheres rather than getting them from having
		// enough renderable members — ring systems has eight renderable bodies, but
		// a row of spheres would picture the planets, not the rings.
		const isSmallBodyLineup = $derived(
			d.isGroupMode() &&
				d.sphereLineup() &&
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
			// One craft is still worth drawing: a mission page with two of them, or a
			// body a single mesh-bearing probe ever reached, is a picture of the
			// page. Sizes only start comparing at two, and that is a bonus here.
			if (craftMembers.length > 0)
				return { bodies: craftMembers, ariaLabel: d.fallbackName(), perPage: 3 };
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

		this.probeLineup = $derived.by<LineupHeroSpec | null>(() => {
			const bodies = buildLineup(d.probes() ?? [], craftGeometryFromMember, {
				names: d.probeNames()
			});
			if (bodies.length === 0) return null;
			return { bodies, ariaLabel: m.probes_section(), perPage: 3 };
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

		// Whichever lineup this page draws: the collection hero, or the Solar
		// System's row of spheres down in the members tab. Both render real
		// textures on real radii and owe the same credits.
		const lineupBodies = $derived(this.hero?.bodies ?? this.solarSystemLineup?.bodies ?? null);

		// Imagery credits for the on-screen bodies, deduped by author. Covers both
		// surface-map textures and meshes — a mesh draped with a map credits both.
		const imageryFor = (bodies: LineupBody[] | null | undefined): ImageryCredit[] => {
			if (!bodies) return [];
			const textures = this.#credits;
			const models = this.#modelCredits;
			const out: ImageryCredit[] = [];
			const seen = new Set<string>();
			const add = (c: ImageryCredit | undefined) => {
				if (!c || seen.has(c.key)) return;
				seen.add(c.key);
				out.push(c);
			};
			for (const b of bodies) {
				const tex = textures?.get(b.id);
				add(tex && { key: tex.organisation, label: tex.organisation, url: tex.source });
				add(models.get(b.id));
			}
			return out;
		};
		this.imagery = $derived(imageryFor(lineupBodies));
		this.craftImagery = $derived(imageryFor(this.probeLineup?.bodies));

		// Metadata sources the lineup members draw on: radii/pole/mass ⇒ PCK (moon
		// diameters are PCK mean radii too); radius fallback ⇒ Wikidata; small-body
		// diameter/albedo/spectral data ⇒ SBDB.
		const pckClaim = $derived(this.isMoonLineup || (d.notableMembers() ?? []).some(hasPckGeometry));
		const hasLineup = $derived(!!lineupBodies);
		this.pck = $derived(hasLineup && pckClaim);
		this.lightcurvePole = $derived(hasLineup && (d.notableMembers() ?? []).some(hasLightcurvePole));
		this.wikidata = $derived(
			hasLineup && (d.notableMembers() ?? []).some((mm) => mm.radius_km != null)
		);
		this.sbdb = $derived(hasLineup && isSmallBodyLineup);

		// Both lineups that live in the members tab leave the overview footer
		// with nothing to credit — the spheres they credit are a tab away.
		const lineupInMembersTab = $derived(this.isMoonLineup || !!this.solarSystemLineup);
		this.overviewCredits = $derived(
			lineupInMembersTab
				? { pck: false, lightcurvePole: false, wikidata: false, sbdb: false, imagery: [] }
				: {
						pck: this.pck,
						lightcurvePole: this.lightcurvePole,
						wikidata: this.wikidata,
						sbdb: this.sbdb,
						imagery: this.imagery
					}
		);

		// Load surface-imagery credits lazily, once a lineup is actually shown.
		$effect(() => {
			if (!lineupBodies) return;
			loadTextureCredits().then((c) => (this.#credits = c));
		});

		// Members drawn from a mesh rather than a texture credit the model bundle
		// meta (cache-shared with BodyLineup's own load): a body's shape model
		// against its catalogue, a craft against whoever built the tier drawn.
		// Best-effort — a failed meta just omits that author.
		$effect(() => {
			const models = [...(lineupBodies ?? []), ...(this.probeLineup?.bodies ?? [])].filter(
				(b) => b.craft || lineupDrawsShapeModel(b)
			);
			if (models.length === 0) return;
			let cancelled = false;
			Promise.all(
				models.map(async (b) => {
					try {
						const meta = await fetchBundleMeta(b.model!);
						const c =
							meta.kind === 'shape_model'
								? shapeModelCredit(meta)
								: b.craft
									? modelTierCredit(meta, craftTier(meta))
									: null;
						if (!c) return null;
						return [b.id, { key: c.name, label: c.name, url: c.url }] as const;
					} catch {
						return null;
					}
				})
			).then((entries) => {
				if (cancelled) return;
				const next = new Map<string, ImageryCredit>();
				for (const e of entries) if (e) next.set(e[0], e[1]);
				this.#modelCredits = next;
			});
			return () => {
				cancelled = true;
			};
		});
	}
}

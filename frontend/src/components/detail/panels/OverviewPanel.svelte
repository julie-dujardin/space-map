<script lang="ts">
	import { untrack, type Snippet } from 'svelte';
	import { Button } from '$lib/components/ui/button/index.js';
	import MapIcon from '@lucide/svelte/icons/map';
	import PanelSkeleton from '../frame/skeleton/PanelSkeleton.svelte';
	import GroupStatCards from '../sections/GroupStatCards.svelte';
	import FeatureStatCards from '../sections/FeatureStatCards.svelte';
	import ObjectStats from '../sections/ObjectStats.svelte';
	import ObjectDescription from '../sections/ObjectDescription.svelte';
	import FeatureProperties from '../sections/FeatureProperties.svelte';
	import ObjectLinks from '../sections/ObjectLinks.svelte';
	import SourcesFooter, { type Source as CitedSource } from '../sections/SourcesFooter.svelte';
	import { cultureSource } from '../sections/culture-credits';
	import MemberStrip from '../members/MemberStrip.svelte';
	import BodyCrossRefs from './overview/BodyCrossRefs.svelte';
	import SystemDiscovery from '../sections/SystemDiscovery.svelte';
	import BodySections from './overview/BodySections.svelte';
	import GroupOverviewSections from './overview/GroupOverviewSections.svelte';
	import { MASS_INVENTORY_URL } from '$lib/data/solar-system-mass';
	import { OrbitalSource } from '$lib/fetch/position/format';
	import type { CategoryConfig } from '$lib/state/category-config';
	import type { Focusable } from '$lib/state/focusable';
	import type { SimClock } from '$lib/scene/state/clock.svelte';
	import type { PositionedBody } from '$lib/types/objects';
	import type { DetailLoad } from '../state/detail-load.svelte';
	import type { MembersState } from '../state/members-state.svelte';
	import type { SurfaceState } from '../state/surface-state.svelte';
	import type { LineupHero } from '../charts/lineup-hero.svelte';
	import type { PlanetarySystemState } from '../charts/planetary-system.svelte';
	import * as m from '$lib/paraglide/messages.js';
	import { getLocale } from '$lib/paraglide/runtime.js';
	import StatCardRow from '../sections/kit/StatCardRow.svelte';
	import StarSections from '../sections/star/StarSections.svelte';
	import StarConstellations from '../sections/star/StarConstellations.svelte';
	import SystemStars from '../sections/star/SystemStars.svelte';
	import Discovery from '../sections/Discovery.svelte';
	import {
		shownCentreTemperature,
		starAliases,
		starIdentifiers,
		starSections,
		starStats
	} from '../sections/star/star-rows';
	import { systemSections, systemStats } from '../sections/star/system-rows';
	import PlanetSections from '../sections/planet/PlanetSections.svelte';
	import {
		planetAliases,
		planetIdentifiers,
		planetSections,
		planetStats
	} from '../sections/planet/planet-rows';
	import PlanetList from '../members/PlanetList.svelte';
	import SystemPlanets from '../members/SystemPlanets.svelte';
	import {
		citationCredits,
		planetCatalogueCredits,
		planetCredits,
		starCredits
	} from '$lib/credits/star-sources';
	import type { ExtrasolarRecord } from '$lib/fetch/extrasolar/lookup';
	import {
		extrasolarAllowed,
		fetchExtrasolarMetadata,
		type ExtrasolarCredit
	} from '$lib/fetch/extrasolar/files';
	import { planetCatalogue, type PlanetSystem } from '$lib/fetch/extrasolar/planets';
	import { systemNode } from '$lib/fetch/extrasolar/systems';
	import {
		radiusPaperPoint,
		nodePlanetCount,
		systemHosts,
		type StarSystem
	} from '$lib/state/star-system';
	import type { PlanetAnchor } from '$lib/types/objects';
	import type { StarStructure } from '../state/star-interior.svelte';

	type FocusFeatureEntry = Extract<Focusable, { kind: 'feature' }>['feature'];

	interface Props {
		body: PositionedBody | null;
		feature: FocusFeatureEntry | null;
		isGroupMode: boolean;
		/** The group page's slug, set exactly when this is one. */
		groupSlug: string | null;
		cat: CategoryConfig;
		clock: SimClock;
		load: DetailLoad;
		members: MembersState;
		surface: SurfaceState;
		lineup: LineupHero;
		parentBody: PositionedBody | undefined;
		planetarySystem: PlanetarySystemState;
		/** The map's page for this object, where the panel is open somewhere
		 *  else and the map is a place to go rather than the ground underneath. */
		mapHref?: string;
		/** The overview is the tab in view. Its charts load their data then. */
		active?: boolean;
		/** The object's action row, headed up by the drawer that knows what the
		 *  page can do with it. Absent on a collection. */
		actions?: Snippet;
		/** The records of an extrasolar object, which has no detail bundle. */
		star?: ExtrasolarRecord | null;
		/** A planet of the extrasolar catalogue, which has none either. */
		planet?: PlanetAnchor | null;
		/** The star system of `star`, once it loads. */
		system?: StarSystem | null;
		/** The system categories of `star`, for its cross-refs. */
		systemCategories?: string[];
		/** The interior of `star`, once it loads. */
		starStructure?: StarStructure | null;
	}

	let {
		body,
		feature,
		isGroupMode,
		groupSlug,
		cat,
		clock,
		load,
		members,
		surface,
		lineup,
		parentBody,
		planetarySystem,
		mapHref,
		active = true,
		actions,
		star = null,
		planet = null,
		system = null,
		systemCategories = [],
		starStructure = null
	}: Props = $props();

	let data = $derived(load.data);
	let groupDetail = $derived(load.groupDetail);
	let linkIdentifiers = $derived(
		star ? starIdentifiers(star) : planet ? planetIdentifiers(planet.planet) : []
	);
	let linkAliases = $derived(star ? starAliases(star) : planet ? planetAliases(planet.planet) : []);

	// The System row of a record is that of a node that holds stars, or of a held star.
	let systemRow = $derived(star ? systemNode(star) : null);
	let node = $derived(systemRow?.star ? null : systemRow);
	let systemPlanets = $derived(system && node ? systemHosts(system, node.id) : []);
	// A held star's page has no list of the system, so the other hosts stay on it.
	let listsStars = $derived(system !== null && !systemRow?.star);
	// The names of the system, so that Wikidata's "Part of" does not repeat them.
	let systemRefs = $derived(
		system ? [...system.nodes.keys()].map((id) => ({ name: system.names.get(id) ?? '' })) : []
	);
	// A held star cites its own values and the orbit of its pair, a node its orbit.
	let citedNodes = $derived.by(() => {
		const held = systemRow?.star ? systemRow : null;
		const pair = held && held.parent !== null ? system?.nodes.get(held.parent) : null;
		return [systemRow, pair].filter((n) => !!n);
	});

	// A star's system file lists its planets. The export metadata names the
	// catalogues behind a planet, and behind the charts of the Planets page.
	let hostSystem = $state.raw<PlanetSystem | null>(null);
	let planetCount = $derived(node ? nodePlanetCount(system, hostSystem, node.id) : 0);
	let exportCredits = $state.raw<readonly ExtrasolarCredit[]>([]);
	$effect(() => {
		const id = star?.id ?? null;
		hostSystem = null;
		if (id === null) return;
		let current = true;
		untrack(() => planetCatalogue.hostSystem(id)).then(
			(system) => {
				if (!current) return;
				hostSystem = system;
			},
			(e: unknown) => console.warn(`[planets] no system for ${id}:`, e)
		);
		return () => {
			current = false;
		};
	});
	$effect(() => {
		const isPlanet = !!planet;
		const isPlanetsPage = cat.planets;
		exportCredits = [];
		if (!isPlanet && !isPlanetsPage) return;
		let current = true;
		untrack(fetchExtrasolarMetadata).then(
			(meta) => {
				if (current) exportCredits = meta?.credits ?? [];
			},
			(e: unknown) => console.warn('[planets] no export credits:', e)
		);
		return () => {
			current = false;
		};
	});

	// Features sit below the moons strip, above fragments, mission craft and probes.
	let overviewStrips = $derived(
		[
			members.membersStrip,
			surface.featuresStrip,
			members.fragmentsStrip,
			members.targetsStrip,
			members.missionStrip,
			members.probesStrip
		].filter((s) => s !== null)
	);

	// Bodies whose `data` holds no usable elements — probes carry a=e=i=…=0,
	// page-only stand-ins carry NaN — must not reach the Orbital panel, which
	// would warn (or throw on the epoch) once a frame.
	let drawerOrbitElements = $derived.by(() => {
		if (!body) return undefined;
		if (body.orbitElements) return body.orbitElements;
		if (body.data.pageOnly || body.data.orbitalSource === OrbitalSource.SPICE_PROBE) {
			return undefined;
		}
		return body.data;
	});

	// Sample sim time at 2 Hz so speed/altitude in the description update
	// smoothly without re-deriving on every animation frame. The seed read is
	// untracked: tracking clock.jd would re-run the effect (and recreate the
	// interval) every frame while time plays.
	let sampledJd = $state(0);
	$effect(() => {
		sampledJd = untrack(() => clock.jd);
		const id = setInterval(() => (sampledJd = clock.jd), 200);
		return () => clearInterval(id);
	});

	// Earth sats (and every earth-sat group page: launch vehicles, organizations,
	// launch sites, countries, …) draw on CelesTrak SATCAT + GCAT for metadata.
	let earthSatCredit = $derived(
		isGroupMode
			? groupDetail?.global?.applies_to === 'earth_sat'
			: data?.global?.cross_refs?.norad_cat_id != null
	);
	// Feature-type pages are entirely IAU gazetteer content, as is the Surface
	// Features browse node above them (`feature_type_count` marks it) — its
	// families, naming timeline and etymology all come from the gazetteer.
	let nomenclatureCredit = $derived(
		groupDetail?.global?.type === 'feature_type' || groupDetail?.global?.feature_type_count != null
	);
	// A small-body collection is SBDB all the way down, unlike the lineup's claim
	// (`overviewCredits.sbdb`) which needs three renderable spheres — figures exist regardless.
	let smallBodyGroupCredit = $derived(
		groupDetail?.global?.applies_to === 'small_body' || cat.smallBody
	);
	// Works a collection page cites outright: the ring catalogue's tables, where
	// they back the mass chart and the tiles rather than one body's panel, the
	// papers every dose on the Radiation page is read off, and the published
	// inventory both Solar System mass charts are drawn from.
	// A culture's or a figure's own text, where it has no article in the
	// reader's language.
	let cultureText = $derived.by(() => {
		const text = groupDetail?.global?.culture_text;
		if (!text || data?.localized?.wikipedia?.extract) return undefined;
		return extrasolarAllowed(text) ? text : undefined;
	});
	let translatedText = $derived(cultureText?.translations?.[getLocale()]);
	let figureCredits = $state.raw<CitedSource[]>([]);
	let groupWorkCredits = $derived.by<CitedSource[]>(() => {
		const out: CitedSource[] = [
			...(groupDetail?.global?.ring_sources ?? []),
			...(groupDetail?.global?.radiation_sources ?? [])
		].map((s) => ({
			key: s.url,
			label: s.title,
			url: s.url
		}));
		// Lineup members whose ellipsoid was fitted rather than tabulated.
		out.push(...lineup.overviewCredits.shapeWorks);
		// A star's values come from the catalogues its records name, or from
		// the papers its object entry cites; a planet's from those its file names.
		if (cultureText) {
			const { credit } = cultureText;
			out.push(
				cultureSource(credit, m.source_culture_text_note({ license: credit.license ?? '' }))
			);
			const translators = cultureText.translation_credit;
			if (translatedText && translators) {
				out.push({
					key: translators.source,
					label: [translators.organisation, translators.name].join(', '),
					url: translators.source,
					note: m.source_culture_text_note({ license: translators.license ?? '' })
				});
			}
		}
		// What draws a figure, where its text does not already name it.
		const drawnBy = groupDetail?.global?.figure_credit;
		if (drawnBy && !cultureText) {
			out.push(
				cultureSource(drawnBy, m.source_culture_figures_note({ license: drawnBy.license ?? '' }))
			);
		}
		out.push(...figureCredits);
		if (star) {
			const nodes = system ? [...system.nodes.values()] : citedNodes;
			const measured = systemRow?.star
				? radiusPaperPoint(system, systemRow, star.metadata.radius)
				: null;
			out.push(...starCredits(star, data?.global?.references, nodes, measured));
			// The centre temperature of the Interior section rests on the Structure tab's works.
			if (!systemRow && starStructure && shownCentreTemperature(starStructure)) {
				out.push(...starStructure.credits);
			}
			out.push(
				...citationCredits(
					citedNodes.flatMap((n) => [...(n.orbit?.references ?? []), ...(n.star?.references ?? [])])
				)
			);
		}
		if (planet) out.push(...planetCredits(planet.planet, exportCredits));
		if (cat.planets) out.push(...planetCatalogueCredits(exportCredits));
		if (cat.solarSystem)
			out.push({
				key: MASS_INVENTORY_URL,
				label: m.mass_budget_source(),
				url: MASS_INVENTORY_URL,
				note: m.source_mass_inventory_role()
			});
		return out;
	});
</script>

{#if load.loadError}
	<div role="alert" class="flex flex-col items-center gap-3 px-4 py-16 text-center">
		<p class="text-sm font-medium text-foreground">{m.detail_error_title()}</p>
		<p class="max-w-xs text-xs text-muted-foreground">{m.detail_error_body()}</p>
		<Button variant="secondary" size="sm" onclick={load.retry}>{m.retry()}</Button>
	</div>
{:else if load.loading}
	<PanelSkeleton />
{:else}
	<div class="flex flex-col gap-4">
		{#if actions}
			{@render actions()}
		{/if}
		{#if mapHref}
			<a
				href={mapHref}
				class="flex h-11 items-center justify-center gap-2 rounded-xl bg-foreground text-sm font-medium text-background transition-colors hover:bg-foreground/90"
			>
				<MapIcon class="size-4" />
				{m.open_in_map()}
			</a>
		{/if}
		{#if isGroupMode && groupDetail?.global}
			<GroupStatCards global={groupDetail.global} localized={groupDetail.localized} />
		{:else if feature}
			<FeatureStatCards {feature} detail={load.featureDetail} />
		{:else if star}
			<div class="flex flex-col gap-2">
				{#each systemRow ? systemStats(star, systemRow, planetCount) : starStats(star) as stats, i (i)}
					<StatCardRow {stats} />
				{/each}
			</div>
		{:else if planet}
			<div class="flex flex-col gap-2">
				{#each planetStats(planet.planet) as stats, i (i)}
					<StatCardRow {stats} />
				{/each}
			</div>
		{:else if body}
			<ObjectStats
				global={data?.global ?? null}
				{body}
				orbitElements={drawerOrbitElements}
				{parentBody}
				jd={sampledJd}
			/>
		{/if}
		<ObjectDescription
			extract={data?.localized?.wikipedia?.extract ?? translatedText ?? cultureText?.text}
			wikipediaUrl={data?.localized?.wikipedia?.url}
			lang={cultureText && !translatedText ? 'en' : undefined}
		/>
		{#if !isGroupMode}
			<BodyCrossRefs
				{body}
				{feature}
				featureType={surface.featureType}
				{data}
				{members}
				orbitElements={drawerOrbitElements}
				{planetarySystem}
				{star}
				planet={planet?.planet ?? null}
				{systemCategories}
			/>
		{/if}
		<!-- When this system's moons were found; sits under its cross-refs, which
		     are the parts of the system this counts. -->
		{#if planetarySystem.discoveryHistogram}
			<SystemDiscovery histogram={planetarySystem.discoveryHistogram} />
		{/if}
		{#if star && system && listsStars}
			<SystemStars {system} {node} star={star.id} />
		{/if}
		{#if system && node}
			<SystemPlanets hosts={systemPlanets} pageId={node.id} />
		{:else if star && hostSystem}
			<PlanetList system={hostSystem} hostId={star.id} others={!listsStars} />
		{/if}
		{#each overviewStrips as strip (strip.heading)}
			<MemberStrip
				members={strip.members}
				localizedNames={strip.localizedNames}
				totalCount={strip.totalCount}
				heading={strip.heading}
				seeAllHref={strip.seeAllHref}
				onSeeAll={strip.onSeeAll}
				alwaysSeeAll={strip.alwaysSeeAll ?? false}
				focusMovesCamera={strip.focusMovesCamera ?? true}
			/>
		{/each}
		{#if feature}
			<FeatureProperties
				{feature}
				detail={load.featureDetail}
				hostId={body?.data.id}
				hostName={body?.data.name ?? undefined}
			/>
		{:else if star}
			<StarSections
				sections={systemRow
					? systemSections(star, systemRow, system)
					: starSections(star, { structure: starStructure })}
			/>
			<Discovery
				global={data?.global ?? null}
				localized={data?.localized ?? null}
				shown={systemRefs}
			/>
			<StarConstellations id={star.id} onCredits={(credits) => (figureCredits = credits)} />
		{:else if planet}
			<PlanetSections
				sections={planetSections(planet, {
					dates: data?.global?.wikidata?.discovery_date,
					discoverers: data?.localized?.discoverers,
					sites: data?.localized?.discovery_site
				})}
			/>
		{:else if body}
			<BodySections {body} {data} orbitElements={drawerOrbitElements} {parentBody} jd={sampledJd} />
		{:else if groupSlug !== null}
			<GroupOverviewSections
				slug={groupSlug}
				{cat}
				{groupDetail}
				{members}
				{active}
				onFigureCredits={(credits) => (figureCredits = credits)}
			/>
		{/if}
		<ObjectLinks
			global={data?.global ?? null}
			localized={data?.localized ?? null}
			extraIdentifiers={linkIdentifiers}
			extraAliases={linkAliases}
		/>
		<SourcesFooter
			global={data?.global ?? null}
			works={groupWorkCredits}
			earthSat={earthSatCredit}
			nomenclature={nomenclatureCredit}
			wikipediaLicensed={!!data?.localized?.wikipedia?.extract}
			pck={lineup.overviewCredits.pck}
			lightcurvePole={lineup.overviewCredits.lightcurvePole}
			sbdb={lineup.overviewCredits.sbdb || smallBodyGroupCredit}
			wikidata={lineup.overviewCredits.wikidata}
			imagery={lineup.overviewCredits.imagery}
		/>
	</div>
{/if}

<script lang="ts">
	import { untrack } from 'svelte';
	import { Button } from '$lib/components/ui/button/index.js';
	import { Skeleton } from '$lib/components/ui/skeleton/index.js';
	import GroupStatCards from '../sections/GroupStatCards.svelte';
	import FeatureStatCards from '../sections/FeatureStatCards.svelte';
	import ObjectStats from '../sections/ObjectStats.svelte';
	import ObjectDescription from '../sections/ObjectDescription.svelte';
	import FeatureProperties from '../sections/FeatureProperties.svelte';
	import ObjectLinks from '../sections/ObjectLinks.svelte';
	import SourcesFooter, { type Source as CitedSource } from '../sections/SourcesFooter.svelte';
	import MemberStrip from '../members/MemberStrip.svelte';
	import BodyCrossRefs from './overview/BodyCrossRefs.svelte';
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
	import * as m from '$lib/paraglide/messages.js';

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
		parentBody
	}: Props = $props();

	let data = $derived(load.data);
	let groupDetail = $derived(load.groupDetail);

	// Features sit below the moons strip, above fragments and mission craft.
	let overviewStrips = $derived(
		[
			members.membersStrip,
			surface.featuresStrip,
			members.fragmentsStrip,
			members.missionStrip
		].filter((s) => s !== null)
	);

	// Probes carry a=e=i=…=0 (no osculating elements); feeding zeros to the
	// Orbital panel triggers a per-frame non-finite-elements warning, so leave it undefined here.
	let drawerOrbitElements = $derived(
		body
			? (body.orbitElements ??
					(body.data.orbitalSource === OrbitalSource.SPICE_PROBE ? undefined : body.data))
			: undefined
	);

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
	let groupWorkCredits = $derived.by<CitedSource[]>(() => {
		const out: CitedSource[] = [
			...(groupDetail?.global?.ring_sources ?? []),
			...(groupDetail?.global?.radiation_sources ?? [])
		].map((s) => ({
			key: s.url,
			label: s.title,
			url: s.url
		}));
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
	<div class="flex flex-col gap-4">
		<Skeleton class="w-full h-20" />
		<Skeleton class="w-full h-32" />
	</div>
{:else}
	<div class="flex flex-col gap-5">
		{#if isGroupMode && groupDetail?.global}
			<GroupStatCards global={groupDetail.global} />
		{:else if feature}
			<FeatureStatCards {feature} detail={load.featureDetail} />
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
			extract={data?.localized?.wikipedia?.extract}
			wikipediaUrl={data?.localized?.wikipedia?.url}
		/>
		{#if !isGroupMode}
			<BodyCrossRefs
				{body}
				{feature}
				featureType={surface.featureType}
				{data}
				{members}
				orbitElements={drawerOrbitElements}
				jd={sampledJd}
			/>
		{/if}
		{#each overviewStrips as strip (strip.heading)}
			<MemberStrip
				members={strip.members}
				localizedNames={strip.localizedNames}
				totalCount={strip.totalCount}
				heading={strip.heading}
				seeAllHref={strip.seeAllHref}
				onSeeAll={strip.onSeeAll}
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
		{:else if body}
			<BodySections {body} {data} orbitElements={drawerOrbitElements} {parentBody} jd={sampledJd} />
		{:else if groupSlug !== null}
			<GroupOverviewSections slug={groupSlug} {cat} {groupDetail} {members} />
		{/if}
		<ObjectLinks global={data?.global ?? null} localized={data?.localized ?? null} />
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

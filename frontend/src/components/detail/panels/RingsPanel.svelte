<script lang="ts">
	import RingStatCards from '../sections/RingStatCards.svelte';
	import RingCatalog from '../sections/RingCatalog.svelte';
	import BodyCategoryTile from '../sections/crossref/BodyCategoryTile.svelte';
	import SystemTile from '../sections/crossref/SystemTile.svelte';
	import SourcesFooter from '../sections/SourcesFooter.svelte';
	import { CAT_RING_SYSTEMS } from '$lib/fetch/groups/registry';
	import { ObjectType, type PositionedBody } from '$lib/types/objects';
	import type { ObjectDetailData } from '$lib/fetch/objects/object-data';
	import type { SimClock } from '$lib/scene/state/clock.svelte';
	import type { PlanetarySystemState } from '../charts/planetary-system.svelte';

	interface Props {
		// The drawer's own derivation — the same one that gates this tab, so the
		// tab and its content can't disagree on ring eligibility.
		ringFeatures: NonNullable<ObjectDetailData['global']>['ring_features'] | undefined;
		data: ObjectDetailData | null;
		body: PositionedBody | null;
		parentBody: PositionedBody | undefined;
		clock: SimClock;
		planetarySystem: PlanetarySystemState;
	}

	let { ringFeatures, data, body, parentBody, clock, planetarySystem }: Props = $props();
	// The ringed small bodies orbit the Sun directly, so they have no system to
	// point at and the ring-systems tile keeps the row to itself.
	let system = $derived(planetarySystem.system);
	let systemId = $derived(planetarySystem.systemId);
	let systemName = $derived(planetarySystem.systemName);
	let hasSystem = $derived(!!system && !!systemId && !!systemName);
	// Host for the chart's moon column: a planet's moons parent on the system
	// barycentre, a minor planet's on the body itself (never the Sun's whole catalogue).
	let ringMoonHostId = $derived(
		parentBody?.data.objectType === ObjectType.BARYCENTER ? parentBody.data.id : body?.data.id
	);
	// Credits for the Rings tab alone: the catalogue's tables, plus whatever
	// prose and names this locale actually got.
	let ringCredits = $derived(
		(data?.global?.ring_sources ?? []).map((s) => ({ key: s.url, label: s.title, url: s.url }))
	);
	let ringLocalized = $derived(Object.values(data?.localized?.ring_features ?? {}));
	let ringProseFromWikipedia = $derived(
		!!data?.localized?.ring_system?.extract || ringLocalized.some((f) => f.extract)
	);
	// Feature names come from Wikidata labels outside English, where the
	// catalogue's own names are used.
	let ringNamesLocalized = $derived(ringLocalized.some((f) => f.name));
</script>

<div class="flex flex-col gap-4">
	{#if ringFeatures}
		<!-- System-wide, so it sits above the chart rather than inside it:
		     these three do not change as you drill into a ring. -->
		<RingStatCards stats={data?.global?.ring_stats} />
		<RingCatalog
			features={ringFeatures}
			localized={data?.localized?.ring_features}
			system={data?.localized?.ring_system}
			bodyRadiusKm={data?.global?.radii?.a}
			bodyId={body?.data.id}
			systemId={ringMoonHostId}
			{clock}
		/>
		<!-- The way back out: to the other ringed bodies, and to the system these
		     rings are part of — this tab is where a visitor finds both. -->
		<div class="grid grid-cols-2 gap-2">
			<BodyCategoryTile slug={CAT_RING_SYSTEMS} class={hasSystem ? '' : 'col-span-2'} />
			{#if hasSystem}
				<SystemTile systemId={systemId!} system={system!} name={systemName!} />
			{/if}
		</div>
		<SourcesFooter
			global={null}
			works={ringCredits}
			wikidata={ringNamesLocalized}
			wikipediaLicensed={ringProseFromWikipedia}
		/>
	{/if}
</div>

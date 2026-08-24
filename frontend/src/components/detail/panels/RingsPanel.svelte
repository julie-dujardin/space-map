<script lang="ts">
	import RingStatCards from '../sections/RingStatCards.svelte';
	import RingCatalog from '../sections/RingCatalog.svelte';
	import BodyCategoryTile from '../sections/crossref/BodyCategoryTile.svelte';
	import SourcesFooter from '../sections/SourcesFooter.svelte';
	import { CAT_RING_SYSTEMS } from '$lib/fetch/groups/registry';
	import { ObjectType, type PositionedBody } from '$lib/types/objects';
	import type { ObjectDetailData } from '$lib/fetch/objects/object-data';
	import type { SimClock } from '$lib/scene/state/clock.svelte';

	interface Props {
		// The drawer's own derivation — the same one that gates this tab, so the
		// tab and its content can't disagree on ring eligibility.
		ringFeatures: NonNullable<ObjectDetailData['global']>['ring_features'] | undefined;
		data: ObjectDetailData | null;
		body: PositionedBody | null;
		parentBody: PositionedBody | undefined;
		clock: SimClock;
	}

	let { ringFeatures, data, body, parentBody, clock }: Props = $props();
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
		<!-- The way back out to the other ringed bodies: this tab is where a
		     visitor finds out there are rings to compare. -->
		<BodyCategoryTile slug={CAT_RING_SYSTEMS} />
		<SourcesFooter
			global={null}
			works={ringCredits}
			wikidata={ringNamesLocalized}
			wikipediaLicensed={ringProseFromWikipedia}
		/>
	{/if}
</div>

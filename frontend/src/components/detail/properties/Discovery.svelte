<script lang="ts">
	import * as m from '$lib/paraglide/messages.js';
	import type { GlobalObjectData, LocalizedObjectData } from '$lib/fetch/objects/object-data';
	import { formatWikidataDate } from '$lib/format/date';
	import Section from './Section.svelte';
	import Row from './Row.svelte';
	import EntityLinks from './EntityLinks.svelte';

	interface Props {
		global: GlobalObjectData | null;
		localized: LocalizedObjectData | null;
	}

	let { global, localized }: Props = $props();

	let isSpacecraft = $derived(global?.type === 'spacecraft' || global?.type === 'debris');
	let discoveryDate = $derived(global?.wikidata?.discovery_date?.[0] ?? global?.sbdb?.first_obs);
	let discoverers = $derived(localized?.discoverers);
	let discoverySite = $derived(localized?.discovery_site);
	let minorPlanetGroup = $derived(localized?.minor_planet_group);
	let asteroidFamily = $derived(localized?.asteroid_family);
	let orbitClass = $derived(global?.sbdb?.class);
	let cometPrefix = $derived(global?.sbdb?.prefix);
	let sats = $derived(global?.sbdb?.sats);
	let partOf = $derived(localized?.part_of);
	let namedAfter = $derived(localized?.named_after);

	let hasContent = $derived(
		!isSpacecraft &&
			(discoveryDate ||
				discoverers ||
				discoverySite ||
				minorPlanetGroup ||
				asteroidFamily ||
				orbitClass ||
				cometPrefix ||
				partOf ||
				namedAfter)
	);
</script>

{#if hasContent}
	<Section title={m.discovery()}>
		{#if discoveryDate}
			<Row label={m.first_observed()} value={formatWikidataDate(discoveryDate)} />
		{/if}
		{#if discoverers && discoverers.length > 0}
			<Row label={discoverers.length > 1 ? m.discoverers() : m.discoverer()}>
				<EntityLinks entities={discoverers} />
			</Row>
		{/if}
		{#if discoverySite && discoverySite.length > 0}
			<Row label={m.discovery_site()}>
				<EntityLinks entities={discoverySite} />
			</Row>
		{/if}
		{#if namedAfter && namedAfter.length > 0}
			<Row label={m.property_name_named_after()}>
				<EntityLinks entities={namedAfter} />
			</Row>
		{/if}
		{#if orbitClass}
			<Row label={m.orbit_class()} tooltip={m.tooltip_orbit_class()} value={orbitClass} />
		{/if}
		{#if cometPrefix}
			<Row label={m.comet_type()} value={cometPrefix} />
		{/if}
		{#if minorPlanetGroup && minorPlanetGroup.length > 0}
			<Row label={m.property_name_minor_planet_group()}>
				<EntityLinks entities={minorPlanetGroup} />
			</Row>
		{/if}
		{#if asteroidFamily}
			<Row label={m.property_name_asteroid_family()}>
				<EntityLinks entities={[asteroidFamily]} />
			</Row>
		{/if}
		{#if sats != null && sats > 0}
			<Row
				label={m.known_satellites()}
				tooltip={m.tooltip_known_satellites()}
				value={String(sats)}
			/>
		{/if}
		{#if partOf && partOf.length > 0}
			<Row label={m.property_name_part_of()}>
				<EntityLinks entities={partOf} />
			</Row>
		{/if}
	</Section>
{/if}

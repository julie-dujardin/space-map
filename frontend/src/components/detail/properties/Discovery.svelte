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
	let asteroidFamily = $derived(localized?.asteroid_family);
	let partOf = $derived(localized?.part_of);
	let namedAfter = $derived(localized?.named_after);

	let hasContent = $derived(
		!isSpacecraft &&
			(discoveryDate || discoverers || discoverySite || asteroidFamily || partOf || namedAfter)
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
		{#if asteroidFamily}
			<Row label={m.property_name_asteroid_family()}>
				<EntityLinks entities={[asteroidFamily]} />
			</Row>
		{/if}
		{#if partOf && partOf.length > 0}
			<Row label={m.property_name_part_of()}>
				<EntityLinks entities={partOf} />
			</Row>
		{/if}
	</Section>
{/if}

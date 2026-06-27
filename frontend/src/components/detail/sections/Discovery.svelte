<script lang="ts">
	import * as m from '$lib/paraglide/messages.js';
	import type { GlobalObjectData, LocalizedObjectData } from '$lib/fetch/objects/object-data';
	import { formatIsoDate, parseIsoDate } from '$lib/format/date';
	import Section from './kit/Section.svelte';
	import Row from './kit/Row.svelte';
	import EntityLinks from './kit/EntityLinks.svelte';

	interface Props {
		global: GlobalObjectData | null;
		localized: LocalizedObjectData | null;
	}

	let { global, localized }: Props = $props();

	let isSpacecraft = $derived(global?.type === 'spacecraft' || global?.type === 'debris');
	let discoveryDate = $derived(
		[...(global?.wikidata?.discovery_date ?? []), global?.sbdb?.first_obs]
			.filter((d): d is string => !!d)
			.sort((a, b) => {
				const ta = parseIsoDate(a)?.date.getTime() ?? Infinity;
				const tb = parseIsoDate(b)?.date.getTime() ?? Infinity;
				return ta - tb;
			})[0]
	);
	let discoverers = $derived(localized?.discoverers);
	let discoverySite = $derived(localized?.discovery_site);
	let asteroidFamily = $derived(localized?.asteroid_family);
	let partOf = $derived(localized?.part_of);
	let namedAfter = $derived(localized?.named_after);

	let hasFields = $derived(
		!!(discoveryDate || discoverers || discoverySite || asteroidFamily || partOf || namedAfter)
	);
	let hasContent = $derived(!isSpacecraft && hasFields);
</script>

{#if hasContent}
	<Section title={m.discovery()}>
		{#if discoveryDate}
			<Row label={m.first_observed()} value={formatIsoDate(discoveryDate)} />
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

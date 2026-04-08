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

	let launchDate = $derived(global?.wikidata?.launch_date);
	let operator = $derived(localized?.operator);
	let manufacturer = $derived(localized?.manufacturer);
	let launchVehicle = $derived(localized?.launch_vehicle);
	let launchSite = $derived(localized?.launch_site);

	let hasContent = $derived(launchDate || operator || manufacturer || launchVehicle || launchSite);
</script>

{#if hasContent}
	<Section title={m.mission()}>
		{#if launchDate}
			<Row label={m.launch_date()} value={formatWikidataDate(launchDate)} />
		{/if}
		{#if operator && operator.length > 0}
			<Row label={m.property_name_operator()}>
				<EntityLinks entities={operator} />
			</Row>
		{/if}
		{#if manufacturer && manufacturer.length > 0}
			<Row label={m.property_name_manufacturer()}>
				<EntityLinks entities={manufacturer} />
			</Row>
		{/if}
		{#if launchVehicle}
			<Row label={m.launch_vehicle()}>
				<EntityLinks entities={[launchVehicle]} />
			</Row>
		{/if}
		{#if launchSite && launchSite.length > 0}
			<Row label={m.launch_site()}>
				<EntityLinks entities={launchSite} />
			</Row>
		{/if}
	</Section>
{/if}

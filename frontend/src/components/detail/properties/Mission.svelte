<script lang="ts">
	import * as m from '$lib/paraglide/messages.js';
	import type { GlobalObjectData, LocalizedObjectData } from '$lib/fetch/objects/object-data';
	import { formatWikidataDate } from '$lib/format/date';
	import { formatCurrency } from '$lib/format/quantities';
	import Section from './Section.svelte';
	import Row from './Row.svelte';
	import EntityLinks from './EntityLinks.svelte';

	interface Props {
		global: GlobalObjectData | null;
		localized: LocalizedObjectData | null;
	}

	let { global, localized }: Props = $props();

	let isSpacecraft = $derived(global?.type === 'spacecraft' || global?.type === 'debris');
	let capitalCost = $derived(global?.wikidata?.capital_cost);
	let launchDate = $derived(global?.wikidata?.launch_date ?? global?.celestrak?.launch_date);
	let decayDate = $derived(global?.celestrak?.decay_date);
	let operators = $derived(localized?.operators);
	let manufacturer = $derived(localized?.manufacturer);
	let developer = $derived(localized?.developer);
	let funder = $derived(localized?.funder);
	let countryOfOrigin = $derived(localized?.country_of_origin);
	let launchContractor = $derived(localized?.launch_contractor);
	let launchVehicle = $derived(localized?.launch_vehicle);
	let launchSite = $derived(localized?.launch_site);
	let namedAfter = $derived(localized?.named_after);
	let partOf = $derived(localized?.part_of);

	let hasContent = $derived(
		isSpacecraft &&
			(launchDate ||
				decayDate ||
				operators ||
				manufacturer ||
				developer ||
				funder ||
				countryOfOrigin ||
				launchContractor ||
				launchVehicle ||
				launchSite ||
				namedAfter ||
				partOf ||
				capitalCost)
	);
</script>

{#if hasContent}
	<Section title={m.mission()}>
		{#if launchDate}
			<Row label={m.launch_date()} value={formatWikidataDate(launchDate)} />
		{/if}
		{#if decayDate}
			<Row label={m.decay_date()} value={formatWikidataDate(decayDate)} />
		{/if}
		{#if operators && operators.length > 0}
			<Row label={m.property_name_operators()}>
				<EntityLinks entities={operators} />
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
		{#if launchContractor && launchContractor.length > 0}
			<Row label={m.property_name_launch_contractor()}>
				<EntityLinks entities={launchContractor} />
			</Row>
		{/if}
		{#if launchSite && launchSite.length > 0}
			<Row label={m.launch_site()}>
				<EntityLinks entities={launchSite} />
			</Row>
		{/if}
		{#if developer && developer.length > 0}
			<Row label={m.property_name_developer()}>
				<EntityLinks entities={developer} />
			</Row>
		{/if}
		{#if funder && funder.length > 0}
			<Row label={m.property_name_funder()}>
				<EntityLinks entities={funder} />
			</Row>
		{/if}
		{#if countryOfOrigin && countryOfOrigin.length > 0}
			<Row label={m.property_name_country_of_origin()}>
				<EntityLinks entities={countryOfOrigin} />
			</Row>
		{/if}
		{#if namedAfter && namedAfter.length > 0}
			<Row label={m.property_name_named_after()}>
				<EntityLinks entities={namedAfter} />
			</Row>
		{/if}
		{#if partOf && partOf.length > 0}
			<Row label={m.property_name_part_of()}>
				<EntityLinks entities={partOf} />
			</Row>
		{/if}
		{#if capitalCost}
			<Row label={m.property_name_capital_cost()} value={formatCurrency(capitalCost)} />
		{/if}
	</Section>
{/if}

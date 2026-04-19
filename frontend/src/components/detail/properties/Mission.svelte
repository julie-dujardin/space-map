<script lang="ts">
	import * as m from '$lib/paraglide/messages.js';
	import type {
		GlobalObjectData,
		LocalizedObjectData,
		EntityRef
	} from '$lib/fetch/objects/object-data';
	import { formatIsoDate } from '$lib/format/date';
	import { formatCurrency, formatNumber } from '$lib/format/quantities';
	import { countryFlag, formatCountry, formatOpsStatus } from '$lib/format/satellite';
	import Section from './Section.svelte';
	import Row from './Row.svelte';
	import EntityLinks from './EntityLinks.svelte';

	interface Props {
		global: GlobalObjectData | null;
		localized: LocalizedObjectData | null;
	}

	let { global, localized }: Props = $props();

	let isSpacecraft = $derived(global?.type === 'spacecraft' || global?.type === 'debris');
	let ct = $derived(global?.celestrak);
	let orbitsEarth = $derived(ct?.orbit_center === 'earth');
	let capitalCost = $derived(global?.wikidata?.capital_cost);
	let launchDate = $derived(global?.wikidata?.launch_date ?? ct?.launch_date);
	let decayDate = $derived(ct?.decay_date);
	let operators = $derived(localized?.operators);
	let manufacturer = $derived(localized?.manufacturer);
	let developer = $derived(localized?.developer);
	let funder = $derived(localized?.funder);
	let countryOfOrigin = $derived(localized?.country_of_origin);
	let launchContractor = $derived(localized?.launch_contractor);
	let launchVehicle = $derived(localized?.launch_vehicle);
	let launchSite = $derived(localized?.launch_site);
	let namedAfter = $derived(localized?.named_after);
	let countries = $derived(ct?.country_codes ?? []);

	/** Merge constellation + part_of, deduplicated by wikipedia URL. */
	let mergedPartOf = $derived.by(() => {
		const parts: EntityRef[] = [];
		const seen = new Set<string>();
		function add(e: EntityRef) {
			const key = e.wikipedia ?? e.name;
			if (!seen.has(key)) {
				seen.add(key);
				parts.push(e);
			}
		}
		if (localized?.constellation) add(localized.constellation);
		if (localized?.part_of) localized.part_of.forEach(add);
		return parts;
	});

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
				mergedPartOf.length > 0 ||
				capitalCost ||
				ct?.ops_status ||
				ct?.rcs != null ||
				countries.length > 0)
	);
</script>

{#if hasContent}
	<Section title={orbitsEarth ? m.satellite() : m.mission()}>
		{#if mergedPartOf.length > 0}
			<Row label={m.property_name_part_of()}>
				<EntityLinks entities={mergedPartOf} />
			</Row>
		{/if}
		{#if ct?.ops_status}
			<Row label={m.ops_status()} value={formatOpsStatus(ct.ops_status)} />
		{/if}
		{#if launchDate}
			<Row label={m.launch_date()} value={formatIsoDate(launchDate)} />
		{/if}
		{#if decayDate}
			<Row label={m.decay_date()} value={formatIsoDate(decayDate)} />
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
		{#if capitalCost}
			<Row label={m.property_name_capital_cost()} value={formatCurrency(capitalCost)} />
		{/if}
		{#if ct?.rcs != null}
			<Row label={m.rcs()} value={`${formatNumber(ct.rcs)} m²`} tooltip={m.tooltip_rcs()} />
		{/if}
		{#if countries.length > 0}
			<Row label={countries.length === 1 ? m.country() : m.countries()}>
				<span class="flex flex-wrap justify-end gap-1.5">
					{#each countries as cc (cc)}
						<span title={cc}>{countryFlag(cc)} {formatCountry(cc)}</span>
					{/each}
				</span>
			</Row>
		{/if}
	</Section>
{/if}

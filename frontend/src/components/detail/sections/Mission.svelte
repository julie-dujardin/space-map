<script lang="ts">
	import Link from './kit/Link.svelte';
	import { getContext } from 'svelte';
	import * as m from '$lib/paraglide/messages.js';
	import type {
		GlobalObjectData,
		LocalizedObjectData,
		EntityRef
	} from '$lib/fetch/objects/object-data';
	import { formatIsoDate } from '$lib/format/date';
	import { formatCurrency, formatNumber } from '$lib/format/quantities';
	import { countryFlag, formatCountry, formatOpsStatus } from '$lib/format/satellite';
	import { sameRef } from '$lib/format/entity-refs';
	import type { AppState } from '$lib/state/app-state.svelte';
	import { applyGroup, serializeUrl } from '$lib/state/url';
	import Section from './kit/Section.svelte';
	import Row from './kit/Row.svelte';
	import EntityLinks from './kit/EntityLinks.svelte';

	const appState = getContext<AppState | undefined>('appState');

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
	let bus = $derived(localized?.bus);
	let developer = $derived(localized?.developer);
	let funder = $derived(localized?.funder);
	let countryOfOrigin = $derived(localized?.country_of_origin);
	let launchContractor = $derived(localized?.launch_contractor);
	let launchVehicle = $derived(localized?.launch_vehicle);
	let launchSite = $derived(localized?.launch_site);
	let namedAfter = $derived(localized?.named_after);
	let countries = $derived(ct?.country_codes ?? []);

	/** Constellation + part_of as one row, each thing once, and never the
	 *  object itself (a station whose catalogue row is its first module). */
	let mergedPartOf = $derived.by(() => {
		const self: EntityRef = { name: localized?.name ?? '', wikipedia: localized?.wikipedia?.url };
		const parts: EntityRef[] = [];
		for (const e of [localized?.constellation, ...(localized?.part_of ?? [])]) {
			if (e && !sameRef(e, self) && !parts.some((p) => sameRef(p, e))) parts.push(e);
		}
		return parts;
	});

	// GCAT files a craft that reached another world under "decayed", with the
	// landing day as its decay date; the curated record says which it was.
	let landed = $derived(ct?.ops_status === 'decayed' && global?.events?.status.where === 'landed');

	let hasFields = $derived(
		!!(
			launchDate ||
			decayDate ||
			operators ||
			manufacturer ||
			bus ||
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
			countries.length > 0
		)
	);
	let hasContent = $derived(isSpacecraft && hasFields);

	function countryGroupHref(cc: string, name: string): string | undefined {
		if (!appState) return undefined;
		return serializeUrl(applyGroup(appState.view, `country-${cc.toLowerCase()}`, name));
	}

	function handleCountryClick(e: MouseEvent, cc: string, name: string) {
		if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
		if (!appState) return;
		e.preventDefault();
		appState.setGroup(`country-${cc.toLowerCase()}`, name);
	}
</script>

{#if hasContent}
	<Section title={orbitsEarth ? m.satellite() : m.mission()}>
		{#if mergedPartOf.length > 0}
			<Row label={m.property_name_part_of()}>
				<EntityLinks entities={mergedPartOf} />
			</Row>
		{/if}
		{#if ct?.ops_status}
			<Row
				label={m.ops_status()}
				value={landed ? m.ops_status_landed() : formatOpsStatus(ct.ops_status)}
			/>
		{/if}
		{#if launchDate}
			<Row label={m.launch_date()} value={formatIsoDate(launchDate)} />
		{/if}
		{#if decayDate}
			<Row label={landed ? m.landing_date() : m.decay_date()} value={formatIsoDate(decayDate)} />
		{/if}
		{#if operators && operators.length > 0}
			<Row label={m.property_name_operators({ count: operators.length })}>
				<EntityLinks entities={operators} />
			</Row>
		{/if}
		{#if manufacturer && manufacturer.length > 0}
			<Row label={m.property_name_manufacturer({ count: manufacturer.length })}>
				<EntityLinks entities={manufacturer} />
			</Row>
		{/if}
		{#if bus}
			<Row label={m.group_type_bus()}>
				<EntityLinks entities={[bus]} />
			</Row>
		{/if}
		{#if launchVehicle}
			<Row label={m.launch_vehicle()}>
				<EntityLinks entities={[launchVehicle]} />
			</Row>
		{/if}
		{#if launchContractor && launchContractor.length > 0}
			<Row label={m.property_name_launch_contractor({ count: launchContractor.length })}>
				<EntityLinks entities={launchContractor} />
			</Row>
		{/if}
		{#if launchSite && launchSite.length > 0}
			<Row label={m.launch_site()}>
				<EntityLinks entities={launchSite} />
			</Row>
		{/if}
		{#if developer && developer.length > 0}
			<Row label={m.property_name_developer({ count: developer.length })}>
				<EntityLinks entities={developer} />
			</Row>
		{/if}
		{#if funder && funder.length > 0}
			<Row label={m.property_name_funder({ count: funder.length })}>
				<EntityLinks entities={funder} />
			</Row>
		{/if}
		<!-- Wikidata's country only where GCAT has no owner codes: they name the
		     same country, and the flags row below links to the country pages. -->
		{#if countryOfOrigin && countryOfOrigin.length > 0 && countries.length === 0}
			<Row label={m.property_name_country_of_origin({ count: countryOfOrigin.length })}>
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
			<Row label={m.country_count({ count: countries.length })}>
				<span class="flex flex-wrap justify-end gap-1.5">
					{#each countries as cc (cc)}
						{@const name = formatCountry(cc)}
						<span title={cc}
							>{countryFlag(cc)}
							{#if appState}
								<Link
									href={countryGroupHref(cc, name)}
									onclick={(e) => handleCountryClick(e, cc, name)}>{name}</Link
								>
							{:else}
								{name}
							{/if}</span
						>
					{/each}
				</span>
			</Row>
		{/if}
	</Section>
{/if}

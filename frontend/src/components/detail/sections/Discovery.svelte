<script lang="ts">
	import * as m from '$lib/paraglide/messages.js';
	import { withoutRefs } from '$lib/format/entity-refs';
	import type {
		EntityRef,
		GlobalObjectData,
		LocalizedObjectData
	} from '$lib/fetch/objects/object-data';
	import { earliestDate, formatIsoDate, sameYearDate } from '$lib/format/date';
	import Section from './kit/Section.svelte';
	import Row from './kit/Row.svelte';
	import EntityLinks from './kit/EntityLinks.svelte';

	interface Props {
		global: GlobalObjectData | null;
		localized: LocalizedObjectData | null;
		/** What another part of the panel names, so that "Part of" leaves it out. */
		shown?: readonly EntityRef[];
	}

	let { global, localized, shown = [] }: Props = $props();

	let isSpacecraft = $derived(global?.type === 'spacecraft' || global?.type === 'debris');

	// JPL `discovery_year` is authoritative for natural moons (drives the render
	// gate). Bodies without a JPL year fall back to the earliest date.
	function pickDiscoveryDate(g: GlobalObjectData | null): string | undefined {
		const wdDates = g?.wikidata?.discovery_date ?? [];
		if (g?.discovery_year != null) return sameYearDate(g.discovery_year, wdDates);
		return earliestDate([...wdDates, g?.sbdb?.first_obs].filter((d): d is string => !!d));
	}

	// Asteroid moons have almost no Wikidata item, so their whole discovery
	// record is Johnston's: who found the companion, with what, from where,
	// and when it was announced. Used only where Wikidata is silent.
	let johnston = $derived(global?.johnston);

	let discoveryDate = $derived(pickDiscoveryDate(global));
	let discoverers = $derived(localized?.discoverers);
	let discoverySite = $derived(localized?.discovery_site);
	let asteroidFamily = $derived(localized?.asteroid_family);
	let partOf = $derived(
		withoutRefs(localized?.part_of, asteroidFamily ? [asteroidFamily, ...shown] : shown)
	);
	let namedAfter = $derived(localized?.named_after);

	let johnstonDate = $derived(discoveryDate ? undefined : johnston?.discovery_date);
	// The archive dates the announcement as well as the discovery, days to
	// years apart. Both answer "when was this found", so the announcement is
	// only worth a row where no discovery date is known.
	let hasFirstObserved = $derived(!!(discoveryDate || johnstonDate));
	let announced = $derived(hasFirstObserved ? undefined : johnston?.announced);
	let johnstonDiscoverers = $derived(
		discoverers && discoverers.length > 0 ? undefined : johnston?.discoverers
	);
	let johnstonFacility = $derived(
		discoverySite && discoverySite.length > 0 ? undefined : johnston?.discovery_facility
	);

	let hasFields = $derived(
		!!(
			discoveryDate ||
			discoverers ||
			discoverySite ||
			asteroidFamily ||
			partOf.length > 0 ||
			namedAfter ||
			johnstonDate ||
			johnstonDiscoverers ||
			johnstonFacility ||
			johnston?.discovery_method ||
			announced
		)
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
		{#if johnstonDate}
			<Row label={m.first_observed()} value={formatIsoDate(johnstonDate)} />
		{/if}
		{#if johnstonDiscoverers}
			<Row label={m.discoverers()} value={johnstonDiscoverers} />
		{/if}
		{#if discoverySite && discoverySite.length > 0}
			<Row label={m.discovery_site()}>
				<EntityLinks entities={discoverySite} />
			</Row>
		{/if}
		{#if johnstonFacility}
			<Row label={m.discovery_site()} value={johnstonFacility} />
		{/if}
		{#if johnston?.discovery_method}
			<Row
				label={m.discovery_method()}
				value={johnston.discovery_method}
				tooltip={m.tooltip_discovery_method()}
			/>
		{/if}
		{#if announced}
			<Row label={m.discovery_announcement()} value={formatIsoDate(announced)} />
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
		{#if partOf.length > 0}
			<Row label={m.property_name_part_of()}>
				<EntityLinks entities={partOf} />
			</Row>
		{/if}
	</Section>
{/if}

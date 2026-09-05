<script lang="ts">
	import * as m from '$lib/paraglide/messages.js';
	import { withoutRefs } from '$lib/format/entity-refs';
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

	// JPL `discovery_year` is authoritative for natural moons (drives the render
	// gate); a Wikidata date is shown only when its year agrees, upgrading to
	// day precision. Bodies without a JPL year fall back to the earliest date.
	function pickDiscoveryDate(g: GlobalObjectData | null): string | undefined {
		const wdDates = g?.wikidata?.discovery_date ?? [];
		const jplYear = g?.discovery_year;
		if (jplYear != null) {
			const agreeing = wdDates.find((d) => parseIsoDate(d)?.date.getUTCFullYear() === jplYear);
			return agreeing ?? String(jplYear);
		}
		return [...wdDates, g?.sbdb?.first_obs]
			.filter((d): d is string => !!d)
			.sort((a, b) => {
				const ta = parseIsoDate(a)?.date.getTime() ?? Infinity;
				const tb = parseIsoDate(b)?.date.getTime() ?? Infinity;
				return ta - tb;
			})[0];
	}

	// Asteroid moons have almost no Wikidata item, so their whole discovery
	// record is Johnston's: who found the companion, with what, from where,
	// and when it was announced. Used only where Wikidata is silent.
	let johnston = $derived(global?.johnston);

	let discoveryDate = $derived(pickDiscoveryDate(global));
	let discoverers = $derived(localized?.discoverers);
	let discoverySite = $derived(localized?.discovery_site);
	let asteroidFamily = $derived(localized?.asteroid_family);
	let partOf = $derived(withoutRefs(localized?.part_of, asteroidFamily ? [asteroidFamily] : []));
	let namedAfter = $derived(localized?.named_after);

	// Printed as the archive writes it ("2001 Aug 29") — not an ISO date, and
	// pinning a day to a month it may not state would invent precision.
	let johnstonDate = $derived(discoveryDate ? undefined : johnston?.discovery_date);
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
			johnston?.announced
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
			<Row label={m.first_observed()} value={johnstonDate} />
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
		{#if johnston?.announced}
			<Row label={m.discovery_announcement()} value={johnston.announced} />
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

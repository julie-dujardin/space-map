<script lang="ts">
	import type { NomenclatureFeature } from '$lib/fetch/nomenclature/fetch';
	import type { FeatureDetailData } from '$lib/fetch/nomenclature/details';
	import { nomenclatureTypeLabel } from '$lib/types/nomenclature';
	import { formatNumber, formatQuantity, formatUnit } from '$lib/format/quantities';
	import { formatIsoDate } from '$lib/format/date';
	import * as m from '$lib/paraglide/messages.js';
	import Section from './Section.svelte';
	import Row from './Row.svelte';
	import EntityLinks from './EntityLinks.svelte';

	interface Props {
		feature: NomenclatureFeature;
		detail: FeatureDetailData | null;
	}

	let { feature, detail }: Props = $props();

	let wd = $derived(detail?.global?.wikidata);
	let loc = $derived(detail?.localized);

	let typeLabel = $derived(nomenclatureTypeLabel(feature.typeCode));
	let diameterText = $derived.by(() => {
		if (!feature.diameterM || feature.diameterM <= 0) return null;
		// IAU diameters span metres (small craters) to thousands of km (maria),
		// so flip to km once the value is sub-precise in metres.
		if (feature.diameterM >= 1000) {
			return `${formatNumber(feature.diameterM / 1000)} ${formatUnit('kilometre')}`;
		}
		return `${formatNumber(feature.diameterM)} ${formatUnit('metre')}`;
	});
	let coordsText = $derived(`${formatNumber(feature.lat)}°, ${formatNumber(feature.lon)}°`);
</script>

<Section title="Surface feature">
	<Row label="Type" value={typeLabel} />
	<Row label="Coordinates" value={coordsText} />
	{#if diameterText}
		<Row label="Diameter" value={diameterText} />
	{/if}
	{#if wd?.vertical_depth}
		<Row label="Depth" value={formatQuantity(wd.vertical_depth)} />
	{/if}
	{#if wd?.length}
		<Row label={m.property_name_length()} value={formatQuantity(wd.length)} />
	{/if}
	{#if wd?.width}
		<Row label={m.property_name_width()} value={formatQuantity(wd.width)} />
	{/if}
	{#if wd?.height}
		<Row label="Height" value={formatQuantity(wd.height)} />
	{/if}
	{#if wd?.area}
		<Row label="Area" value={formatQuantity(wd.area)} />
	{/if}
	{#if wd?.elevation}
		<Row label="Elevation" value={formatQuantity(wd.elevation)} />
	{/if}
	{#if feature.approvalDate}
		<Row label="Named" value={formatIsoDate(feature.approvalDate)} />
	{/if}
	{#if feature.origin}
		<Row label="Origin">
			<span class="block whitespace-normal text-end">{feature.origin}</span>
		</Row>
	{/if}
	{#if loc?.named_after?.length}
		<Row label={m.property_name_named_after()}>
			<EntityLinks entities={loc.named_after} />
		</Row>
	{/if}
	{#if loc?.location?.length}
		<Row label="Region">
			<EntityLinks entities={loc.location} />
		</Row>
	{/if}
	{#if loc?.located_on_physical_feature}
		<Row label="Located on">
			<EntityLinks entities={[loc.located_on_physical_feature]} />
		</Row>
	{/if}
</Section>

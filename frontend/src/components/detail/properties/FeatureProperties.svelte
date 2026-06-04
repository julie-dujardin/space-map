<script lang="ts">
	import type { NomenclatureFeature } from '$lib/fetch/nomenclature/fetch';
	import { nomenclatureTypeLabel } from '$lib/types/nomenclature';
	import { formatNumber, formatUnit } from '$lib/format/quantities';
	import Section from './Section.svelte';
	import Row from './Row.svelte';

	interface Props {
		feature: NomenclatureFeature;
	}

	let { feature }: Props = $props();

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
	{#if feature.approvalDate}
		<Row label="Named" value={feature.approvalDate} />
	{/if}
	{#if feature.origin}
		<Row label="Origin">
			<span class="block whitespace-normal text-end">{feature.origin}</span>
		</Row>
	{/if}
</Section>

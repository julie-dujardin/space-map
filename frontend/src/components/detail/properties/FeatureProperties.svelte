<script lang="ts">
	import type { NomenclatureFeature } from '$lib/fetch/nomenclature/fetch';
	import type { FeatureDetailData } from '$lib/fetch/nomenclature/details';
	import { nomenclatureTypeDescription, nomenclatureTypeLabel } from '$lib/types/nomenclature';
	import { formatNumber, formatQuantity, formatUnit } from '$lib/format/quantities';
	import { formatIsoDate } from '$lib/format/date';
	import * as m from '$lib/paraglide/messages.js';
	import * as Tooltip from '$lib/components/ui/tooltip/index.js';
	import Section from './Section.svelte';
	import Row from './Row.svelte';
	import EntityLinks from './EntityLinks.svelte';

	interface Props {
		feature: NomenclatureFeature;
		detail: FeatureDetailData | null;
	}

	let { feature, detail }: Props = $props();

	let glb = $derived(detail?.global);
	let wd = $derived(detail?.global?.wikidata);
	let loc = $derived(detail?.localized);

	let typeLabel = $derived(nomenclatureTypeLabel(feature.typeCode));
	let typeDescription = $derived(nomenclatureTypeDescription(feature.typeCode));
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

<Section title={m.surface_feature()}>
	<Row label={m.feature_type()}>
		{#if typeDescription}
			<Tooltip.Root>
				<Tooltip.Trigger>
					{#snippet child({ props })}
						<span class="cursor-help decoration-dotted underline underline-offset-2" {...props}>
							{typeLabel}
						</span>
					{/snippet}
				</Tooltip.Trigger>
				<Tooltip.Content>{typeDescription}</Tooltip.Content>
			</Tooltip.Root>
		{:else}
			{typeLabel}
		{/if}
	</Row>
	<Row label={m.coordinates()} value={coordsText} />
	{#if diameterText}
		<Row label={m.diameter()} value={diameterText} />
	{/if}
	{#if wd?.vertical_depth}
		<Row label={m.feature_depth()} value={formatQuantity(wd.vertical_depth)} />
	{/if}
	{#if wd?.length}
		<Row label={m.property_name_length()} value={formatQuantity(wd.length)} />
	{/if}
	{#if wd?.width}
		<Row label={m.property_name_width()} value={formatQuantity(wd.width)} />
	{/if}
	{#if wd?.height}
		<Row label={m.feature_height()} value={formatQuantity(wd.height)} />
	{/if}
	{#if wd?.area}
		<Row label={m.feature_area()} value={formatQuantity(wd.area)} />
	{/if}
	{#if wd?.elevation}
		<Row label={m.feature_elevation()} value={formatQuantity(wd.elevation)} />
	{/if}
	{#if feature.approvalDate}
		<Row label={m.feature_named_date()} value={formatIsoDate(feature.approvalDate)} />
	{/if}
	{#if feature.origin}
		<Row label={m.feature_origin()}>
			<span class="block whitespace-normal text-end">{feature.origin}</span>
		</Row>
	{/if}
	{#if loc?.named_after?.length}
		<Row label={m.property_name_named_after()}>
			<EntityLinks entities={loc.named_after} />
		</Row>
	{/if}
	{#if glb?.parent_feature}
		<Row label={m.feature_parent_feature()}>
			<EntityLinks entities={[glb.parent_feature]} />
		</Row>
	{/if}
	{#if loc?.quadrangle}
		<Row label={m.feature_quadrangle()}>
			<EntityLinks entities={[loc.quadrangle]} />
		</Row>
	{/if}
	{#if loc?.inside_of?.length}
		<Row label={m.feature_inside_of()}>
			<EntityLinks entities={loc.inside_of} />
		</Row>
	{/if}
	{#if glb?.contains?.length}
		<Row label={m.feature_contains()}>
			<EntityLinks entities={glb.contains} />
		</Row>
	{/if}
	{#if glb?.satellite_features?.length}
		<Row label={m.feature_satellite_features()}>
			<EntityLinks entities={glb.satellite_features} />
		</Row>
	{/if}
</Section>

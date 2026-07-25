<script lang="ts">
	import { getContext, untrack } from 'svelte';
	import type { NomenclatureFeature } from '$lib/fetch/nomenclature/fetch';
	import type { FeatureDetailData } from '$lib/fetch/nomenclature/details';
	import { formatNumber, formatQuantity, formatUnit } from '$lib/format/quantities';
	import { formatIsoDate } from '$lib/format/date';
	import * as m from '$lib/paraglide/messages.js';
	import * as Tooltip from '$lib/components/ui/tooltip/index.js';
	import Section from './kit/Section.svelte';
	import Row from './kit/Row.svelte';
	import EntityLinks from './kit/EntityLinks.svelte';
	import { featureTypeSlug } from '$lib/fetch/groups/registry';
	import { featureTypeDescription, featureTypeLabel } from '$lib/format/feature-type';
	import type { AppState } from '$lib/state/app-state.svelte';
	import { applyGroup, serializeUrl } from '$lib/state/url';

	const appState = getContext<AppState | undefined>('appState');

	interface Props {
		feature: NomenclatureFeature;
		detail: FeatureDetailData | null;
	}

	let { feature, detail }: Props = $props();

	let glb = $derived(detail?.global);
	let wd = $derived(detail?.global?.wikidata);
	let loc = $derived(detail?.localized);

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

	// The type row links to that type's collection page. The slug comes from the
	// group index (untracked so resolving it doesn't re-trigger the load).
	let typeSlug = $state<string | undefined>(undefined);
	$effect(() => {
		const code = feature.typeCode;
		untrack(() => {
			featureTypeSlug(code).then((slug) => {
				if (feature.typeCode === code) typeSlug = slug;
			});
		});
	});
	// Names live on the type's `ft-` slug, so both wait on that lookup; the IAU
	// code stands in for the moment before it lands.
	let typeLabel = $derived(featureTypeLabel(typeSlug) ?? feature.typeCode);
	let typeDescription = $derived(featureTypeDescription(typeSlug) ?? null);
	let typeHref = $derived(
		typeSlug && appState ? serializeUrl(applyGroup(appState.view, typeSlug, typeLabel)) : undefined
	);

	function openType(e: MouseEvent) {
		if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
		if (!appState || !typeSlug) return;
		e.preventDefault();
		appState.setGroup(typeSlug, typeLabel);
	}
</script>

{#snippet typeText()}
	{#if typeHref}
		<a href={typeHref} onclick={openType} class="pointer-events-auto hover:text-foreground"
			>{typeLabel}</a
		>
	{:else}
		{typeLabel}
	{/if}
{/snippet}

<Section title={m.surface_feature()}>
	<Row label={m.feature_type()}>
		{#if typeDescription}
			<Tooltip.Root>
				<Tooltip.Trigger>
					{#snippet child({ props })}
						<span class="cursor-help decoration-dotted underline underline-offset-2" {...props}>
							{@render typeText()}
						</span>
					{/snippet}
				</Tooltip.Trigger>
				<Tooltip.Content>{typeDescription}</Tooltip.Content>
			</Tooltip.Root>
		{:else}
			{@render typeText()}
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
	{#if glb?.approval_date}
		<Row label={m.feature_named_date()} value={formatIsoDate(glb.approval_date)} />
	{/if}
	{#if glb?.origin}
		<Row label={m.feature_origin()}>
			<span class="block whitespace-normal text-end">{glb.origin}</span>
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

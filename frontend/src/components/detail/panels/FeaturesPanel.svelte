<script lang="ts">
	import ObjectDescription from '../sections/ObjectDescription.svelte';
	import FeatureTypeFilter from '../sections/FeatureTypeFilter.svelte';
	import PaginatedMemberList from '../members/PaginatedMemberList.svelte';
	import SourcesFooter from '../sections/SourcesFooter.svelte';
	import type { SurfaceState } from '../state/surface-state.svelte';
	import type { AppState } from '$lib/state/app-state.svelte';
	import type { PositionedBody } from '$lib/types/objects';

	interface Props {
		body: PositionedBody | null;
		surface: SurfaceState;
		appState: AppState;
	}

	let { body, surface, appState }: Props = $props();
</script>

<div class="flex flex-col gap-4">
	{#if surface.quadText}
		<ObjectDescription
			extract={surface.quadText.extract}
			wikipediaUrl={surface.quadText.url}
			truncateLength={200}
		/>
	{/if}
	{#if body && surface.hasFeatures}
		<FeatureTypeFilter
			bodyId={body.data.id}
			quad={surface.selectedQuad}
			selected={appState.view.featureType}
			onselect={(code) => appState.setFeatureType(code)}
		/>
		{@const narrowed = surface.selectedQuad != null || appState.view.featureType != null}
		<PaginatedMemberList
			source={{
				kind: 'features',
				bodyId: body.data.id,
				quad: surface.selectedQuad ?? undefined,
				featureType: appState.view.featureType ?? undefined
			}}
			totalCount={surface.selectedQuad ? (surface.selectedQuadCount ?? 0) : surface.featureTotal}
			localizedNames={surface.featureNames}
			fallback={narrowed ? [] : (surface.notableFeatures ?? [])}
			onHoverFeature={(id) => (surface.hoveredFeatureId = id)}
		/>
	{/if}
	<!-- The gazetteer behind every name and diameter listed here, and — when a
	     quadrangle is selected — the licence for its extract, which is a
	     different article from the one the overview tab covers. -->
	<SourcesFooter global={null} nomenclature wikipediaLicensed={!!surface.quadText?.extract} />
</div>
